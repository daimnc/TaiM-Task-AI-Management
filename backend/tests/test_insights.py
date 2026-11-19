"""Phase 4.2 Batch 1: the AI Insights facts engine (insights.py). No AI, no network, no database writes.

Most tests feed plain dicts to the pure functions. The last class feeds data that the real API and store produced, so the
engine is proven to accept the real shapes, to see only one student's data and to write nothing.
"""
import copy
import json
import pathlib
import random
import re
import sys
import unittest
from datetime import date, timedelta

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from base import ApiTestCase, TODAY  # noqa: E402  (TODAY = Monday 2026-11-16)

import insights  # noqa: E402
import store  # noqa: E402
from insights import (AREAS, DATE_DISCLOSURE, HISTORY_DISCLOSURE, HORIZON_DAYS, MAX_SUBJECT_ROWS, MAX_UPCOMING,  # noqa: E402
                      build_facts, flatten_facts, rule_based_insights)
from progress import build_progress  # noqa: E402

SUBJECTS = [{"subject_id": "s1", "subject_name": "Programming"}, {"subject_id": "s2", "subject_name": "Databases"},
            {"subject_id": "s3", "subject_name": "Research"}]


def iso(offset):
    return (TODAY + timedelta(days=offset)).isoformat()


def task(n, subject="s1", due=14, status="not_started", importance="medium", subtasks=None, done=None, **over):
    """(task_id, raw stored task). `due` and `done` are day offsets from TODAY. `done` sets completed_on."""
    data = {"task_id": f"t{n:03d}", "student_id": "alice", "subject_id": subject, "title": f"Task {n}",
            "deadline": iso(due) if isinstance(due, int) else due, "importance": importance, "category": "assignment",
            "progress_pct": 0, "status": status}
    if status == "completed":
        data["progress_pct"] = 100
        if done is not None:
            data["completed_on"] = iso(done)
    if subtasks is not None:
        data["subtasks"] = [{"subtask_id": f"u{n}_{i}", "title": f"Step {i}", "estimated_minutes": m, "status": s}
                            for i, (m, s) in enumerate(subtasks)]
    data.update(over)
    return data["task_id"], data


def facts(tasks, subjects=SUBJECTS, today=TODAY):
    return build_facts(tasks, subjects, today)


def finished(count, margins, start=100):
    """Completed tasks whose deadline is `margin` days after their completion day (completed on day offset -1)."""
    return [task(start + i, status="completed", due=-1 + m, done=-1) for i, m in zip(range(count), margins)]


class EmptyAndShapeTests(unittest.TestCase):
    def test_no_tasks_gives_zeros_and_an_honest_empty_summary(self):
        f = facts([])
        self.assertEqual(set(f), {"asOf", "completion", "workload", "deadlines", "patterns", "dataQuality"})
        self.assertEqual(f["asOf"], "2026-11-16")
        self.assertEqual((f["completion"]["totalTasks"], f["completion"]["open"], f["completion"]["completionRate"]), (0, 0, 0))
        self.assertEqual(f["workload"]["subjects"], [])
        self.assertEqual(f["deadlines"]["perDay"], [0] * HORIZON_DAYS)
        self.assertFalse(f["deadlines"]["heavy"])
        self.assertFalse(f["patterns"]["enoughForPatterns"])
        r = rule_based_insights(f)
        self.assertIn("No tasks are recorded yet", r["summary"])
        self.assertEqual([i["area"] for i in r["insights"]], list(AREAS))
        self.assertEqual(r["suggestions"], [])

    def test_facts_are_json_serialisable_and_inputs_are_not_modified(self):
        tasks = [task(1, due=-2), task(2, status="completed", due=3, done=-1, subtasks=[(10, "completed")]), task(3, due="bad")]
        before = copy.deepcopy((tasks, SUBJECTS))
        f = facts(tasks)
        json.dumps(f)
        json.dumps(rule_based_insights(f))
        self.assertEqual((tasks, SUBJECTS), before)

    def test_the_result_does_not_depend_on_input_order(self):
        tasks = [task(i, subject=("s1", "s2", "s3")[i % 3], due=(i * 2) % 12 - 2, importance=("low", "medium", "high")[i % 3],
                      status="completed" if i % 4 == 0 else "not_started", done=-(i % 5) if i % 4 == 0 else None) for i in range(1, 30)]
        expected = facts(tasks)
        for seed in range(5):
            shuffled = tasks[:]
            random.Random(seed).shuffle(shuffled)
            self.assertEqual(facts(shuffled), expected)

    def test_the_module_has_no_database_network_or_ai_imports(self):
        source = (pathlib.Path(insights.__file__)).read_text(encoding="utf-8")
        imports = set(re.findall(r"^(?:from|import)\s+([A-Za-z_][\w.]*)", source, re.M))
        self.assertEqual(imports, {"statistics", "datetime", "dates", "progress", "validation"})


