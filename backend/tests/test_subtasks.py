"""Subtasks: embedded in the parent task. The server alone decides the parent's progress and status."""
import copy
import pathlib
import sys
import threading
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from base import TASK_FIELDS, TODAY, ApiTestCase  # noqa: E402

STEPS = ["Research the topic", "Write the program", "Test and debug"]
SUBTASK_FIELDS = {"subtask_id", "title", "estimated_minutes", "status"}


class SubtaskCase(ApiTestCase):
    def add_subtasks(self, task_id, titles=STEPS, user="alice", **extra):
        body = {"subtasks": [{"title": t, "estimated_minutes": 30} for t in titles], **extra}
        return self.call("POST", f"/api/tasks/{task_id}/subtasks", user, json=body)

    def parent_with(self, titles=STEPS, **task_over):
        task = self.add_task(**task_over)
        r = self.add_subtasks(task["task_id"], titles)
        self.assertEqual(r.status_code, 201, r.get_json())
        return r.get_json()

    def sub(self, task_id, action, subtask_id, user="alice"):
        path = f"/api/tasks/{task_id}/subtasks/{subtask_id}" + ("" if action == "delete" else f"/{action}")
        return self.call("DELETE" if action == "delete" else "POST", path, user)

    def ids(self, parent):
        return [s["subtask_id"] for s in parent["subtasks"]]


class AddTests(SubtaskCase):
    def test_batch_is_attached_to_the_parent_with_the_exact_shape(self):
        parent = self.parent_with()
        self.assertEqual(set(parent), TASK_FIELDS)
        self.assertEqual([s["title"] for s in parent["subtasks"]], STEPS)
        for s in parent["subtasks"]:
            self.assertEqual(set(s), SUBTASK_FIELDS)
            self.assertEqual((s["status"], s["estimated_minutes"]), ("not_started", 30))
        self.assertEqual(len(set(self.ids(parent))), 3)
        self.assertEqual((parent["progress_pct"], parent["status"]), (0, "not_started"))

    def test_subtasks_are_not_separate_tasks(self):
        parent = self.parent_with()
        tasks = self.call("GET", "/api/tasks").get_json()
        self.assertEqual([t["task_id"] for t in tasks], [parent["task_id"]])
        self.assertEqual(len(tasks[0]["subtasks"]), 3)
        self.assertEqual({k[0] for k in self.db.store}, {"students", "subjects", "tasks"})

    def test_estimated_minutes_defaults_and_unknown_fields_are_ignored(self):
        task = self.add_task()
        r = self.call("POST", f"/api/tasks/{task['task_id']}/subtasks",
                      json={"subtasks": [{"title": "A", "dueDate": "2026-11-18", "due_date": "2026-11-18", "x": 1}]})
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.get_json()["subtasks"][0]["estimated_minutes"], 30)
        stored = self.task_doc(task["task_id"])["subtasks"][0]
        self.assertEqual(set(stored), SUBTASK_FIELDS)

    def test_new_subtasks_are_appended_and_never_replace_existing_ones(self):
        parent = self.parent_with()
        first_ids = self.ids(parent)
        self.sub(parent["task_id"], "complete", first_ids[0])
        again = self.add_subtasks(parent["task_id"], ["Four", "Five"]).get_json()
        self.assertEqual(self.ids(again)[:3], first_ids)
        self.assertEqual([s["title"] for s in again["subtasks"]], STEPS + ["Four", "Five"])
        self.assertEqual(again["subtasks"][0]["status"], "completed")  # existing progress kept
        self.assertEqual(again["progress_pct"], 20)  # 1 of 5

    def test_whole_batch_is_checked_before_anything_is_saved(self):
        task = self.add_task()
        before = copy.deepcopy(self.db.store)
        writes = len(self.db.writes)
        bad = {"subtasks": [{"title": "Fine"}, {"title": "  "}, {"title": "x" * 121},
                            {"title": "ok", "estimated_minutes": 0}, "nope",
                            {"title": "ok", "status": "completed", "subtask_id": "mine"}]}
        r = self.call("POST", f"/api/tasks/{task['task_id']}/subtasks", json=bad)
        self.assertEqual(r.status_code, 422)
        errors = r.get_json()["errors"]
        self.assertEqual(set(errors), {"subtasks[1].title", "subtasks[2].title", "subtasks[3].estimated_minutes",
                                       "subtasks[4]", "subtasks[5].status", "subtasks[5].subtask_id"})
        self.assertEqual(self.db.store, before)
        self.assertEqual(len(self.db.writes), writes)

    def test_bad_batch_shapes_and_minutes_are_422(self):
        task = self.add_task()
        tid = task["task_id"]
        for body in ({}, {"subtasks": []}, {"subtasks": "x"}, {"subtasks": {"title": "a"}}, {"subtasks": [{}]}):
            self.assertEqual(self.call("POST", f"/api/tasks/{tid}/subtasks", json=body).status_code, 422, body)
        for minutes in (0, -5, 1.5, "30", True, None, 9007199254740992):
            r = self.call("POST", f"/api/tasks/{tid}/subtasks", json={"subtasks": [{"title": "a", "estimated_minutes": minutes}]})
            self.assertEqual(r.status_code, 422, minutes)
        self.assertEqual(self.call("POST", f"/api/tasks/{tid}/subtasks", data="not json",
                                   headers={"Content-Type": "application/json"}).status_code, 400)
        self.assertEqual(self.get_task(tid)["subtasks"], [])

    def test_limit_of_twenty_counts_existing_subtasks_and_saves_nothing_when_exceeded(self):
        parent = self.parent_with(titles=[f"S{i}" for i in range(18)])
        before = copy.deepcopy(self.db.store)
        r = self.add_subtasks(parent["task_id"], ["a", "b", "c"])
        self.assertEqual(r.status_code, 422)
        self.assertIn("subtasks", r.get_json()["errors"])
        self.assertEqual(self.db.store, before)
        self.assertEqual(self.add_subtasks(parent["task_id"], ["a", "b"]).status_code, 201)
        self.assertEqual(self.add_subtasks(parent["task_id"], [f"T{i}" for i in range(21)]).status_code, 422)


