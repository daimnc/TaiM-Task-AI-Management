"""Phase 4.3 deterministic engine tests (planner_assist.py). No API, provider or security tests here: see test_planner_assist_ai.py."""
import ast
import copy
import pathlib
import sys
import unittest
from datetime import date

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from base import TODAY, ApiTestCase  # noqa: E402

import planner_assist as pa  # noqa: E402
import store  # noqa: E402

STUDENT = {"session_minutes": 45}


def task(title, due="2026-11-20", importance="medium", status="not_started", progress=0, category="assignment", subs=None, subject="s1", **extra):
    raw = {"title": title, "deadline": due, "importance": importance, "status": status, "progress_pct": progress,
           "category": category, "subject_id": subject}
    if subs is not None:
        raw["subtasks"] = [{"subtask_id": f"x{i}", "title": "s", "estimated_minutes": m, "status": st} for i, (m, st) in enumerate(subs)]
    raw.update(extra)
    return raw


def plan(tasks, hours=2, horizon=7, student=STUDENT, subjects=(), today=TODAY):
    docs = [(k, v) for k, v in tasks.items()]
    return pa.build_plan_assist(docs, list(subjects), student, today, hours, horizon)


def order(p):
    return [t["taskId"] for t in p["prioritizedTasks"]]


class FilteringAndEstimates(unittest.TestCase):
    def test_completed_excluded_and_in_progress_at_100_included(self):
        p = plan({"done": task("D", status="completed", progress=100), "open": task("O", status="in_progress", progress=100)})
        self.assertEqual(order(p), ["open"])
        self.assertEqual(p["prioritizedTasks"][0]["remainingMinutes"], pa.MIN_PROVISIONAL_MINUTES)

    def test_subtask_estimate_uses_only_unfinished_minutes(self):
        t = plan({"a": task("A", subs=[(30, "completed"), (40, "not_started"), (20, "not_started")])})["prioritizedTasks"][0]
        self.assertEqual((t["remainingMinutes"], t["estimateSource"]), (60, "subtasks"))

    def test_provisional_is_labelled_everywhere(self):
        p = plan({"a": task("A", category="exam", progress=50)})
        t = p["prioritizedTasks"][0]
        self.assertEqual(t["estimateSource"], "provisional")
        self.assertIn("not a measurement", t["estimateLabel"])
        self.assertIn("Provisional time estimate", t["reasons"])
        self.assertEqual(p["schedule"][0]["items"][0]["estimateSource"], "provisional")
        self.assertTrue(any("provisional" in n and "not measurements" in n for n in p["limitations"]))
        self.assertEqual(t["remainingMinutes"], 70)  # 45 min * 3 sessions * 50% = 67.5 -> next multiple of 5

    def test_no_provisional_note_when_all_estimates_come_from_subtasks(self):
        p = plan({"a": task("A", subs=[(30, "not_started")])})
        self.assertFalse(any("provisional" in n for n in p["limitations"]))

    def test_all_subtasks_done_but_task_open_is_provisional_not_zero(self):
        t = plan({"a": task("A", subs=[(30, "completed")])})["prioritizedTasks"][0]
        self.assertEqual(t["estimateSource"], "provisional")

    def test_session_minutes_scales_provisional_and_bad_value_defaults(self):
        self.assertEqual(plan({"a": task("A")}, student={"session_minutes": 90})["prioritizedTasks"][0]["remainingMinutes"], 180)
        self.assertEqual(plan({"a": task("A")}, student={"session_minutes": 7})["prioritizedTasks"][0]["remainingMinutes"], 90)


class Prioritisation(unittest.TestCase):
    def test_overdue_first_then_importance_then_most_overdue(self):
        p = plan({"low_old": task("a", due="2026-11-01", importance="low"), "high_new": task("b", due="2026-11-15", importance="high"),
                  "high_old": task("c", due="2026-11-10", importance="high"), "soon": task("d", due="2026-11-16", importance="high")})
        self.assertEqual(order(p), ["high_old", "high_new", "low_old", "soon"])
        self.assertEqual(p["prioritizedTasks"][0]["reasons"][0], "Overdue by 6 days")

    def test_not_blind_earliest_deadline_first(self):
        p = plan({"tiny": task("Tiny", due="2026-11-17", importance="low", category="quiz", subs=[(15, "not_started")]),
                  "big": task("Big", due="2026-11-19", importance="high", subs=[(360, "not_started")])})
        self.assertEqual(order(p), ["big", "tiny"])

    def test_due_today_beats_later_work_of_equal_importance(self):
        p = plan({"later": task("L", due="2026-11-25", subs=[(60, "not_started")]), "now": task("N", due="2026-11-16", subs=[(60, "not_started")])})
        self.assertEqual(order(p)[0], "now")

    def test_deterministic_with_ties(self):
        tasks = {k: task(k, due="2026-11-20") for k in ("c", "a", "b")}
        self.assertEqual(order(plan(tasks)), ["a", "b", "c"])
        self.assertEqual(plan(tasks), plan(dict(reversed(list(tasks.items())))))

    def test_reasons_are_plain_language(self):
        t = plan({"a": task("A", due="2026-11-17", importance="high", status="in_progress", progress=40)})["prioritizedTasks"][0]
        self.assertEqual(t["reasons"][:3], ["Due tomorrow", "High importance", "Already started (40% done)"])


