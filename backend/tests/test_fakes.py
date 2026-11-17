"""Checks for the fake Firestore itself, so the other tests can be trusted."""
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from fakes import MAX_BATCH_WRITES, FakeAlreadyExists, FakeFirestore  # noqa: E402


class FakeFirestoreTests(unittest.TestCase):
    def setUp(self):
        self.db = FakeFirestore()
        for i, (owner, subject) in enumerate([("a", "x"), ("a", "y"), ("b", "x")]):
            self.db.collection("tasks").document(f"t{i}").set({"student_id": owner, "subject_id": subject})

    def ids(self, query):
        return sorted(s.id for s in query.stream())

    def test_where_filters_and_chains(self):
        tasks = self.db.collection("tasks")
        self.assertEqual(self.ids(tasks.where("student_id", "==", "a")), ["t0", "t1"])
        self.assertEqual(self.ids(tasks.where("student_id", "==", "a").where("subject_id", "==", "y")), ["t1"])
        self.assertEqual(self.ids(tasks.where("student_id", "==", "zzz")), [])
        with self.assertRaises(NotImplementedError):
            tasks.where("student_id", "!=", "a")

    def test_limit(self):
        self.assertEqual(len(list(self.db.collection("tasks").limit(2).stream())), 2)
        self.assertEqual(len(list(self.db.collection("tasks").where("subject_id", "==", "x").limit(1).stream())), 1)

    def test_create_fails_if_the_document_exists_and_never_overwrites(self):
        ref = self.db.collection("tasks").document("t0")
        with self.assertRaises(FakeAlreadyExists):
            ref.create({"student_id": "evil"})
        self.assertEqual(ref.get().to_dict()["student_id"], "a")
        self.db.collection("tasks").document("new").create({"student_id": "a"})
        self.assertTrue(self.db.collection("tasks").document("new").get().exists)

    def test_batch_is_limited_to_500_writes_and_is_atomic(self):
        batch = self.db.batch()
        for i in range(MAX_BATCH_WRITES + 1):
            batch.set(self.db.collection("many").document(f"d{i}"), {"n": i})
        with self.assertRaises(ValueError):
            batch.commit()
        self.assertEqual(list(self.db.collection("many").stream()), [])
        ok = self.db.batch()
        for i in range(MAX_BATCH_WRITES):
            ok.create(self.db.collection("many").document(f"d{i}"), {"n": i})
        ok.commit()
        self.assertEqual(len(list(self.db.collection("many").stream())), MAX_BATCH_WRITES)

    def test_batch_create_conflict_writes_nothing(self):
        batch = self.db.batch()
        batch.create(self.db.collection("tasks").document("fresh"), {"student_id": "a"})
        batch.create(self.db.collection("tasks").document("t0"), {"student_id": "evil"})
        with self.assertRaises(FakeAlreadyExists):
            batch.commit()
        self.assertFalse(self.db.collection("tasks").document("fresh").get().exists)
        self.assertEqual(self.db.collection("tasks").document("t0").get().to_dict()["student_id"], "a")

    def test_list_documents_includes_parents_that_only_have_subcollections(self):
        self.db.collection("users").document("ghost").collection("tasks").document("t").set({"x": 1})
        self.db.collection("users").document("real").set({"name": "r"})
        self.assertEqual([s.id for s in self.db.collection("users").stream()], ["real"])  # stream misses the ghost
        self.assertEqual(sorted(d.id for d in self.db.collection("users").list_documents()), ["ghost", "real"])

    def test_write_log_and_forbidden_paths(self):
        self.db.writes.clear()
        self.db.collection("tasks").document("t0").set({"student_id": "a"})
        self.db.collection("tasks").document("t0").delete()
        self.assertEqual([op for op, _ in self.db.writes], ["set", "delete"])
        self.db.forbidden.append(("users",))
        with self.assertRaises(AssertionError):
            self.db.collection("users").document("x").get()
        with self.assertRaises(AssertionError):
            list(self.db.collection("users").stream())
        self.db.collection("tasks").document("t1").get()  # other paths are fine


if __name__ == "__main__":
    unittest.main()