class ProgressAndStatusTests(SubtaskCase):
    def test_progress_table_for_three_subtasks_and_auto_completion(self):
        parent = self.parent_with()
        tid, ids = parent["task_id"], self.ids(parent)
        seen = []
        for sid in ids:
            body = self.sub(tid, "complete", sid).get_json()
            seen.append((body["progress_pct"], body["status"]))
        self.assertEqual(seen, [(33, "in_progress"), (67, "in_progress"), (100, "completed")])
        self.assertEqual(self.task_doc(tid)["completed_on"], TODAY.isoformat())

    def test_reopening_a_subtask_reopens_the_parent_and_clears_completed_on(self):
        parent = self.parent_with()
        tid, ids = parent["task_id"], self.ids(parent)
        for sid in ids:
            self.sub(tid, "complete", sid)
        body = self.sub(tid, "reopen", ids[2]).get_json()
        self.assertEqual((body["progress_pct"], body["status"]), (67, "in_progress"))
        self.assertNotIn("completed_on", self.task_doc(tid))
        self.assertEqual(self.call("GET", "/api/progress").get_json()["completed"], 0)
        self.sub(tid, "reopen", ids[0])
        self.sub(tid, "reopen", ids[1])
        body = self.get_task(tid)
        self.assertEqual((body["progress_pct"], body["status"]), (0, "in_progress"))  # not back to not_started

    def test_progress_statistics_use_the_auto_completed_parent_once(self):
        parent = self.parent_with()
        for sid in self.ids(parent):
            self.sub(parent["task_id"], "complete", sid)
        stats = self.call("GET", "/api/progress").get_json()
        self.assertEqual((stats["completed"], stats["completionRate"], stats["onTimeRate"]), (1, 100, 100))
        self.assertEqual(sum(stats["weeklyProductivity"]), 1)
        self.assertEqual(stats["weeklyProductivity"][0], 1)  # TODAY is a Monday

    def test_completing_twice_and_reopening_a_not_completed_subtask(self):
        parent = self.parent_with()
        tid, sid = parent["task_id"], self.ids(parent)[0]
        first = self.sub(tid, "complete", sid).get_json()
        self.assertEqual(self.sub(tid, "complete", sid).get_json(), first)
        self.assertEqual(self.sub(tid, "reopen", self.ids(parent)[1]).status_code, 409)
        self.assertEqual(self.get_task(tid)["progress_pct"], 33)

    def test_rounding_is_half_up_with_whole_numbers(self):
        for count, done, expected in ((6, 1, 17), (6, 5, 83), (8, 1, 13), (8, 3, 38), (7, 3, 43), (20, 19, 95)):
            parent = self.parent_with(titles=[f"S{i}" for i in range(count)])
            body = parent
            for sid in self.ids(parent)[:done]:
                body = self.sub(parent["task_id"], "complete", sid).get_json()
            self.assertEqual(body["progress_pct"], expected, (count, done))
            self.assertEqual(body["status"], "in_progress")

    def test_start_is_still_allowed_and_a_started_parent_stays_started_at_zero(self):
        parent = self.parent_with()
        tid, ids = parent["task_id"], self.ids(parent)
        self.assertEqual(self.call("POST", f"/api/tasks/{tid}/start").get_json()["status"], "in_progress")
        self.sub(tid, "complete", ids[0])
        self.sub(tid, "reopen", ids[0])
        self.assertEqual(self.get_task(tid)["status"], "in_progress")

    def test_parent_done_and_reopen_are_refused_while_subtasks_exist(self):
        parent = self.parent_with()
        tid = parent["task_id"]
        before = copy.deepcopy(self.db.store)
        for action in ("complete", "reopen"):
            self.assertEqual(self.call("POST", f"/api/tasks/{tid}/{action}").status_code, 409, action)
        self.assertEqual(self.db.store, before)
        for sid in self.ids(parent):
            self.sub(tid, "complete", sid)
        before = copy.deepcopy(self.db.store)
        for action in ("complete", "reopen"):
            self.assertEqual(self.call("POST", f"/api/tasks/{tid}/{action}").status_code, 409, action)
        self.assertEqual(self.db.store, before)

    def test_manual_progress_is_refused_with_subtasks_but_other_edits_work(self):
        parent = self.parent_with()
        tid = parent["task_id"]
        r = self.call("PATCH", f"/api/tasks/{tid}", json={"progress_pct": 50})
        self.assertEqual(r.status_code, 422)
        self.assertIn("progress_pct", r.get_json()["errors"])
        r = self.call("PATCH", f"/api/tasks/{tid}", json={"title": "Renamed", "subtasks": [], "status": None})
        self.assertEqual(r.status_code, 422)  # status is still forbidden
        r = self.call("PATCH", f"/api/tasks/{tid}", json={"title": "Renamed", "subtasks": []})
        self.assertEqual((r.status_code, r.get_json()["title"], len(r.get_json()["subtasks"])), (200, "Renamed", 3))

    def test_tasks_without_subtasks_keep_the_manual_rules(self):
        task = self.add_task()
        tid = task["task_id"]
        self.assertEqual(self.call("PATCH", f"/api/tasks/{tid}", json={"progress_pct": 40}).get_json()["status"], "not_started")
        done = self.call("POST", f"/api/tasks/{tid}/complete").get_json()
        self.assertEqual((done["status"], done["progress_pct"]), ("completed", 100))
        again = self.call("POST", f"/api/tasks/{tid}/reopen").get_json()
        self.assertEqual((again["status"], again["progress_pct"]), ("in_progress", 100))
        self.assertEqual(again["subtasks"], [])

    def test_adding_subtasks_to_a_completed_task_reopens_it(self):
        task = self.add_task()
        self.call("POST", f"/api/tasks/{task['task_id']}/complete")
        body = self.add_subtasks(task["task_id"], ["One", "Two"]).get_json()
        self.assertEqual((body["status"], body["progress_pct"]), ("in_progress", 0))
        self.assertNotIn("completed_on", self.task_doc(task["task_id"]))

    def test_adding_subtasks_replaces_manual_progress_with_the_calculated_value(self):
        task = self.add_task()
        self.call("PATCH", f"/api/tasks/{task['task_id']}", json={"progress_pct": 65})
        body = self.add_subtasks(task["task_id"], ["One", "Two"]).get_json()
        self.assertEqual(body["progress_pct"], 0)