class CompletionTests(unittest.TestCase):
    def test_counts_and_rate_use_status(self):
        tasks = [task(1, status="completed", done=-1), task(2, status="completed", done=-2), task(3, status="in_progress"),
                 task(4), task(5)]
        c = facts(tasks)["completion"]
        self.assertEqual((c["totalTasks"], c["completed"], c["open"], c["inProgress"], c["notStarted"], c["completionRate"]),
                         (5, 2, 3, 1, 2, 40))

    def test_100_percent_without_completing_is_still_open(self):
        t = task(1, status="in_progress", progress_pct=100)
        c = facts([t])["completion"]
        self.assertEqual((c["completed"], c["open"], c["completionRate"]), (0, 1, 0))

    def test_rates_and_weekly_figures_match_the_existing_progress_calculation(self):
        tasks = [task(1, status="completed", done=-1, due=2), task(2, status="completed", done=-8, due=-9),
                 task(3, status="completed", done=-9, due=-10), task(4, due=-3), task(5, due=9), task(6, status="completed", due=1)]
        f, p = facts(tasks), build_progress(tasks, TODAY)
        self.assertEqual((f["completion"]["completionRate"], f["completion"]["weeklyCompletion"], f["completion"]["weeklyChange"]),
                         (p["completionRate"], p["weeklyCompletion"], p["weeklyChange"]))
        self.assertEqual(f["deadlines"]["overdue"], p["overdue"])
        enough = facts(tasks + finished(5, [1, 1, 1, 1, 1]))
        self.assertEqual(enough["patterns"]["onTimeRate"], build_progress(tasks + finished(5, [1, 1, 1, 1, 1]), TODAY)["onTimeRate"])

    def test_weekly_change_is_marked_unknown_when_last_week_had_no_completions(self):
        c = facts([task(1, status="completed", done=0)])["completion"]
        self.assertEqual((c["weeklyCompletion"], c["weeklyChange"], c["weeklyChangeKnown"]), ([0, 0, 0, 1], 0, False))
        text = rule_based_insights(facts([task(1, status="completed", done=0)]))["insights"][0]["text"]
        for word in ("last week", "up ", "down ", "unchanged"):
            self.assertNotIn(word, text)  # no invented comparison

    def test_weekly_change_is_reported_when_it_can_be_calculated(self):
        tasks = [task(1, status="completed", done=-7), task(2, status="completed", done=-6), task(3, status="completed", done=0)]  # last week: Mon+Tue
        c = facts(tasks)["completion"]
        self.assertEqual((c["weeklyCompletion"], c["weeklyChange"], c["weeklyChangeKnown"]), ([0, 0, 2, 1], -50, True))
        self.assertIn("down 50%", rule_based_insights(facts(tasks))["insights"][0]["text"])

    def test_subtask_progress_counts_open_tasks_only(self):
        tasks = [task(1, status="in_progress", subtasks=[(10, "completed"), (20, "not_started"), (30, "not_started")]),
                 task(2, status="completed", done=-1, subtasks=[(10, "completed"), (10, "completed")])]
        c = facts(tasks)["completion"]
        self.assertEqual((c["openSubtasksDone"], c["openSubtasksTotal"]), (1, 3))


