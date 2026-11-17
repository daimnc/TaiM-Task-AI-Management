"""Ownership: a student can only reach their own students/subjects/tasks. Foreign and missing look identical (404),
nothing is mutated, and no client-supplied identity is trusted."""
import copy
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from base import TASK, ApiTestCase  # noqa: E402


class OwnershipMatrixTests(ApiTestCase):
    def setUp(self):
        super().setUp()
        self.subject = self.add_subject("alice", "Alice's subject")
        self.task = self.add_task("alice", subject_id=self.subject["subject_id"])
        self.tid, self.sid = self.task["task_id"], self.subject["subject_id"]
        self.snapshot = copy.deepcopy(self.db.store)

    def assertNothingChanged(self):
        self.assertEqual(self.db.store, self.snapshot)

    def test_bob_cannot_touch_alices_task_through_any_route(self):
        calls = [
            ("PATCH", f"/api/tasks/{self.tid}", {"title": "Pwned"}),
            ("PATCH", f"/api/tasks/{self.tid}", {"progress_pct": 99}),
            ("DELETE", f"/api/tasks/{self.tid}", None),
            ("POST", f"/api/tasks/{self.tid}/start", None),
            ("POST", f"/api/tasks/{self.tid}/complete", None),
            ("POST", f"/api/tasks/{self.tid}/reopen", None),
        ]
        for method, path, body in calls:
            r = self.call(method, path, "bob", json=body)
            self.assertEqual(r.status_code, 404, (method, path))
        self.assertNothingChanged()

    def test_reopen_on_a_foreign_completed_task_is_404_not_409(self):
        self.call("POST", f"/api/tasks/{self.tid}/complete")
        self.snapshot = copy.deepcopy(self.db.store)
        self.assertEqual(self.call("POST", f"/api/tasks/{self.tid}/reopen", "bob").status_code, 404)
        self.assertEqual(self.call("POST", f"/api/tasks/{self.tid}/start", "bob").status_code, 404)  # not 409
        self.assertNothingChanged()

    def test_bob_cannot_touch_alices_subject(self):
        self.assertEqual(self.call("PATCH", f"/api/subjects/{self.sid}", "bob", json={"subject_name": "Pwned"}).status_code, 404)
        self.assertEqual(self.call("DELETE", f"/api/subjects/{self.sid}", "bob").status_code, 404)
        self.assertNothingChanged()

    def test_foreign_and_missing_look_identical(self):
        for method, path, body in (("PATCH", "/api/tasks/{}", {"title": "x"}), ("DELETE", "/api/tasks/{}", None),
                                   ("POST", "/api/tasks/{}/complete", None), ("PATCH", "/api/subjects/{}", {"subject_name": "x"}),
                                   ("DELETE", "/api/subjects/{}", None)):
            real = self.tid if "tasks" in path else self.sid
            foreign = self.call(method, path.format(real), "bob", json=body)
            missing = self.call(method, path.format("does-not-exist"), "bob", json=body)
            self.assertEqual((foreign.status_code, foreign.get_json()), (missing.status_code, missing.get_json()), path)

    def test_lists_are_isolated(self):
        self.assertEqual(self.call("GET", "/api/tasks", "bob").get_json(), [])
        self.assertEqual(self.call("GET", "/api/subjects", "bob").get_json(), [])
        self.assertEqual(self.call("GET", "/api/progress", "bob").get_json()["completionRate"], 0)

    def test_task_cannot_reference_another_students_subject(self):
        r = self.call("POST", "/api/tasks", "bob", json={**TASK, "subject_id": self.sid})
        self.assertEqual(r.status_code, 422)
        bobs_task = self.add_task("bob")
        r = self.call("PATCH", f"/api/tasks/{bobs_task['task_id']}", "bob", json={"subject_id": self.sid})
        self.assertEqual(r.status_code, 422)
        self.assertNotEqual(self.task_doc(bobs_task["task_id"])["subject_id"], self.sid)

    def test_alices_data_survives_bobs_attempts_and_is_still_hers(self):
        self.call("DELETE", f"/api/tasks/{self.tid}", "bob")
        self.call("DELETE", f"/api/subjects/{self.sid}", "bob")
        self.assertEqual(self.get_task(self.tid)["title"], TASK["title"])
        self.assertEqual(self.call("GET", "/api/subjects").get_json(), [self.subject])

    def test_client_supplied_identity_is_never_trusted(self):
        r = self.call("GET", "/api/tasks?uid=alice&student_id=alice&userId=alice", "bob",
                      headers={"X-User-Id": "alice", "X-Uid": "alice", "X-Student-Id": "alice"})
        self.assertEqual(r.get_json(), [])
        r = self.call("POST", "/api/tasks", "bob", json={**TASK, "subject_id": self.default_subject_id("bob"),
                                                         "student_id": "alice", "uid": "alice", "userId": "alice"})
        self.assertEqual(r.status_code, 201)
        self.assertEqual(self.task_doc(r.get_json()["task_id"])["student_id"], "bob")
        r = self.call("POST", "/api/subjects", "bob", json={"subject_name": "Bob's", "student_id": "alice"})
        self.assertEqual(self.db.store[("subjects", r.get_json()["subject_id"])]["student_id"], "bob")
        self.assertEqual(len(self.call("GET", "/api/tasks", "alice").get_json()), 1)

    def test_student_document_is_keyed_by_the_verified_uid_only(self):
        r = self.call("PUT", "/api/settings", "bob", json={"full_name": "Bob B", "student_id": "alice",
                                                          "email": "alice@example.com"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.db.store[("students", "bob")]["student_id"], "bob")
        self.assertEqual(self.db.store[("students", "bob")]["email"], "bob@example.com")
        self.assertNotEqual(self.db.store[("students", "alice")]["full_name"], "Bob B")
        self.assertEqual(self.db.store[("students", "alice")]["email"], "alice@example.com")

    def test_a_student_document_with_a_tampered_owner_is_not_reachable(self):
        # A task whose stored student_id differs from the caller is invisible, even with the right task id.
        self.db.store[("tasks", self.tid)]["student_id"] = "someone-else"
        self.assertEqual(self.call("PATCH", f"/api/tasks/{self.tid}", "alice", json={"title": "x"}).status_code, 404)
        self.assertEqual(self.call("GET", "/api/tasks", "alice").get_json(), [])


if __name__ == "__main__":
    unittest.main()