class DeleteTests(SubtaskCase):
    def test_deleting_a_subtask_recalculates_the_parent(self):
        parent = self.parent_with()
        tid, ids = parent["task_id"], self.ids(parent)
        self.sub(tid, "complete", ids[0])
        body = self.sub(tid, "delete", ids[1]).get_json()
        self.assertEqual((len(body["subtasks"]), body["progress_pct"], body["status"]), (2, 50, "in_progress"))
        body = self.sub(tid, "delete", ids[2]).get_json()  # the only remaining one is done
        self.assertEqual((body["progress_pct"], body["status"]), (100, "completed"))
        self.assertEqual(self.task_doc(tid)["completed_on"], TODAY.isoformat())

    def test_deleting_the_last_subtask_hands_control_back_to_the_manual_rules(self):
        parent = self.parent_with(titles=["Only"])
        tid, sid = parent["task_id"], self.ids(parent)[0]
        body = self.sub(tid, "delete", sid).get_json()
        self.assertEqual((body["subtasks"], body["progress_pct"], body["status"]), ([], 0, "not_started"))
        self.assertEqual(self.call("POST", f"/api/tasks/{tid}/complete").get_json()["status"], "completed")
        self.assertEqual(self.call("PATCH", f"/api/tasks/{tid}", json={"progress_pct": 100}).status_code, 200)

    def test_deleting_the_parent_removes_every_embedded_subtask(self):
        parent = self.parent_with()
        other = self.parent_with(title="Other task")
        self.assertEqual(self.call("DELETE", f"/api/tasks/{parent['task_id']}").status_code, 204)
        self.assertNotIn(("tasks", parent["task_id"]), self.db.store)
        remaining = self.call("GET", "/api/tasks").get_json()
        self.assertEqual([t["task_id"] for t in remaining], [other["task_id"]])
        self.assertEqual(len(remaining[0]["subtasks"]), 3)
        self.assertEqual({k[0] for k in self.db.store}, {"students", "subjects", "tasks"})
        self.assertEqual(self.sub(parent["task_id"], "delete", self.ids(parent)[0]).status_code, 404)

    def test_subject_delete_check_is_unchanged(self):
        subject = self.add_subject("alice", "Biology")
        parent = self.parent_with(subject_id=subject["subject_id"])
        self.assertEqual(self.call("DELETE", f"/api/subjects/{subject['subject_id']}").status_code, 409)
        self.call("DELETE", f"/api/tasks/{parent['task_id']}")
        self.assertEqual(self.call("DELETE", f"/api/subjects/{subject['subject_id']}").status_code, 204)