class WorkloadTests(unittest.TestCase):
    def test_subjects_are_ranked_by_open_tasks_then_name_and_labelled_in_that_order(self):
        tasks = [task(1, "s2"), task(2, "s2"), task(3, "s1"), task(4, "s3"), task(5, "s2", status="completed", done=-1)]
        rows = facts(tasks)["workload"]["subjects"]
        self.assertEqual([(r["label"], r["name"], r["openTasks"], r["sharePct"]) for r in rows],
                         [("S1", "Databases", 2, 50), ("S2", "Programming", 1, 25), ("S3", "Research", 1, 25)])

    def test_per_subject_figures(self):
        tasks = [task(1, "s1", due=-1, importance="high"), task(2, "s1", due=7, importance="high"), task(3, "s1", due=8),
                 task(4, "s1", due="not-a-date"), task(5, "s1", status="completed", due=-5, done=-1, importance="high")]
        row = facts(tasks)["workload"]["subjects"][0]
        self.assertEqual((row["openTasks"], row["overdue"], row["highImportance"], row["dueWithin7Days"]), (4, 1, 2, 1))

    def test_remaining_minutes_count_only_unfinished_subtasks_of_open_tasks_and_nothing_is_guessed(self):
        tasks = [task(1, subtasks=[(30, "completed"), (45, "not_started"), (15, "not_started")]),
                 task(2),  # no subtasks: no estimate, adds nothing
                 task(3, status="completed", done=-1, subtasks=[(500, "not_started")])]  # completed parent: ignored
        w = facts(tasks)["workload"]
        self.assertEqual((w["subjects"][0]["remainingMinutes"], w["remainingMinutesTotal"]), (60, 60))
        self.assertEqual((w["subjects"][0]["unestimatedTasks"], w["unestimatedTasksTotal"]), (1, 1))

    def test_a_missing_or_deleted_subject_is_grouped_as_unknown_not_dropped(self):
        tasks = [task(1, "gone"), task(2, ""), task(3, "s1")]
        rows = facts(tasks)["workload"]["subjects"]
        self.assertEqual([(r["name"], r["openTasks"], r["subjectId"]) for r in rows], [("Unknown subject", 2, ""), ("Programming", 1, "s1")])

    def test_subjects_without_open_tasks_are_not_listed(self):
        rows = facts([task(1, "s1"), task(2, "s2", status="completed", done=-1)])["workload"]["subjects"]
        self.assertEqual([r["name"] for r in rows], ["Programming"])

    def test_only_the_top_subjects_are_listed_and_the_rest_are_summed(self):
        subjects = [{"subject_id": f"x{i}", "subject_name": f"Subject {i:02d}"} for i in range(12)]
        tasks = [task(i, f"x{i}") for i in range(12)] + [task(50, "x11"), task(51, "x11")]
        w = facts(tasks, subjects)["workload"]
        self.assertEqual(len(w["subjects"]), MAX_SUBJECT_ROWS)
        self.assertEqual(w["subjects"][0]["name"], "Subject 11")
        self.assertEqual(w["otherSubjects"], {"count": 4, "openTasks": 4})
        self.assertEqual(sum(r["openTasks"] for r in w["subjects"]) + w["otherSubjects"]["openTasks"], w["openTasks"])

    def test_concentration_needs_enough_open_tasks_and_a_big_enough_share(self):
        self.assertTrue(facts([task(1, "s1"), task(2, "s1"), task(3, "s2"), task(4, "s3")])["workload"]["concentrated"])  # 4 open, 50%
        self.assertFalse(facts([task(1, "s1"), task(2, "s1"), task(3, "s2")])["workload"]["concentrated"])  # only 3 open
        self.assertFalse(facts([task(1, "s1"), task(2, "s2"), task(3, "s3"), task(4, "s3"), task(5, "s2"), task(6, "s1"), task(7, "s1")])
                         ["workload"]["concentrated"])  # 7 open, top subject has 3 = 43%
        w = facts([task(1, "s1"), task(2, "s1"), task(3, "s1"), task(4, "s2")])["workload"]
        self.assertEqual((w["topSubjectShare"], w["concentrated"]), (75, True))


