"""Tasks: create/list/update/delete with the approved field names and enums, and server-owned fields."""
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from base import TASK, TASK_FIELDS, ApiTestCase  # noqa: E402


class TaskTests(ApiTestCase):
    def test_create_returns_exact_shape_and_starts_not_started_at_zero(self):
        task = self.add_task()
        self.assertEqual(set(task), TASK_FIELDS)
        self.assertTrue(task["task_id"])
        self.assertEqual((task["status"], task["progress_pct"]), ("not_started", 0))
        self.assertEqual({k: task[k] for k in TASK}, TASK)

    def test_stored_document_is_server_controlled(self):
        task = self.add_task()
        doc = self.task_doc(task["task_id"])
        self.assertEqual(doc["task_id"], task["task_id"])
        self.assertEqual(doc["student_id"], "alice")
        self.assertEqual(doc["status"], "not_started")
        self.assertEqual(doc["progress_pct"], 0)
        self.assertNotIn("completed_on", doc)
        self.assertTrue(doc["created_at"] and doc["updated_at"])

    def test_client_supplied_server_fields_are_ignored(self):
        task = self.add_task(task_id="hacked", student_id="bob", completed_on="2020-01-01", created_at="x",
                             updated_at="y", foo="bar")
        self.assertNotEqual(task["task_id"], "hacked")
        self.assertEqual(set(task), TASK_FIELDS)
        doc = self.task_doc(task["task_id"])
        self.assertEqual(doc["student_id"], "alice")
        self.assertNotIn("completed_on", doc)
        self.assertNotIn("foo", doc)
        self.assertNotIn(("tasks", "hacked"), self.db.store)
        self.assertNotIn("x", (doc["created_at"], doc["updated_at"]))
        self.assertNotEqual(doc["created_at"], "x")
        self.assertEqual(self.call("GET", "/api/tasks", "bob").get_json(), [])

    def test_create_rejects_client_status_and_progress(self):
        subject_id = self.default_subject_id("alice")
        for field, value in (("status", "completed"), ("status", "not_started"), ("progress_pct", 50),
                             ("progress_pct", 0)):
            r = self.call("POST", "/api/tasks", json={**TASK, "subject_id": subject_id, field: value})
            self.assertEqual(r.status_code, 422, (field, value))
            self.assertIn(field, r.get_json()["errors"])
        self.assertEqual(self.call("GET", "/api/tasks").get_json(), [])

    def test_create_requires_an_owned_subject(self):
        bobs = self.add_subject("bob", "Bob's subject")
        for subject_id in ("does-not-exist", bobs["subject_id"]):
            r = self.call("POST", "/api/tasks", json={**TASK, "subject_id": subject_id})
            self.assertEqual(r.status_code, 422, subject_id)
            self.assertIn("subject_id", r.get_json()["errors"])
        self.assertEqual(self.call("GET", "/api/tasks").get_json(), [])
        self.assertEqual(self.call("GET", "/api/tasks", "bob").get_json(), [])

    def test_validation_errors(self):
        subject_id = self.default_subject_id("alice")
        bad = {
            "title": ["", "   ", None, 5, "x" * 121],
            "category": ["Assignment", "homework", "", None, ["assignment"], "Examination"],
            "importance": ["urgent", "High", "", None, 3],
            "deadline": ["2026-02-30", "11/01/2026", "2026-1-5", "20261101", "", None, 5],
            "subject_id": ["", None, 5, "a b", "../x", "x" * 129],
        }
        for field, values in bad.items():
            for value in values:
                r = self.call("POST", "/api/tasks", json={**TASK, "subject_id": subject_id, field: value})
                self.assertEqual(r.status_code, 422, (field, value))
                body = r.get_json()
                self.assertIsInstance(body["detail"], str)
                self.assertIn(field, body["errors"])

    def test_every_approved_category_and_importance_is_accepted(self):
        for category in ("assignment", "project", "exam", "quiz", "research", "other"):
            self.assertEqual(self.add_task(category=category)["category"], category)
        for importance in ("low", "medium", "high"):
            self.assertEqual(self.add_task(importance=importance)["importance"], importance)

    def test_old_field_names_are_not_accepted(self):
        old = {"title": "Old shape", "course": "CS", "category": "Assignment", "deadline": "2026-11-20",
               "priority": "High", "progress": 65}
        r = self.call("POST", "/api/tasks", json=old)
        self.assertEqual(r.status_code, 422)
        self.assertTrue({"subject_id", "importance", "category"} <= set(r.get_json()["errors"]))

    def test_missing_required_fields(self):
        r = self.call("POST", "/api/tasks", json={})
        self.assertEqual(r.status_code, 422)
        self.assertEqual(set(r.get_json()["errors"]), {"title", "subject_id", "category", "deadline", "importance"})

    def test_body_must_be_a_json_object(self):
        for payload in ("not json", "[1,2]", '"text"', ""):
            r = self.call("POST", "/api/tasks", data=payload, content_type="application/json")
            self.assertEqual(r.status_code, 400, payload)
            self.assertIn("detail", r.get_json())

    def test_list_returns_only_own_tasks_in_creation_order(self):
        first = self.add_task(title="First")
        second = self.add_task(title="Second")
        self.add_task("bob", title="Bob's")
        tasks = self.call("GET", "/api/tasks").get_json()
        self.assertEqual([t["title"] for t in tasks], ["First", "Second"])
        self.assertEqual([t["task_id"] for t in tasks], [first["task_id"], second["task_id"]])
        self.assertTrue(all(set(t) == TASK_FIELDS for t in tasks))

    def test_patch_updates_only_sent_fields(self):
        task = self.add_task()
        r = self.call("PATCH", f"/api/tasks/{task['task_id']}",
                      json={"title": " New title ", "importance": "low", "ignored": 1})
        self.assertEqual(r.status_code, 200)
        updated = r.get_json()
        self.assertEqual(set(updated), TASK_FIELDS)
        self.assertEqual((updated["title"], updated["importance"], updated["category"], updated["deadline"]),
                         ("New title", "low", TASK["category"], TASK["deadline"]))
        self.assertEqual((updated["status"], updated["progress_pct"]), ("not_started", 0))
        self.assertEqual(self.get_task(task["task_id"])["title"], "New title")

    def test_patch_can_move_a_task_to_another_owned_subject(self):
        other = self.add_subject("alice", "Another")
        task = self.add_task()
        r = self.call("PATCH", f"/api/tasks/{task['task_id']}", json={"subject_id": other["subject_id"]})
        self.assertEqual(r.get_json()["subject_id"], other["subject_id"])

    def test_patch_rejects_status_and_ignores_server_fields(self):
        task = self.add_task()
        path = f"/api/tasks/{task['task_id']}"
        r = self.call("PATCH", path, json={"status": "completed"})
        self.assertEqual(r.status_code, 422)
        self.assertIn("status", r.get_json()["errors"])
        r = self.call("PATCH", path, json={"title": "Ok", "status": "in_progress"})
        self.assertEqual(r.status_code, 422)
        self.assertEqual(self.get_task(task["task_id"])["title"], TASK["title"])
        r = self.call("PATCH", path, json={"title": "Ok2", "student_id": "bob", "task_id": "x", "completed_on": "2020-01-01",
                                           "created_at": "z"})
        self.assertEqual(r.status_code, 200)
        doc = self.task_doc(task["task_id"])
        self.assertEqual((doc["student_id"], doc["task_id"]), ("alice", task["task_id"]))
        self.assertNotIn("completed_on", doc)
        self.assertNotEqual(doc["created_at"], "z")

    def test_patch_validation_and_empty_body(self):
        task_id = self.add_task()["task_id"]
        for body in ({}, {"unknown": 1}, {"progress_pct": 150}, {"progress_pct": -1}, {"progress_pct": "50"},
                     {"progress_pct": True}, {"progress_pct": 50.5}, {"deadline": "soon"}, {"importance": "x"},
                     {"category": "Assignment"}, {"subject_id": "nope"}):
            r = self.call("PATCH", f"/api/tasks/{task_id}", json=body)
            self.assertEqual(r.status_code, 422, body)
        self.assertEqual(self.get_task(task_id)["progress_pct"], 0)

    def test_patch_to_another_students_subject_is_rejected(self):
        task_id = self.add_task()["task_id"]
        bobs = self.add_subject("bob", "Bob's")
        r = self.call("PATCH", f"/api/tasks/{task_id}", json={"subject_id": bobs["subject_id"]})
        self.assertEqual(r.status_code, 422)
        self.assertNotEqual(self.get_task(task_id)["subject_id"], bobs["subject_id"])

    def test_unknown_or_malformed_ids_are_404(self):
        self.assertEqual(self.call("PATCH", "/api/tasks/nope", json={"progress_pct": 5}).status_code, 404)
        self.assertEqual(self.call("DELETE", "/api/tasks/nope").status_code, 404)
        for weird in ("..", ".", "a.b", "a%20b"):
            self.assertEqual(self.call("DELETE", f"/api/tasks/{weird}").status_code, 404, weird)

    def test_delete_returns_204_and_removes_task(self):
        task_id = self.add_task()["task_id"]
        r = self.call("DELETE", f"/api/tasks/{task_id}")
        self.assertEqual((r.status_code, r.data), (204, b""))
        self.assertEqual(self.call("GET", "/api/tasks").get_json(), [])
        self.assertEqual(self.call("DELETE", f"/api/tasks/{task_id}").status_code, 404)


if __name__ == "__main__":
    unittest.main()