class OwnershipAndCompatibilityTests(SubtaskCase):
    def test_bob_cannot_reach_alices_subtasks_and_nothing_changes(self):
        parent = self.parent_with()
        tid, sid = parent["task_id"], self.ids(parent)[0]
        before = copy.deepcopy(self.db.store)
        self.assertEqual(self.add_subtasks(tid, ["x"], user="bob").status_code, 404)
        for action in ("complete", "reopen", "delete"):
            self.assertEqual(self.sub(tid, action, sid, user="bob").status_code, 404, action)
        self.assertEqual(self.db.store, before)

    def test_missing_task_and_missing_or_malformed_subtask_are_404(self):
        parent = self.parent_with()
        tid = parent["task_id"]
        self.assertEqual(self.add_subtasks("nope", ["x"]).status_code, 404)
        for sid in ("nope", "a b", "x" * 200):
            for action in ("complete", "reopen", "delete"):
                self.assertEqual(self.sub(tid, action, sid).status_code, 404, (action, sid))
        self.assertEqual(self.sub("nope", "complete", self.ids(parent)[0]).status_code, 404)

    def test_a_subtask_id_from_another_task_is_not_found(self):
        first, second = self.parent_with(), self.parent_with(title="Second")
        self.assertEqual(self.sub(second["task_id"], "complete", self.ids(first)[0]).status_code, 404)

    def test_old_documents_without_a_subtasks_field_still_work(self):
        task = self.add_task()
        doc = self.task_doc(task["task_id"])
        self.assertNotIn("subtasks", doc)  # creating a task does not add the field
        self.assertEqual(self.get_task(task["task_id"])["subtasks"], [])
        self.assertEqual(self.call("POST", f"/api/tasks/{task['task_id']}/start").status_code, 200)
        self.assertEqual(self.call("POST", f"/api/tasks/{task['task_id']}/complete").status_code, 200)
        self.assertEqual(self.add_subtasks(task["task_id"], ["late"]).status_code, 201)

    def test_malformed_subtasks_field_is_rejected_without_modifying_the_task(self):
        malformed_values = (
            "garbage",
            {"not": "a list"},
            ["not an object"],
            [{"subtask_id": "valid-id", "title": "Missing fields"}],
            [{"subtask_id": "valid-id", "title": "Bad status", "estimated_minutes": 30,
              "status": "in_progress"}],
        )
        for malformed in malformed_values:
            with self.subTest(malformed=malformed):
                task = self.add_task()
                stored = self.task_doc(task["task_id"])
                stored["subtasks"] = copy.deepcopy(malformed)
                before = copy.deepcopy(stored)

                response = self.call("GET", "/api/tasks")
                self.assertEqual(response.status_code, 422)
                self.assertIn("subtasks", response.get_json()["errors"])

                response = self.call("POST", f"/api/tasks/{task['task_id']}/complete")
                self.assertEqual(response.status_code, 422)
                self.assertEqual(self.task_doc(task["task_id"]), before)

    def test_malformed_subtask_array_is_not_partially_filtered(self):
        task = self.add_task()
        valid = {"subtask_id": "valid-id", "title": "Keep me", "estimated_minutes": 30,
                 "status": "not_started"}
        self.task_doc(task["task_id"])["subtasks"] = [valid, "damaged item"]
        before = copy.deepcopy(self.task_doc(task["task_id"]))
        response = self.add_subtasks(task["task_id"], ["Another"])
        self.assertEqual(response.status_code, 422)
        self.assertEqual(self.task_doc(task["task_id"]), before)

    def test_client_cannot_inject_subtasks_when_creating_a_task(self):
        task = self.add_task(subtasks=[{"title": "sneaky", "status": "completed"}])
        self.assertEqual(task["subtasks"], [])
        self.assertNotIn("subtasks", self.task_doc(task["task_id"]))


