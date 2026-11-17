"""The exact approved status behaviour.

create: not_started / 0     start: in_progress, progress unchanged     update progress: status unchanged
complete: completed / 100   reopen: in_progress, progress unchanged    in_progress at 100% is allowed
"""
import pathlib
import sys
import unittest
from datetime import date

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import dates  # noqa: E402
from base import TASK_FIELDS, TODAY, ApiTestCase  # noqa: E402


class StatusRuleTests(ApiTestCase):
    def act(self, task_id, action, user="alice"):
        return self.call("POST", f"/api/tasks/{task_id}/{action}", user)

    def patch_progress(self, task_id, value):
        return self.call("PATCH", f"/api/tasks/{task_id}", json={"progress_pct": value})

    # ---- create ----
    def test_create_is_not_started_at_zero(self):
        task = self.add_task()
        self.assertEqual((task["status"], task["progress_pct"]), ("not_started", 0))

    # ---- start ----
    def test_start_sets_in_progress_and_keeps_progress(self):
        task_id = self.add_task()["task_id"]
        self.patch_progress(task_id, 40)
        started = self.act(task_id, "start")
        self.assertEqual(started.status_code, 200)
        body = started.get_json()
        self.assertEqual((body["status"], body["progress_pct"]), ("in_progress", 40))
        self.assertEqual(set(body), TASK_FIELDS)

    def test_start_twice_changes_nothing(self):
        task_id = self.add_task()["task_id"]
        self.act(task_id, "start")
        updated_at = self.task_doc(task_id)["updated_at"]
        r = self.act(task_id, "start")
        self.assertEqual((r.status_code, r.get_json()["status"]), (200, "in_progress"))
        self.assertEqual(self.task_doc(task_id)["updated_at"], updated_at)

    def test_start_on_completed_task_is_409(self):
        task_id = self.add_task()["task_id"]
        self.act(task_id, "complete")
        r = self.act(task_id, "start")
        self.assertEqual(r.status_code, 409)
        self.assertIn("reopen", r.get_json()["detail"].lower())
        self.assertEqual(self.get_task(task_id)["status"], "completed")

    # ---- update progress never changes status ----
    def test_progress_update_never_changes_status(self):
        task_id = self.add_task()["task_id"]
        r = self.patch_progress(task_id, 40)
        self.assertEqual((r.get_json()["status"], r.get_json()["progress_pct"]), ("not_started", 40))
        self.act(task_id, "start")
        r = self.patch_progress(task_id, 100)
        self.assertEqual((r.get_json()["status"], r.get_json()["progress_pct"]), ("in_progress", 100))
        r = self.patch_progress(task_id, 0)
        self.assertEqual((r.get_json()["status"], r.get_json()["progress_pct"]), ("in_progress", 0))

    def test_in_progress_at_100_is_allowed_and_has_no_completed_on(self):
        task_id = self.add_task()["task_id"]
        self.act(task_id, "start")
        self.patch_progress(task_id, 100)
        doc = self.task_doc(task_id)
        self.assertEqual((doc["status"], doc["progress_pct"]), ("in_progress", 100))
        self.assertNotIn("completed_on", doc)

    # ---- complete ----
    def test_complete_from_not_started_and_in_progress(self):
        for start_first in (False, True):
            task_id = self.add_task()["task_id"]
            if start_first:
                self.act(task_id, "start")
                self.patch_progress(task_id, 30)
            r = self.act(task_id, "complete")
            body = r.get_json()
            self.assertEqual((r.status_code, body["status"], body["progress_pct"]), (200, "completed", 100))
            self.assertEqual(self.task_doc(task_id)["completed_on"], TODAY.isoformat())
            self.assertEqual(set(body), TASK_FIELDS)

    def test_complete_twice_keeps_the_original_completed_on(self):
        task_id = self.add_task()["task_id"]
        self.act(task_id, "complete")
        self.db.store[("tasks", task_id)]["completed_on"] = "2026-11-10"
        r = self.act(task_id, "complete")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.task_doc(task_id)["completed_on"], "2026-11-10")

    # ---- reopen ----
    def test_reopen_goes_to_in_progress_without_changing_progress(self):
        task_id = self.add_task()["task_id"]
        self.act(task_id, "complete")
        r = self.act(task_id, "reopen")
        body = r.get_json()
        self.assertEqual((r.status_code, body["status"], body["progress_pct"]), (200, "in_progress", 100))  # not 80
        self.assertNotIn("completed_on", self.task_doc(task_id))

    def test_reopen_keeps_whatever_progress_the_task_had(self):
        task_id = self.add_task()["task_id"]
        self.act(task_id, "complete")
        self.db.store[("tasks", task_id)]["progress_pct"] = 100
        self.act(task_id, "reopen")
        self.assertEqual(self.patch_progress(task_id, 60).get_json()["progress_pct"], 60)
        self.assertEqual(self.get_task(task_id)["status"], "in_progress")

    def test_reopen_on_a_task_that_is_not_completed_is_409(self):
        task_id = self.add_task()["task_id"]
        self.assertEqual(self.act(task_id, "reopen").status_code, 409)
        self.act(task_id, "start")
        self.assertEqual(self.act(task_id, "reopen").status_code, 409)
        self.assertEqual(self.get_task(task_id)["status"], "in_progress")

    def test_completing_again_after_reopen_records_the_new_day(self):
        task_id = self.add_task()["task_id"]
        self.act(task_id, "complete")
        self.act(task_id, "reopen")
        later = date(2026, 11, 18)
        dates.today = lambda: later
        self.act(task_id, "complete")
        self.assertEqual(self.task_doc(task_id)["completed_on"], "2026-11-18")

    # ---- completed tasks stay at 100 ----
    def test_completed_task_cannot_be_lowered_without_reopening(self):
        task_id = self.add_task()["task_id"]
        self.act(task_id, "complete")
        r = self.patch_progress(task_id, 50)
        self.assertEqual(r.status_code, 422)
        self.assertIn("Reopen", r.get_json()["errors"]["progress_pct"])
        self.assertEqual(self.patch_progress(task_id, 100).status_code, 200)
        task = self.get_task(task_id)
        self.assertEqual((task["status"], task["progress_pct"]), ("completed", 100))

    # ---- status is not exposed as editable and internals stay private ----
    def test_internal_fields_are_never_exposed(self):
        task_id = self.add_task()["task_id"]
        self.act(task_id, "complete")
        self.assertEqual(set(self.get_task(task_id)), TASK_FIELDS)

    def test_actions_on_unknown_ids_are_404(self):
        for action in ("start", "complete", "reopen"):
            self.assertEqual(self.act("nope", action).status_code, 404, action)
            self.assertEqual(self.act("a.b", action).status_code, 404, action)


if __name__ == "__main__":
    unittest.main()