class MissingAndInvalidDeadlines(unittest.TestCase):
    CASES = {"none": None, "empty": "", "blank": "  ", "junk": "next week", "not_a_date": "2026-13-45", "short": "2026-1-5", "number": 20261120}

    def test_visible_in_priority_list_never_scheduled_never_given_a_date(self):
        tasks = {"dated": task("D")}
        tasks.update({k: task(k, due=v) for k, v in self.CASES.items()})
        p = plan(tasks)
        self.assertEqual(len(p["prioritizedTasks"]), 1 + len(self.CASES))
        self.assertEqual(order(p)[0], "dated")
        self.assertEqual({u["taskId"] for u in p["warnings"]["unscheduledTasks"]}, set(self.CASES))
        scheduled_ids = {i["taskId"] for d in p["schedule"] for i in d["items"]}
        self.assertEqual(scheduled_ids, {"dated"})
        for t in p["prioritizedTasks"][1:]:
            self.assertIsNone(t["deadline"]); self.assertIsNone(t["daysUntil"]); self.assertFalse(t["scheduled"]); self.assertEqual(t["plannedMinutes"], 0)
        for u in p["warnings"]["unscheduledTasks"]:
            self.assertIn(u["reason"], ("missing_deadline", "invalid_deadline")); self.assertIn("did not", u["message"])
        self.assertEqual(p["capacity"]["totalNeededMinutes"], p["prioritizedTasks"][0]["remainingMinutes"])

    def test_missing_vs_invalid_reason_codes(self):
        w = plan({"a": task("A", due=None), "b": task("B", due="garbage")})["warnings"]["unscheduledTasks"]
        self.assertEqual({u["taskId"]: u["reason"] for u in w}, {"a": "missing_deadline", "b": "invalid_deadline"})

    def test_only_undated_tasks(self):
        p = plan({"a": task("A", due=None)})
        self.assertEqual(p["nextTask"]["taskId"], "a")
        self.assertEqual(p["capacity"]["allocatedMinutes"], 0)
        self.assertTrue(all(not d["items"] for d in p["schedule"]))