MAX_SAFE = 9007199254740991


class MinutesTests(SubtaskCase):
    def test_large_minutes_and_the_default_are_saved_returned_and_read_back(self):
        task = self.add_task()
        tid = task["task_id"]
        body = {"subtasks": [{"title": f"m{m}", "estimated_minutes": m} for m in (1441, 2160, 100000, MAX_SAFE)]
                + [{"title": "default"}]}
        r = self.call("POST", f"/api/tasks/{tid}/subtasks", json=body)
        self.assertEqual(r.status_code, 201, r.get_json())
        expected = [1441, 2160, 100000, MAX_SAFE, 30]
        self.assertEqual([s["estimated_minutes"] for s in r.get_json()["subtasks"]], expected)
        self.assertEqual([s["estimated_minutes"] for s in self.get_task(tid)["subtasks"]], expected)
        self.assertEqual([s["estimated_minutes"] for s in self.task_doc(tid)["subtasks"]], expected)

    def test_only_the_safe_integer_limit_caps_minutes_and_it_is_422(self):
        tid = self.add_task()["task_id"]
        before = copy.deepcopy(self.db.store)
        for minutes in (MAX_SAFE + 1, 10 ** 30):
            r = self.call("POST", f"/api/tasks/{tid}/subtasks", json={"subtasks": [{"title": "x", "estimated_minutes": minutes}]})
            self.assertEqual(r.status_code, 422, minutes)
            self.assertIn("subtasks[0].estimated_minutes", r.get_json()["errors"])
        self.assertEqual(self.db.store, before)


class RaceCase(SubtaskCase):
    """Deterministic races: `race(fn)` runs `fn` once, right after the first transactional read of a task, so the
    operation under test always loses the race exactly once and has to retry on fresh data."""

    def race(self, competing):
        state = {"fired": False}

        def hook(path):
            if not state["fired"] and path[0] == "tasks":
                state["fired"] = True
                competing()
        self.db.after_txn_read = hook
        return state

    def ok(self, response, code=200):
        self.assertEqual(response.status_code, code, response.get_json())
        return response.get_json()


