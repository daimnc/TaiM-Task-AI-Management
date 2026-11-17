"""Legacy users/{uid}/... data must never be read, written or deleted by the new backend."""
import copy
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from base import ApiTestCase  # noqa: E402

LEGACY = {
    ("users", "alice", "tasks", "legacy1"): {"title": "Old task", "course": "CS", "category": "Assignment",
                                              "deadline": "2026-11-20", "priority": "High", "progress": 100,
                                              "completedOn": "2026-11-15", "createdAt": "2026-11-01T00:00:00+00:00"},
    ("users", "alice", "preferences", "settings"): {"name": "Old Alice", "program": "BS CS", "leadDays": 3,
                                                    "sessionMinutes": 25, "weeklySummary": True},
    ("users", "alice", "preferences", "reminders"): {"deadline": False, "dailySummary": True,
                                                     "progressCheckin": True, "quietHours": False},
    ("users", "carol", "tasks", "legacy2"): {"title": "Carol's old task", "progress": 10},
}


class LegacyUntouchedTests(ApiTestCase):
    def test_a_full_session_never_reads_writes_or_deletes_legacy_data(self):
        self.db.store.update(copy.deepcopy(LEGACY))
        before = copy.deepcopy(LEGACY)
        self.db.forbidden.append(("users",))  # any read of users/... now raises AssertionError

        subject = self.add_subject("alice", "Fresh subject")
        extra = self.add_subject("alice", "Second subject")
        task = self.add_task("alice", subject_id=subject["subject_id"])
        tid = task["task_id"]
        self.call("PATCH", f"/api/tasks/{tid}", json={"title": "Edited", "subject_id": extra["subject_id"]})
        self.call("POST", f"/api/tasks/{tid}/start")
        self.call("PATCH", f"/api/tasks/{tid}", json={"progress_pct": 70})
        self.call("POST", f"/api/tasks/{tid}/complete")
        self.call("POST", f"/api/tasks/{tid}/reopen")
        self.call("GET", "/api/tasks")
        self.call("GET", "/api/subjects")
        self.call("GET", "/api/progress")
        self.call("POST", "/api/ai/chat", json={"message": "what first?"})
        self.call("PUT", "/api/settings", json={"full_name": "Ana", "leadDays": 5})
        self.call("GET", "/api/settings")
        self.call("PUT", "/api/reminders/preferences", json={"deadline": True})
        self.call("GET", "/api/reminders/preferences")
        self.call("PATCH", f"/api/subjects/{extra['subject_id']}", json={"subject_name": "Renamed"})
        self.call("DELETE", f"/api/tasks/{tid}")
        self.call("DELETE", f"/api/subjects/{subject['subject_id']}")

        self.assertEqual({k: v for k, v in self.db.store.items() if k[0] == "users"}, before)
        self.assertFalse([w for w in self.db.writes if w[1][0] == "users"])
        self.assertTrue(self.db.writes)  # the session really did write (to the new collections)

    def test_legacy_tasks_are_not_visible_through_the_new_api(self):
        self.db.store.update(copy.deepcopy(LEGACY))
        self.assertEqual(self.call("GET", "/api/tasks", "alice").get_json(), [])
        self.assertEqual(self.call("GET", "/api/settings", "alice").get_json()["full_name"], "Alice")


if __name__ == "__main__":
    unittest.main()