class SchedulerCapacity(unittest.TestCase):
    def test_never_exceeds_daily_capacity_and_splits_across_days(self):
        p = plan({"a": task("A", due="2026-11-22", subs=[(300, "not_started")])}, hours=2)
        self.assertEqual([d["allocatedMinutes"] for d in p["schedule"][:3]], [120, 120, 60])
        for d in p["schedule"]:
            self.assertLessEqual(d["allocatedMinutes"], d["capacityMinutes"])
            self.assertEqual(d["allocatedMinutes"] + d["remainingCapacityMinutes"], d["capacityMinutes"])

    def test_never_scheduled_after_deadline(self):
        p = plan({"a": task("A", due="2026-11-17", subs=[(500, "not_started")])}, hours=2)
        for d in p["schedule"]:
            if d["dayOffset"] > 1:
                self.assertEqual(d["items"], [])

    def test_work_with_far_deadline_fills_spare_capacity(self):
        p = plan({"a": task("A", due="2026-12-30", subs=[(100, "not_started")])}, hours=1, horizon=3)
        self.assertEqual([d["allocatedMinutes"] for d in p["schedule"]], [60, 40, 0])

    def test_must_start_today_task_is_served_before_higher_priority_roomy_task(self):
        p = plan({"roomy": task("Roomy", due="2026-11-17", importance="high", subs=[(30, "not_started")]),
                  "tight": task("Tight", due="2026-11-18", importance="low", subs=[(300, "not_started")])}, hours=2)
        self.assertEqual(order(p)[0], "roomy")
        self.assertEqual([(i["taskId"], i["minutes"]) for i in p["schedule"][0]["items"]], [("tight", 120)])
        self.assertEqual(p["warnings"]["atRiskTasks"], [])

    def test_on_time_deadline_capacity_is_reserved_before_overdue_catch_up(self):
        p = plan({"late": task("Late", due="2026-11-10", subs=[(120, "not_started")]),
                  "soon": task("Soon", due="2026-11-17", subs=[(180, "not_started")])}, hours=2)
        today_items = [(i["taskId"], i["minutes"]) for i in p["schedule"][0]["items"]]
        self.assertEqual(today_items, [("soon", 120)])
        tomorrow_items = [(i["taskId"], i["minutes"]) for i in p["schedule"][1]["items"]]
        self.assertEqual(tomorrow_items[0], ("soon", 60))
        self.assertNotIn("soon", {a["taskId"] for a in p["warnings"]["atRiskTasks"]})

    def test_cumulative_same_deadline_workload_is_reserved(self):
        p = plan({"a": task("A", due="2026-11-17", subs=[(90, "not_started")]),
                  "b": task("B", due="2026-11-17", subs=[(90, "not_started")]),
                  "late": task("Late", due="2026-11-10", subs=[(120, "not_started")])}, hours=2)
        today = [(i["taskId"], i["minutes"]) for i in p["schedule"][0]["items"]]
        self.assertEqual(sum(m for task_id, m in today if task_id in ("a", "b")), 60)
        self.assertFalse({"a", "b"} & {a["taskId"] for a in p["warnings"]["atRiskTasks"]})

    def test_overdue_work_yields_only_when_on_time_work_needs_capacity(self):
        p = plan({"late": task("Late", due="2026-11-10", subs=[(60, "not_started")]),
                  "now": task("Now", due="2026-11-16", importance="high", subs=[(90, "not_started")])}, hours=2)
        self.assertEqual([(i["taskId"], i["minutes"]) for i in p["schedule"][0]["items"]], [("now", 90), ("late", 30)])
        self.assertEqual(p["schedule"][0]["items"][0]["overdue"], False)

    def test_horizon_and_totals(self):
        p = plan({"a": task("A", subs=[(50, "not_started")])}, hours=0.5, horizon=3)
        c = p["capacity"]
        self.assertEqual((len(p["schedule"]), c["dailyMinutes"], c["totalAvailableMinutes"], c["horizonDays"]), (3, 30, 90, 3))
        self.assertEqual(c["allocatedMinutes"] + c["unallocatedMinutes"], c["totalNeededMinutes"])
        self.assertEqual([d["date"] for d in p["schedule"]], ["2026-11-16", "2026-11-17", "2026-11-18"])


class Warnings(unittest.TestCase):
    def test_overdue_counted_and_flagged(self):
        w = plan({"a": task("A", due="2026-11-14")})["warnings"]
        self.assertEqual(w["overdueCount"], 1)
        self.assertEqual(w["atRiskTasks"][0]["reason"], "overdue")

    def test_task_that_cannot_fit_even_alone_is_at_risk(self):
        p = plan({"a": task("A", due="2026-11-17", subs=[(600, "not_started")])}, hours=2)
        r = p["warnings"]["atRiskTasks"][0]
        self.assertEqual(r["reason"], "exceeds_capacity_before_deadline")
        self.assertEqual(r["unallocatedMinutes"], 600 - 240)
        self.assertTrue(p["warnings"]["overloaded"]); self.assertEqual(p["warnings"]["deficitMinutes"], 360)

    def test_competition_causes_not_fully_scheduled_and_overloaded_days(self):
        p = plan({"a": task("A", due="2026-11-17", subs=[(200, "not_started")]), "b": task("B", due="2026-11-17", subs=[(200, "not_started")])}, hours=2)
        self.assertEqual(p["warnings"]["deficitMinutes"], 160)
        self.assertEqual({a["reason"] for a in p["warnings"]["atRiskTasks"]}, {"not_fully_scheduled"})
        self.assertEqual(p["warnings"]["overloadedDays"], ["2026-11-16", "2026-11-17"])
        self.assertTrue(all(d["overloaded"] for d in p["schedule"][:2]))

    def test_each_fits_alone_but_not_together(self):
        p = plan({"a": task("A", due="2026-11-17", subs=[(150, "not_started")]), "b": task("B", due="2026-11-17", subs=[(150, "not_started")])}, hours=2)
        self.assertEqual({a["reason"] for a in p["warnings"]["atRiskTasks"]}, {"not_fully_scheduled"})
        self.assertEqual(p["warnings"]["deficitMinutes"], 60)

    def test_feasible_plan_has_no_warnings(self):
        w = plan({"a": task("A", due="2026-11-20", subs=[(60, "not_started")])})["warnings"]
        self.assertEqual((w["overdueCount"], w["overloaded"], w["atRiskTasks"], w["overloadedDays"], w["deficitMinutes"]), (0, False, [], [], 0))

    def test_work_due_beyond_horizon_is_not_a_deficit(self):
        w = plan({"a": task("A", due="2026-12-31", subs=[(900, "not_started")])}, hours=1, horizon=3)["warnings"]
        self.assertEqual((w["overloaded"], w["atRiskTasks"]), (False, []))