class ConcurrencyTests(RaceCase):
    def test_two_different_subtasks_completed_at_once_are_both_saved(self):
        parent = self.parent_with()
        tid, ids = parent["task_id"], self.ids(parent)
        state = self.race(lambda: self.ok(self.sub(tid, "complete", ids[1])))
        result = self.ok(self.sub(tid, "complete", ids[0]))
        self.assertTrue(state["fired"])
        self.assertEqual((result["progress_pct"], result["status"]), (67, "in_progress"))
        stored = self.get_task(tid)
        self.assertEqual([s["status"] for s in stored["subtasks"]], ["completed", "completed", "not_started"])
        self.assertEqual((stored["progress_pct"], stored["status"]), (67, "in_progress"))

    def test_two_add_batches_at_once_give_four_subtasks(self):
        tid = self.add_task()["task_id"]
        self.race(lambda: self.ok(self.add_subtasks(tid, ["C", "D"]), 201))
        self.ok(self.add_subtasks(tid, ["A", "B"]), 201)
        titles = [s["title"] for s in self.get_task(tid)["subtasks"]]
        self.assertEqual(sorted(titles), ["A", "B", "C", "D"])
        self.assertEqual(len({s["subtask_id"] for s in self.get_task(tid)["subtasks"]}), 4)

    def test_title_edit_during_a_subtask_completion_keeps_both(self):
        parent = self.parent_with()
        tid, ids = parent["task_id"], self.ids(parent)
        self.race(lambda: self.ok(self.call("PATCH", f"/api/tasks/{tid}", json={"title": "Renamed"})))
        self.ok(self.sub(tid, "complete", ids[0]))
        stored = self.get_task(tid)
        self.assertEqual(stored["title"], "Renamed")
        self.assertEqual(stored["subtasks"][0]["status"], "completed")
        self.assertEqual(stored["progress_pct"], 33)

    def test_parent_deleted_mid_operation_gives_404_and_is_not_recreated(self):
        for action in ("complete", "delete"):
            with self.subTest(action=action):
                parent = self.parent_with(title=f"Doomed {action}")
                tid, sid = parent["task_id"], self.ids(parent)[0]
                self.race(lambda: self.assertEqual(self.call("DELETE", f"/api/tasks/{tid}").status_code, 204))
                self.assertEqual(self.sub(tid, action, sid).status_code, 404)
                self.assertNotIn(("tasks", tid), self.db.store)

    def test_start_task_during_a_subtask_completion(self):
        parent = self.parent_with()
        tid, ids = parent["task_id"], self.ids(parent)
        self.race(lambda: self.ok(self.call("POST", f"/api/tasks/{tid}/start")))
        self.ok(self.sub(tid, "complete", ids[0]))
        stored = self.get_task(tid)
        self.assertEqual((stored["status"], stored["progress_pct"]), ("in_progress", 33))

    def test_complete_task_during_update_task_keeps_both_changes(self):
        tid = self.add_task()["task_id"]
        self.race(lambda: self.ok(self.call("POST", f"/api/tasks/{tid}/complete")))
        self.ok(self.call("PATCH", f"/api/tasks/{tid}", json={"title": "Edited"}))
        stored = self.get_task(tid)
        self.assertEqual((stored["title"], stored["status"], stored["progress_pct"]), ("Edited", "completed", 100))

    def test_complete_task_during_a_progress_edit_makes_the_edit_fail_on_fresh_data(self):
        tid = self.add_task()["task_id"]
        self.race(lambda: self.ok(self.call("POST", f"/api/tasks/{tid}/complete")))
        r = self.call("PATCH", f"/api/tasks/{tid}", json={"progress_pct": 40})
        self.assertEqual(r.status_code, 422, r.get_json())
        stored = self.get_task(tid)
        self.assertEqual((stored["status"], stored["progress_pct"]), ("completed", 100))

    def test_reopen_task_during_update_task_keeps_both_changes(self):
        tid = self.add_task()["task_id"]
        self.ok(self.call("POST", f"/api/tasks/{tid}/complete"))
        self.race(lambda: self.ok(self.call("POST", f"/api/tasks/{tid}/reopen")))
        self.ok(self.call("PATCH", f"/api/tasks/{tid}", json={"title": "Edited"}))
        stored = self.get_task(tid)
        self.assertEqual((stored["title"], stored["status"], stored["progress_pct"]), ("Edited", "in_progress", 100))

    def test_subtask_delete_during_a_subtask_completion(self):
        parent = self.parent_with()
        tid, ids = parent["task_id"], self.ids(parent)
        self.race(lambda: self.ok(self.sub(tid, "delete", ids[1])))
        self.ok(self.sub(tid, "complete", ids[0]))
        stored = self.get_task(tid)
        self.assertEqual([s["subtask_id"] for s in stored["subtasks"]], [ids[0], ids[2]])
        self.assertEqual((stored["progress_pct"], stored["status"]), (50, "in_progress"))

    def test_subtask_completion_during_a_subtask_delete_recalculates_from_fresh_data(self):
        parent = self.parent_with()
        tid, ids = parent["task_id"], self.ids(parent)
        self.race(lambda: self.ok(self.sub(tid, "complete", ids[0])))
        self.ok(self.sub(tid, "delete", ids[2]))
        stored = self.get_task(tid)
        self.assertEqual((stored["progress_pct"], stored["status"]), (50, "in_progress"))

    def test_a_losing_attempt_writes_nothing(self):
        parent = self.parent_with()
        tid, ids = parent["task_id"], self.ids(parent)
        self.race(lambda: self.ok(self.sub(tid, "complete", ids[1])))
        before = len(self.db.writes)
        self.ok(self.sub(tid, "complete", ids[0]))
        self.assertEqual(len(self.db.writes) - before, 1 + 1)  # the competing commit + the retried commit; none from the lost attempt

    def test_two_threads_completing_different_subtasks_both_survive(self):
        parent = self.parent_with()
        tid, ids = parent["task_id"], self.ids(parent)
        barrier, seen, results = threading.Barrier(2, timeout=10), threading.local(), []

        def hook(path):  # both threads read before either commits, once each
            if path[0] == "tasks" and not getattr(seen, "waited", False):
                seen.waited = True
                barrier.wait()
        self.db.after_txn_read = hook

        def worker(subtask_id):
            results.append(self.sub(tid, "complete", subtask_id).status_code)
        threads = [threading.Thread(target=worker, args=(sid,)) for sid in ids[:2]]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=15)
        self.assertFalse(any(t.is_alive() for t in threads))
        self.assertEqual(results, [200, 200])
        stored = self.get_task(tid)
        self.assertEqual((stored["progress_pct"], stored["status"]), (67, "in_progress"))
        self.assertEqual([s["status"] for s in stored["subtasks"]], ["completed", "completed", "not_started"])
        self.assertGreater(self.db.txn_attempts, 2)  # one of them really had to retry