class DeadlineTests(unittest.TestCase):
    def test_bucket_boundaries(self):
        offsets = [-1, 0, 1, 3, 4, 7, 8]
        d = facts([task(i, due=o) for i, o in enumerate(offsets, 1)])["deadlines"]
        self.assertEqual((d["overdue"], d["dueToday"], d["dueIn1To3"], d["dueIn4To7"], d["dueLater"]), (1, 1, 2, 2, 1))
        self.assertEqual(d["dueWithin7Days"], 5)

    def test_only_open_tasks_with_a_readable_deadline_are_counted(self):
        tasks = [task(1, due=-5, status="completed", done=-6), task(2, due="2026-13-45"), task(3, due=""), task(4, due=2)]
        d = facts(tasks)["deadlines"]
        self.assertEqual((d["overdue"], d["dueIn1To3"], d["noValidDeadline"]), (0, 1, 2))
        self.assertEqual(facts(tasks)["dataQuality"]["openWithoutValidDeadline"], 2)

    def test_per_day_counts_cover_today_to_13_days_ahead_and_exclude_overdue(self):
        d = facts([task(1, due=-2), task(2, due=0), task(3, due=0), task(4, due=13), task(5, due=14)])["deadlines"]
        self.assertEqual(len(d["perDay"]), HORIZON_DAYS)
        self.assertEqual((d["perDay"][0], d["perDay"][13], sum(d["perDay"])), (2, 1, 3))
        self.assertEqual((d["peakDayOffset"], d["peakDayCount"]), (0, 2))

    def heavy(self, offsets, overdue=0):
        tasks = [task(i, due=o) for i, o in enumerate(offsets, 1)] + [task(100 + i, due=-1 - i) for i in range(overdue)]
        d = facts(tasks)["deadlines"]
        return d["heavy"], d["heavyReason"], d["dueWithin3Days"]

    def test_three_open_tasks_due_within_3_days_is_heavy_and_the_boundary_is_day_3(self):
        self.assertEqual(self.heavy([0, 1, 3]), (True, "cluster", 3))      # today, tomorrow and day 3: all inside
        self.assertEqual(self.heavy([1, 2, 3]), (True, "cluster", 3))
        self.assertEqual(self.heavy([0, 0, 0]), (True, "cluster", 3))      # all due today
        self.assertEqual(self.heavy([2, 3, 4]), (False, None, 2))          # day 4 is outside "within 3 days"
        self.assertEqual(self.heavy([0, 1, 4]), (False, None, 2))
        self.assertEqual(self.heavy([0, 1]), (False, None, 2))             # two are not enough
        self.assertEqual(self.heavy([0, 1, 2, 3, 3]), (True, "cluster", 5))

    def test_tasks_due_later_are_never_a_heavy_stretch_however_close_together(self):
        self.assertEqual(self.heavy([4, 5, 6]), (False, None, 0))          # the case that used to be flagged
        self.assertEqual(self.heavy([5, 6, 7, 8, 9]), (False, None, 0))
        self.assertEqual(self.heavy(list(range(4, 14))), (False, None, 0))  # one per day for 10 days, none within 3 days
        self.assertEqual(self.heavy([10, 10, 10, 10]), (False, None, 0))

    def test_overdue_plus_two_tasks_due_within_3_days_is_heavy_with_the_same_boundary(self):
        self.assertEqual(self.heavy([0, 3], overdue=1), (True, "overdue_plus_soon", 2))   # offsets 0 and 3 are both inside
        self.assertEqual(self.heavy([1, 2], overdue=2), (True, "overdue_plus_soon", 2))
        self.assertEqual(self.heavy([3, 4], overdue=1), (False, None, 1))                 # day 4 is outside
        self.assertEqual(self.heavy([0], overdue=1), (False, None, 1))                    # only one soon
        self.assertEqual(self.heavy([2, 5, 6], overdue=1), (False, None, 1))
        self.assertEqual(self.heavy([0, 1], overdue=0), (False, None, 2))                 # nothing overdue
        self.assertEqual(self.heavy([], overdue=5), (False, None, 0))                     # overdue alone is not this rule
        self.assertEqual(self.heavy([0, 1, 2], overdue=1), (True, "cluster", 3))          # both true: the cluster reason wins

    def test_overdue_tasks_are_never_counted_as_due_within_3_days(self):
        self.assertEqual(self.heavy([0, 1], overdue=1), (True, "overdue_plus_soon", 2))   # 2 soon + 1 overdue is NOT "3 due soon"
        self.assertEqual(self.heavy([2], overdue=2), (False, None, 1))

    def test_one_boundary_is_used_everywhere(self):
        tasks = [task(1, due=-1), task(2, due=0), task(3, due=1), task(4, due=3), task(5, due=4), task(6, due=7), task(7, due=8),
                 task(8, due=2, status="completed", done=-1), task(9, due="bad")]
        d = facts(tasks)["deadlines"]
        self.assertEqual(d["dueWithin3Days"], d["dueToday"] + d["dueIn1To3"])
        self.assertEqual(d["dueWithin3Days"], sum(d["perDay"][0:4]))           # offsets 0..3
        self.assertEqual(d["dueWithin3Days"], sum(1 for u in d["upcoming"] if 0 <= u["daysUntil"] <= 3))
        self.assertEqual((d["dueWithin3Days"], d["soonDays"]), (3, 3))          # completed and unreadable-deadline tasks are not counted
        self.assertEqual(d["dueWithin7Days"], d["dueWithin3Days"] + d["dueIn4To7"])
        for gone in ("windowDays", "busiestWindowStart", "busiestWindowTasks", "firstWindowTasks"):
            self.assertNotIn(gone, d)

    def test_heavy_wording_matches_the_rule(self):
        def deadlines_text(tasks):
            return rule_based_insights(facts(tasks))["insights"][2]["text"]
        self.assertIn("Heavy stretch: 3 open tasks due within 3 days (counting today).", deadlines_text([task(1, due=0), task(2, due=1), task(3, due=3)]))
        self.assertIn("Heavy stretch: you have 1 overdue and 2 open tasks due within 3 days (counting today).",
                      deadlines_text([task(1, due=-1), task(2, due=0), task(3, due=3)]))
        self.assertIn("No heavy stretch: fewer than 3 open tasks are due within 3 days.", deadlines_text([task(1, due=4), task(2, due=5), task(3, due=6)]))

    def test_upcoming_is_sorted_capped_and_linked_to_subject_labels(self):
        tasks = [task(1, "s2", due=5), task(2, "s1", due=-3), task(3, "s1", due=5, importance="high"), task(4, "s3", due=1),
                 task(5, "s1", due=9), task(6, "s1", due=20), task(7, "s1", due=20)]
        d = facts(tasks)
        up = d["deadlines"]["upcoming"]
        self.assertEqual(len(up), MAX_UPCOMING)
        self.assertEqual([u["label"] for u in up], ["T1", "T2", "T3", "T4", "T5"])
        self.assertEqual([u["title"] for u in up], ["Task 2", "Task 4", "Task 3", "Task 1", "Task 5"])  # same day: high importance first
        self.assertEqual([u["daysUntil"] for u in up], [-3, 1, 5, 5, 9])
        labels = {r["subjectId"]: r["label"] for r in d["workload"]["subjects"]}
        self.assertEqual([u["subjectLabel"] for u in up], [labels["s1"], labels["s3"], labels["s1"], labels["s2"], labels["s1"]])


