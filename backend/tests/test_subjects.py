"""Subjects: CRUD, validation, per-student uniqueness, delete blocked while tasks use the subject, deterministic ids."""
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from base import ApiTestCase  # noqa: E402
import store  # noqa: E402


class SubjectCrudTests(ApiTestCase):
    def test_create_returns_exact_shape_and_trims(self):
        r = self.call("POST", "/api/subjects", json={"subject_name": "  Database Systems  "})
        self.assertEqual(r.status_code, 201)
        body = r.get_json()
        self.assertEqual(set(body), {"subject_id", "subject_name"})
        self.assertEqual(body["subject_name"], "Database Systems")
        doc = self.db.store[("subjects", body["subject_id"])]
        self.assertEqual(doc, {"subject_id": body["subject_id"], "student_id": "alice", "subject_name": "Database Systems"})

    def test_client_supplied_ids_are_ignored(self):
        r = self.call("POST", "/api/subjects", json={"subject_name": "Math", "subject_id": "hacked", "student_id": "bob"})
        body = r.get_json()
        self.assertNotEqual(body["subject_id"], "hacked")
        self.assertEqual(self.db.store[("subjects", body["subject_id"])]["student_id"], "alice")
        self.assertEqual(self.call("GET", "/api/subjects", "bob").get_json(), [])

    def test_list_is_own_subjects_sorted_by_name(self):
        for name in ("Zoology", "algebra", "Biology"):
            self.add_subject("alice", name)
        self.add_subject("bob", "Bob's subject")
        names = [s["subject_name"] for s in self.call("GET", "/api/subjects").get_json()]
        self.assertEqual(names, ["algebra", "Biology", "Zoology"])

    def test_validation(self):
        for value in ("", "   ", None, 5, ["x"], "x" * 101):
            r = self.call("POST", "/api/subjects", json={"subject_name": value})
            self.assertEqual(r.status_code, 422, value)
            self.assertIn("subject_name", r.get_json()["errors"])
        self.assertEqual(self.call("POST", "/api/subjects", json={}).status_code, 422)
        subject = self.add_subject()
        for body in ({}, {"unknown": 1}, {"subject_name": ""}):
            self.assertEqual(self.call("PATCH", f"/api/subjects/{subject['subject_id']}", json=body).status_code, 422, body)

    def test_names_are_unique_per_student_ignoring_case_and_spaces(self):
        self.add_subject("alice", "Operating Systems")
        for name in ("operating systems", "  OPERATING   systems "):
            r = self.call("POST", "/api/subjects", json={"subject_name": name})
            self.assertEqual(r.status_code, 422, name)
            self.assertIn("subject_name", r.get_json()["errors"])
        self.assertEqual(self.add_subject("bob", "Operating Systems")["subject_name"], "Operating Systems")

    def test_rename(self):
        math = self.add_subject("alice", "Math")
        other = self.add_subject("alice", "Science")
        r = self.call("PATCH", f"/api/subjects/{math['subject_id']}", json={"subject_name": " Calculus "})
        self.assertEqual(r.get_json(), {"subject_id": math["subject_id"], "subject_name": "Calculus"})
        clash = self.call("PATCH", f"/api/subjects/{other['subject_id']}", json={"subject_name": "calculus"})
        self.assertEqual(clash.status_code, 422)
        same = self.call("PATCH", f"/api/subjects/{math['subject_id']}", json={"subject_name": "calculus"})
        self.assertEqual(same.status_code, 200)  # renaming to its own name (different case) is allowed

    def test_delete_unused_subject(self):
        subject = self.add_subject()
        r = self.call("DELETE", f"/api/subjects/{subject['subject_id']}")
        self.assertEqual((r.status_code, r.data), (204, b""))
        self.assertEqual(self.call("GET", "/api/subjects").get_json(), [])
        self.assertEqual(self.call("DELETE", f"/api/subjects/{subject['subject_id']}").status_code, 404)

    def test_delete_is_rejected_while_tasks_reference_the_subject(self):
        subject = self.add_subject()
        keep = self.add_subject("alice", "Other subject")
        first = self.add_task(subject_id=subject["subject_id"], title="One")
        second = self.add_task(subject_id=subject["subject_id"], title="Two")
        r = self.call("DELETE", f"/api/subjects/{subject['subject_id']}")
        self.assertEqual(r.status_code, 409)
        body = r.get_json()
        self.assertIn("still has tasks", body["detail"])
        self.assertIn("Reassign or delete", body["detail"])
        self.assertIn("subject_id", body["errors"])
        self.assertIn(("subjects", subject["subject_id"]), self.db.store)  # not deleted
        # reassign one task: still blocked by the other
        self.call("PATCH", f"/api/tasks/{first['task_id']}", json={"subject_id": keep["subject_id"]})
        self.assertEqual(self.call("DELETE", f"/api/subjects/{subject['subject_id']}").status_code, 409)
        # delete the other task: now allowed
        self.call("DELETE", f"/api/tasks/{second['task_id']}")
        self.assertEqual(self.call("DELETE", f"/api/subjects/{subject['subject_id']}").status_code, 204)

    def test_delete_is_also_rejected_for_completed_tasks(self):
        subject = self.add_subject()
        task = self.add_task(subject_id=subject["subject_id"])
        self.call("POST", f"/api/tasks/{task['task_id']}/complete")
        self.assertEqual(self.call("DELETE", f"/api/subjects/{subject['subject_id']}").status_code, 409)

    def test_other_students_tasks_never_block_or_leak(self):
        subject = self.add_subject("alice")
        self.add_task("bob")  # bob's own subject/task
        self.assertEqual(self.call("DELETE", f"/api/subjects/{subject['subject_id']}").status_code, 204)


class DeterministicSubjectIdTests(unittest.TestCase):
    def test_same_student_and_subject_always_give_the_same_id(self):
        a = store.deterministic_subject_id("alice", "Database Systems")
        self.assertEqual(a, store.deterministic_subject_id("alice", "Database Systems"))
        self.assertEqual(a, store.deterministic_subject_id("alice", "  database   SYSTEMS "))

    def test_different_student_or_subject_gives_a_different_id(self):
        a = store.deterministic_subject_id("alice", "Math")
        self.assertNotEqual(a, store.deterministic_subject_id("bob", "Math"))
        self.assertNotEqual(a, store.deterministic_subject_id("alice", "Science"))
        self.assertNotEqual(store.deterministic_subject_id("ab", "c"), store.deterministic_subject_id("a", "bc"))

    def test_id_is_a_valid_document_id_and_stable_across_processes(self):
        sid = store.deterministic_subject_id("alice", "Math")
        self.assertTrue(store.valid_id(sid))
        self.assertEqual(sid, "sub_" + __import__("hashlib").sha256("alice\x1fmath".encode()).hexdigest()[:24])


if __name__ == "__main__":
    unittest.main()