class ConflictExhaustionTests(RaceCase):
    def test_five_failed_attempts_return_409_with_a_retry_message_and_change_nothing(self):
        parent = self.parent_with()
        tid, ids = parent["task_id"], self.ids(parent)
        ref = self.db.collection("tasks").document(tid)

        def always_conflict(path):
            if path[0] == "tasks":
                ref.set(self.db.store[("tasks", tid)])  # a plain write bumps the version every time
        self.db.after_txn_read = always_conflict
        before = copy.deepcopy(self.task_doc(tid))
        attempts = self.db.txn_attempts
        r = self.sub(tid, "complete", ids[0])
        self.assertEqual(r.status_code, 409)
        self.assertIn("try again", r.get_json()["detail"].lower())
        self.assertEqual(self.db.txn_attempts - attempts, 5)
        self.assertEqual(self.task_doc(tid), before)

    def test_an_error_inside_the_transaction_is_not_turned_into_a_conflict(self):
        tid = self.add_task()["task_id"]
        self.assertEqual(self.call("POST", f"/api/tasks/{tid}/reopen").status_code, 409)  # normal 409, one attempt
        self.assertEqual(self.call("PATCH", f"/api/tasks/{tid}", json={"progress_pct": 5000}).status_code, 422)


def _sub(sid, **over):
    return {"subtask_id": sid, "title": "Step " + sid, "estimated_minutes": 30, "status": "not_started", **over}


def _three(*statuses):
    return [_sub(sid, status=(statuses[i] if i < len(statuses) else "not_started")) for i, sid in enumerate("abc")]


# SAME TABLE as PARITY_CASES in frontend/tests/subtasks.test.mjs (same names, same data, same expectation).
PARITY_CASES = [
    ("empty list, not started", [], 0, "not_started", True),
    ("three not started", _three(), 0, "not_started", True),
    ("none done but in progress", _three(), 0, "in_progress", True),
    ("one of three done", _three("completed"), 33, "in_progress", True),
    ("two of three done", _three("completed", "completed"), 67, "in_progress", True),
    ("all done", _three("completed", "completed", "completed"), 100, "completed", True),
    ("minutes = 1440", [_sub("a", estimated_minutes=1440)], 0, "not_started", True),
    ("minutes = 1441 (was rejected before Stage A)", [_sub("a", estimated_minutes=1441)], 0, "not_started", True),
    ("minutes = 100000", [_sub("a", estimated_minutes=100000)], 0, "not_started", True),
    ("minutes = max safe integer", [_sub("a", estimated_minutes=MAX_SAFE)], 0, "not_started", True),
    ("minutes = max safe integer + 1", [_sub("a", estimated_minutes=MAX_SAFE + 1)], 0, "not_started", False),
    ("minutes = 0", [_sub("a", estimated_minutes=0)], 0, "not_started", False),
    ("minutes = -5", [_sub("a", estimated_minutes=-5)], 0, "not_started", False),
    ("minutes = 1.5", [_sub("a", estimated_minutes=1.5)], 0, "not_started", False),
    ("minutes = \"30\"", [_sub("a", estimated_minutes="30")], 0, "not_started", False),
    ("minutes = true", [_sub("a", estimated_minutes=True)], 0, "not_started", False),
    ("extra key", [_sub("a", due="2026-11-20")], 0, "not_started", False),
    ("missing key", [{k: v for k, v in _sub("a").items() if k != "status"}], 0, "not_started", False),
    ("title with surrounding spaces", [_sub("a", title=" padded ")], 0, "not_started", False),
    ("empty title", [_sub("a", title="")], 0, "not_started", False),
    ("title of 121 characters", [_sub("a", title="x" * 121)], 0, "not_started", False),
    ("subtask status in_progress", [_sub("a", status="in_progress")], 0, "not_started", False),
    ("duplicate subtask ids", [_sub("a"), _sub("a")], 0, "not_started", False),
    ("progress does not match subtasks", _three("completed"), 50, "in_progress", False),
    ("all done but parent in progress", _three("completed", "completed", "completed"), 100, "in_progress", False),
    ("parent completed with one open subtask", _three("completed", "completed"), 67, "completed", False),
    ("subtasks is not a list", "garbage", 0, "not_started", False),
    ("21 subtasks", [_sub(f"s{i}") for i in range(21)], 0, "not_started", False),
    ("some done but parent not started", _three("completed"), 33, "not_started", False),
    ("some done but parent not started (two of three)", _three("completed", "completed"), 67, "not_started", False),
    ("none done but parent completed", _three(), 0, "completed", False),
    ("progress is false instead of 0", _three(), False, "not_started", False),
    ("progress is true while none done", _three(), True, "not_started", False),
]