class PatternTests(unittest.TestCase):
    def test_below_the_minimum_no_pattern_is_claimed(self):
        f = facts(finished(4, [1, 2, 3, 4]))
        p = f["patterns"]
        self.assertFalse(p["enoughForPatterns"])
        for key in ("onTimeRate", "lateSharePct", "lastMinuteSharePct", "medianDaysBeforeDeadline", "weekdayPattern"):
            self.assertIsNone(p[key], key)
        self.assertIn("Not enough data yet", rule_based_insights(f)["insights"][3]["text"])

    def test_margins_and_rates_with_enough_history(self):
        p = facts(finished(5, [3, 2, 0, -1, 5]))["patterns"]  # margin = days before the deadline; negative = late
        self.assertEqual((p["enoughForPatterns"], p["completedWithDateAndDeadline"]), (True, 5))
        self.assertEqual((p["onTimeRate"], p["lateSharePct"], p["lastMinuteSharePct"], p["medianDaysBeforeDeadline"]), (80, 20, 20, 2))

    def test_last_minute_means_the_deadline_day_or_the_day_before(self):
        p = facts(finished(6, [0, 1, 1, 2, 3, -2]))["patterns"]
        self.assertEqual(p["lastMinuteSharePct"], 50)

    def test_the_median_of_an_even_number_of_tasks_is_the_lower_middle_value(self):
        self.assertEqual(facts(finished(6, [1, 2, 3, 4, 5, 6]))["patterns"]["medianDaysBeforeDeadline"], 3)

    def test_late_work_is_described_as_late(self):
        f = facts(finished(5, [-3, -3, -3, -3, -3]))
        self.assertEqual(f["patterns"]["onTimeRate"], 0)
        self.assertIn("3 days after the deadline", rule_based_insights(f)["insights"][3]["text"])

    def test_completed_tasks_without_a_usable_day_are_counted_but_not_used(self):
        tasks = finished(5, [1] * 5) + [task(50, status="completed", done=None), task(51, status="completed", completed_on="garbage")]
        f = facts(tasks)
        self.assertEqual((f["patterns"]["completedTotal"], f["patterns"]["completedWithDate"]), (7, 5))
        self.assertEqual(f["dataQuality"]["completedWithoutDate"], 2)

    def test_reopened_and_deleted_tasks_add_no_history(self):
        base = finished(5, [1] * 5)
        reopened = task(60, status="in_progress", due=0, completed_on=iso(-1))  # a stale completion day must be ignored
        # (the store removes completed_on on reopen; even if one were left behind, status decides)
        f = facts(base + [reopened])
        self.assertEqual((f["patterns"]["completedTotal"], f["patterns"]["completedWithDate"], f["completion"]["completed"]), (5, 5, 5))
        self.assertEqual(f["patterns"], facts(base)["patterns"])  # identical to the history without that task; a deleted task is simply absent
        self.assertEqual(f["completion"]["open"], 1)

    def test_weekday_pattern_needs_enough_completions_a_clear_top_day_and_no_tie(self):
        def on(weekday_offsets):  # offsets from the Monday 2026-11-09, one completed task each
            return [task(200 + i, status="completed", due=0, done=o - 7) for i, o in enumerate(weekday_offsets)]
        self.assertIsNone(facts(on([2] * 7))["patterns"]["weekdayPattern"])  # 7 < 8 completions
        clear = facts(on([2, 2, 2, 2, 0, 1, 4, 5]))["patterns"]
        self.assertEqual(clear["weekdayPattern"], {"weekday": 2, "count": 4, "sharePct": 50})
        self.assertEqual(clear["weekdayCounts"], [1, 1, 4, 0, 1, 1, 0])
        self.assertIsNone(facts(on([2, 2, 2, 4, 4, 4, 0, 1]))["patterns"]["weekdayPattern"])  # tie for first
        self.assertIsNone(facts(on([0, 0, 1, 1, 2, 2, 3, 4]))["patterns"]["weekdayPattern"])  # top day below 3
        text = rule_based_insights(facts(on([2, 2, 2, 2, 0, 1, 4, 5])))["insights"][3]["text"]
        self.assertIn("on a Wednesday", text)

    def test_the_completion_date_disclosure_is_always_shown(self):
        for tasks in ([], finished(2, [1, 1]), finished(6, [1] * 6)):
            r = rule_based_insights(facts(tasks))
            self.assertIn(DATE_DISCLOSURE, r["insights"][3]["text"] if tasks else r["notes"])
            self.assertEqual(r["notes"], [DATE_DISCLOSURE, HISTORY_DISCLOSURE])
            self.assertEqual(facts(tasks)["dataQuality"]["notes"], [DATE_DISCLOSURE, HISTORY_DISCLOSURE])
        self.assertIn("not the time you actually spent studying", DATE_DISCLOSURE)
        self.assertIn("reopened or deleted", HISTORY_DISCLOSURE)


