"""Progress statistics are calculated from task STATUS (and completed_on), never from the progress number."""
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from base import ApiTestCase  # noqa: E402

KEYS = {"completionRate", "onTimeRate", "completed", "overdue", "weeklyChange", "weeklyProductivity",
        "weeklyCompletion", "insight", "insightSource"}


class ProgressTests(ApiTestCase):
    def progress(self, user="alice"):
        return self.call("GET", "/api/progress", user).get_json()

    def complete(self, task_id, user="alice"):
        self.assertEqual(self.call("POST", f"/api/tasks/{task_id}/complete", user).status_code, 200)

    def test_no_tasks_gives_zero_defaults_in_the_expected_shape(self):
        p = self.progress()
        self.assertEqual(set(p), KEYS)
        self.assertEqual((p["completionRate"], p["onTimeRate"], p["completed"], p["overdue"], p["weeklyChange"]),
                         (0, 0, 0, 0, 0))
        self.assertEqual(p["weeklyProductivity"], [0] * 7)
        self.assertEqual(p["weeklyCompletion"], [0] * 4)
        self.assertEqual(p["insightSource"], "rule-based")

    def test_statistics_come_from_stored_tasks_and_status(self):
        self.complete(self.add_task(title="Done on time", deadline="2026-11-20")["task_id"])  # completed today (Mon)
        overdue = self.add_task(title="Overdue", deadline="2026-11-10")["task_id"]
        self.call("PATCH", f"/api/tasks/{overdue}", json={"progress_pct": 40})
        self.add_task(title="Future", deadline="2026-11-30")
        other = self.add_task("bob", title="Not mine")["task_id"]
        self.complete(other, "bob")
        p = self.progress()
        self.assertEqual((p["completed"], p["overdue"], p["completionRate"], p["onTimeRate"]), (1, 1, 33, 100))
        self.assertEqual(p["weeklyProductivity"], [1, 0, 0, 0, 0, 0, 0])
        self.assertEqual(p["weeklyCompletion"], [0, 0, 0, 1])
        self.assertEqual(p["weeklyChange"], 0)
        self.assertIn("1 overdue", p["insight"])
        self.assertIn("assignment", p["insight"])
        self.assertIn("not AI-generated", p["insight"])

    def test_100_percent_without_completing_is_still_open(self):
        task_id = self.add_task(deadline="2026-11-10")["task_id"]
        self.call("POST", f"/api/tasks/{task_id}/start")
        self.call("PATCH", f"/api/tasks/{task_id}", json={"progress_pct": 100})
        p = self.progress()
        self.assertEqual((p["completed"], p["completionRate"], p["overdue"]), (0, 0, 1))
        self.assertEqual(p["weeklyCompletion"], [0, 0, 0, 0])

    def test_late_completion_lowers_on_time_rate(self):
        self.complete(self.add_task(deadline="2026-11-10")["task_id"])
        p = self.progress()
        self.assertEqual((p["completed"], p["onTimeRate"], p["overdue"]), (1, 0, 0))

    def test_reopening_removes_a_task_from_completed_statistics(self):
        task_id = self.add_task()["task_id"]
        self.complete(task_id)
        self.call("POST", f"/api/tasks/{task_id}/reopen")
        p = self.progress()
        self.assertEqual((p["completed"], p["weeklyCompletion"], p["completionRate"]), (0, [0, 0, 0, 0], 0))

    def test_completed_task_without_a_recorded_day_counts_but_is_skipped_by_date_figures(self):
        task_id = self.add_task()["task_id"]
        self.complete(task_id)
        del self.db.store[("tasks", task_id)]["completed_on"]
        p = self.progress()
        self.assertEqual((p["completed"], p["onTimeRate"], p["weeklyCompletion"]), (1, 0, [0, 0, 0, 0]))

    def test_weekly_change_compares_the_last_two_weeks(self):
        for day in ("2026-11-09", "2026-11-10"):  # last week: 2 completions
            self.complete(self.add_task()["task_id"])
        for task in self.db.store.values():
            if task.get("status") == "completed":
                task["completed_on"] = "2026-11-10"
        self.complete(self.add_task()["task_id"])  # this week: 1
        p = self.progress()
        self.assertEqual(p["weeklyCompletion"], [0, 0, 2, 1])
        self.assertEqual(p["weeklyChange"], -50)


if __name__ == "__main__":
    unittest.main()