class EdgeCases(unittest.TestCase):
    def test_empty_and_all_completed(self):
        for tasks in ({}, {"a": task("A", status="completed")}):
            p = plan(tasks)
            self.assertIsNone(p["nextTask"]); self.assertEqual(p["prioritizedTasks"], [])
            self.assertEqual(p["tips"], []); self.assertIn("no open tasks", p["summary"])
            self.assertEqual(len(p["schedule"]), 7)

    def test_next_task_is_first_priority_and_rank_numbers(self):
        p = plan({"a": task("A", due="2026-11-18"), "b": task("B", due="2026-11-16")})
        self.assertEqual(p["nextTask"]["taskId"], order(p)[0])
        self.assertEqual([t["rank"] for t in p["prioritizedTasks"]], [1, 2])

    def test_subject_names_and_unknown_subject(self):
        p = plan({"a": task("A", subject="s1"), "b": task("B", subject="gone")}, subjects=[{"subject_id": "s1", "subject_name": "Math"}])
        self.assertEqual({t["taskId"]: t["subjectName"] for t in p["prioritizedTasks"]}, {"a": "Math", "b": "Unknown subject"})

    def test_corrupt_values_do_not_crash(self):
        p = plan({"a": {"title": 5, "importance": "urgent", "progress_pct": "x", "status": "weird", "subtasks": "no", "deadline": "2026-11-18"}})
        t = p["prioritizedTasks"][0]
        self.assertEqual((t["title"], t["importance"], t["progressPct"], t["status"]), ("Untitled task", "medium", 0, "not_started"))

    def test_huge_subtask_minutes_are_handled_without_looping(self):
        p = plan({"a": task("A", subs=[(9007199254740991, "not_started")])})
        self.assertLessEqual(p["capacity"]["allocatedMinutes"], p["capacity"]["totalAvailableMinutes"])

    def test_rule_coaching_limits_and_content(self):
        p = plan({"a": task("A", due="2026-11-10"), "b": task("B", due=None), "c": task("C", due="2026-11-17", subs=[(900, "not_started")])})
        self.assertLessEqual(len(p["tips"]), 3)
        self.assertTrue(all(set(t) == {"focus", "text"} for t in p["tips"]))
        self.assertIn("overdue", [t["focus"] for t in p["tips"]])

    def test_input_is_not_modified(self):
        docs = [("a", task("A", subs=[(30, "not_started")])), ("b", task("B", due=None))]
        before, subjects = copy.deepcopy(docs), [{"subject_id": "s1", "subject_name": "M"}]
        pa.build_plan_assist(docs, subjects, STUDENT, TODAY, 2, 7)
        self.assertEqual(docs, before); self.assertEqual(subjects, [{"subject_id": "s1", "subject_name": "M"}])

    def test_module_has_no_database_network_flask_or_ai_imports(self):
        tree = ast.parse(pathlib.Path(pa.__file__).read_text(encoding="utf-8"))
        names = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
        names |= {n.module.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
        self.assertEqual(names - {"math", "re", "datetime", "dates"}, set())


class RealStoreIsolation(ApiTestCase):
    """The engine fed by the real store layer (fake Firestore): only the signed-in student's data, and no writes."""

    def test_only_own_tasks_and_no_writes(self):
        alice_math = self.add_subject("alice", "Alice Math")["subject_id"]
        self.add_task("alice", title="Alice task", subject_id=alice_math)
        self.add_task("bob", title="Bob secret task")
        writes_before = len(self.db.writes)
        p = pa.build_plan_assist(store.list_task_docs(self.db, "alice"), store.list_subjects(self.db, "alice"),
                                 store.get_student(self.db, "alice", {"name": "Alice"}), TODAY, 2, 7)
        self.assertEqual([t["title"] for t in p["prioritizedTasks"]], ["Alice task"])
        self.assertEqual(p["prioritizedTasks"][0]["subjectName"], "Alice Math")
        self.assertNotIn("Bob", str(p))
        self.assertEqual(len(self.db.writes), writes_before)

    def test_fresh_student_without_a_student_document(self):
        p = pa.build_plan_assist(store.list_task_docs(self.db, "nobody"), [], store.get_student(self.db, "nobody", {}), TODAY, 2, 7)
        self.assertIsNone(p["nextTask"])


if __name__ == "__main__":
    unittest.main()