class ClaimCheckingTests(unittest.TestCase):
    def test_every_numeric_fact_has_its_own_path_and_value(self):
        f = facts([task(1, "s1", due=-1), task(2, "s1", due=-1), task(3, "s2", due=0), task(4, "s2", due=0)])
        flat = flatten_facts(f)
        self.assertEqual(flat["deadlines.overdue"], 2)
        self.assertEqual(flat["deadlines.dueToday"], 2)  # same number, different fact: a claim can be checked against the right one
        self.assertEqual(flat["workload.subjects.S1.openTasks"], 2)
        self.assertEqual(flat["deadlines.perDay.0"], 2)
        self.assertEqual(flat["completion.totalTasks"], 4)
        self.assertEqual(flat["deadlines.upcoming.T1.daysUntil"], -1)

    def test_text_booleans_and_missing_values_are_not_numeric_facts(self):
        f = facts([task(1)])
        flat = flatten_facts(f)
        self.assertNotIn("deadlines.heavy", flat)
        self.assertNotIn("patterns.onTimeRate", flat)  # None (not enough data) is not a number to be claimed
        self.assertNotIn("workload.subjects.S1.name", flat)
        self.assertTrue(all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in flat.values()))

    def test_a_wrong_claim_does_not_match_its_fact_even_if_the_number_exists_elsewhere(self):
        flat = flatten_facts(facts([task(1, due=-1), task(2, due=-1), task(3, due=0), task(4, due=0), task(5, due=0)]))
        self.assertEqual((flat["deadlines.overdue"], flat["deadlines.dueToday"]), (2, 3))
        self.assertNotEqual(flat["deadlines.overdue"], 3)  # "3 overdue" would be wrong although 3 exists as dueToday