class ParityTests(SubtaskCase):
    def test_parity_table_accepts_and_rejects_stored_data(self):
        for name, subtasks, progress, status, accepted in PARITY_CASES:
            with self.subTest(case=name):
                tid = self.add_task(title=name[:40])["task_id"]
                doc = self.task_doc(tid)
                doc.update({"subtasks": copy.deepcopy(subtasks), "progress_pct": progress, "status": status})
                if status == "completed":
                    doc["completed_on"] = "2026-11-16"
                before = copy.deepcopy(doc)
                listing = self.call("GET", "/api/tasks")
                if accepted:
                    self.assertEqual(listing.status_code, 200, listing.get_json())
                else:
                    self.assertEqual(listing.status_code, 422, name)
                    self.assertIn("subtasks", listing.get_json()["errors"])
                    for path in ("start", "complete", "reopen"):
                        self.assertEqual(self.call("POST", f"/api/tasks/{tid}/{path}").status_code, 422, (name, path))
                    self.assertEqual(self.task_doc(tid), before)
                self.db.store.pop(("tasks", tid))  # keep the listing usable for the next case


class RecalculationInvariantTests(SubtaskCase):
    def test_every_combination_of_one_to_six_subtasks_stays_consistent_after_each_step(self):
        for total in range(1, 7):
            for mask in range(1 << total):
                with self.subTest(total=total, mask=mask):
                    parent = self.parent_with(titles=[f"S{i}" for i in range(total)], title=f"T{total}-{mask}")
                    tid, ids = parent["task_id"], self.ids(parent)
                    for i in range(total):
                        if mask & (1 << i):
                            self.assertEqual(self.sub(tid, "complete", ids[i]).status_code, 200)
                    self.assertEqual(self.call("GET", "/api/tasks").status_code, 200)  # the consistency check passes
                    done = bin(mask).count("1")
                    stored = self.get_task(tid)
                    self.assertEqual(stored["progress_pct"], (done * 100 + total // 2) // total)
                    self.assertEqual(stored["status"] == "completed", done == total)
                    self.db.store.pop(("tasks", tid))

    def test_adding_to_a_completed_parent_and_deleting_until_the_rest_are_done(self):
        parent = self.parent_with(titles=["a", "b"])
        tid, ids = parent["task_id"], self.ids(parent)
        for sid in ids:
            self.sub(tid, "complete", sid)
        self.assertEqual(self.get_task(tid)["status"], "completed")
        added = self.add_subtasks(tid, ["late"]).get_json()
        self.assertEqual((added["status"], added["progress_pct"]), ("in_progress", 67))
        self.assertEqual(self.call("GET", "/api/tasks").status_code, 200)
        late = self.ids(added)[2]
        deleted = self.sub(tid, "delete", late).get_json()
        self.assertEqual((deleted["status"], deleted["progress_pct"]), ("completed", 100))
        self.assertEqual(self.call("GET", "/api/tasks").status_code, 200)


if __name__ == "__main__":
    unittest.main()