class RuleBasedTextTests(unittest.TestCase):
    def test_one_insight_per_area_in_a_fixed_order_with_no_ai_claims(self):
        tasks = [task(1, "s1", due=-2, importance="high"), task(2, "s1", due=0), task(3, "s1", due=1), task(4, "s2", due=6),
                 task(5, status="completed", done=-1)]
        r = rule_based_insights(facts(tasks))
        self.assertEqual([i["area"] for i in r["insights"]], list(AREAS))
        blob = json.dumps(r)
        for word in ("Gemini", "Groq", "artificial", "AI-generated", "hours"):
            self.assertNotIn(word, blob)
        self.assertLessEqual(len(r["suggestions"]), 3)
        self.assertTrue(all(isinstance(i["text"], str) and i["text"] for i in r["insights"]))

    def test_numbers_in_the_text_come_from_the_facts(self):
        tasks = [task(1, "s1", due=-2), task(2, "s1", due=0), task(3, "s2", due=1), task(4, "s2", due=6), task(5, status="completed", done=-1)]
        f = facts(tasks)
        r = rule_based_insights(f)
        self.assertIn("1 of 5 tasks completed (20%)", r["insights"][0]["text"])
        self.assertIn("1 overdue, 1 due today, 1 due in the next 1 to 3 days, 1 due in 4 to 7 days", r["insights"][2]["text"])
        self.assertIn("1 overdue and 3 due within the next 7 days", r["summary"])

    def test_suggestions_are_tied_to_calculated_facts(self):
        overdue = rule_based_insights(facts([task(1, due=-4), task(2, due=-1)]))["suggestions"]
        self.assertEqual(overdue[0], {"area": "deadlines",
                                      "text": 'Start with "Task 1": it is the most overdue task you have open.'})
        cluster = rule_based_insights(facts([task(1, due=1), task(2, due=2), task(3, due=3)]))["suggestions"]
        self.assertEqual(cluster[0]["area"], "deadlines")
        self.assertIn("Several tasks are due within 3 days; consider starting the earliest one now.", cluster[0]["text"])
        self.assertEqual(rule_based_insights(facts([task(1, due=4), task(2, due=5), task(3, due=6)]))["suggestions"], [])
        conc = rule_based_insights(facts([task(1, "s1"), task(2, "s1"), task(3, "s1"), task(4, "s2")]))["suggestions"]
        self.assertEqual(conc[0]["area"], "workload")
        self.assertIn("Most of your open work is in Programming", conc[0]["text"])
        self.assertEqual(rule_based_insights(facts([task(1, due=10)]))["suggestions"], [])

    def test_workload_text_says_when_no_estimate_exists(self):
        text = rule_based_insights(facts([task(1), task(2, subtasks=[(25, "not_started"), (35, "completed")])]))["insights"][1]["text"]
        self.assertIn("about 25 minutes", text)
        self.assertIn("1 open task has no subtasks, so no time estimate is available", text)

    def test_unreadable_deadlines_are_mentioned_not_hidden(self):
        text = rule_based_insights(facts([task(1, due="oops"), task(2, due=3)]))["insights"][2]["text"]
        self.assertIn("1 open task could not be included because its deadline is missing or unreadable", text)


class RealStoreDataTests(ApiTestCase):
    """The engine fed with what the real routes and store produce (fake Firestore, no network)."""

    def facts_for(self, user="alice"):
        return build_facts(store.list_task_docs(self.db, user), store.list_subjects(self.db, user), TODAY)

    def test_real_shapes_one_student_only_reopen_and_no_writes(self):
        prog = self.add_subject("alice", "Programming")["subject_id"]
        db_s = self.add_subject("alice", "Databases")["subject_id"]
        a = self.add_task(title="A", subject_id=prog, deadline="2026-11-17")["task_id"]
        b = self.add_task(title="B", subject_id=db_s, deadline="2026-11-30")["task_id"]
        c = self.add_task(title="C", subject_id=prog, deadline="2026-11-10")["task_id"]
        self.call("POST", f"/api/tasks/{b}/subtasks", json={"subtasks": [{"title": "one", "estimated_minutes": 40}, {"title": "two", "estimated_minutes": 20}]})
        self.assertEqual(self.call("POST", f"/api/tasks/{a}/complete").status_code, 200)
        self.assertEqual(self.call("POST", f"/api/tasks/{c}/complete").status_code, 200)
        self.assertEqual(self.call("POST", f"/api/tasks/{c}/reopen").status_code, 200)  # reopened: no longer history
        bob_subject = self.add_subject("bob", "Bob's subject")["subject_id"]
        self.add_task("bob", title="Bob", subject_id=bob_subject, deadline="2026-11-12")
        writes_before = list(self.db.writes)

        f = self.facts_for()
        self.assertEqual(self.db.writes, writes_before)  # reading and calculating wrote nothing
        self.assertEqual((f["completion"]["totalTasks"], f["completion"]["completed"], f["completion"]["open"]), (3, 1, 2))
        self.assertEqual(f["patterns"]["completedTotal"], 1)  # only A; the reopened C leaves no trace
        self.assertEqual({r["name"] for r in f["workload"]["subjects"]}, {"Programming", "Databases"})  # not Bob's subject
        self.assertEqual(f["deadlines"]["overdue"], 1)  # C (reopened, deadline passed)
        self.assertEqual(f["workload"]["remainingMinutesTotal"], 60)
        self.assertEqual(f["workload"]["unestimatedTasksTotal"], 1)
        self.assertNotIn("Bob", json.dumps(f))
        api_progress = self.call("GET", "/api/progress").get_json()
        self.assertEqual((f["completion"]["completionRate"], f["deadlines"]["overdue"], f["completion"]["weeklyCompletion"]),
                         (api_progress["completionRate"], api_progress["overdue"], api_progress["weeklyCompletion"]))
        rule_based_insights(f)

    def test_a_student_with_no_data_gets_the_empty_facts(self):
        self.assertEqual(self.facts_for("nobody")["completion"]["totalTasks"], 0)


if __name__ == "__main__":
    unittest.main()
