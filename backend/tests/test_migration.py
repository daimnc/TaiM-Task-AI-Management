"""Phase 2 migration tests. Fake Firestore and fake Auth only: no network, no real Firebase project."""
import copy
import io
import json
import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from base import ApiTestCase  # noqa: E402  (also sets up sys.path and keeps the tests away from real Firebase)
from fakes import FakeFirestore  # noqa: E402

import migrate_legacy as m  # noqa: E402
import store  # noqa: E402

CREATED_MS = 1700000000000
CREATED_ISO = "2023-11-14T22:13:20+00:00"


def auth_info(uid, display_name=None, created_ms=CREATED_MS, email="default"):
    email = f"{uid}@example.com" if email == "default" else email
    return m.AuthInfo(email, display_name if display_name is not None else uid.capitalize(), created_ms)


def legacy_task(**over):
    base = {"title": "Secret Title", "course": "Math", "category": "Assignment", "deadline": "2026-11-20",
            "priority": "High", "progress": 50, "createdAt": "2026-11-01T00:00:00+00:00",
            "updatedAt": "2026-11-02T00:00:00+00:00"}
    base.update(over)
    return {k: v for k, v in base.items() if v is not ...}  # pass key=... to drop a field


def put_task(db, uid, task_id, **over):
    db.store[("users", uid, "tasks", task_id)] = legacy_task(**over)


def put_settings(db, uid, **over):
    db.store[("users", uid, "preferences", "settings")] = {"name": "Settings Name", "program": "BS CS", "leadDays": 3,
                                                           "sessionMinutes": 25, "weeklySummary": True, **over}


def put_reminders(db, uid, **over):
    db.store[("users", uid, "preferences", "reminders")] = {"deadline": False, "dailySummary": True,
                                                            "progressCheckin": True, "quietHours": False, **over}


def legacy_snapshot(db):
    return copy.deepcopy({k: v for k, v in db.store.items() if k[0] == "users"})


def new_docs(db):
    return {k: v for k, v in db.store.items() if k[0] != "users"}


def fail_commit_when(db, predicate, exc=RuntimeError):
    """Make `batch.commit()` raise (before anything is applied) when predicate(ops, commit_number) is true."""
    real_batch, counter = db.batch, {"n": 0}

    def batch():
        b = real_batch()
        real_commit = b.commit

        def commit():
            counter["n"] += 1
            if predicate(b._ops, counter["n"]):
                raise exc("injected failure")
            real_commit()
        b.commit = commit
        return b
    db.batch = batch


def after_commit(db, action):
    """Run action(db) right after every successful commit (to simulate corruption or a concurrent legacy edit)."""
    real_batch = db.batch

    def batch():
        b = real_batch()
        real_commit = b.commit

        def commit():
            real_commit()
            action(db)
        b.commit = commit
        return b
    db.batch = batch


class MigrationCase(unittest.TestCase):
    def setUp(self):
        self.db = FakeFirestore()
        self.auth = {}
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def lookup(self, uid):
        value = self.auth.get(uid, "missing")
        if value == "missing":
            raise m.AuthNotFound(uid)
        if isinstance(value, Exception):
            raise value
        return value

    def add_user(self, uid, **auth_kwargs):
        self.auth[uid] = auth_info(uid, **auth_kwargs)

    def go(self, *argv, enable_v2=False, project_id="proj"):
        out = io.StringIO()
        code = m.main(list(argv), db=self.db, auth_lookup=self.lookup, enable_v2=enable_v2, project_id=project_id,
                      report_dir=pathlib.Path(self.tmp.name), out=out)
        self.output = out.getvalue()
        return code

    def apply(self, *extra, **kw):
        return self.go("--apply", "--confirm-project", "proj", *extra, **kw)

    def report(self):
        files = sorted(pathlib.Path(self.tmp.name).glob("migration-*.json"))
        return json.loads(files[-1].read_text(encoding="utf-8"))

    def state(self, uid):
        return next(s for s in self.report()["students"] if s["uid"] == uid)["state"]

    def student_report(self, uid):
        return next(s for s in self.report()["students"] if s["uid"] == uid)

    def simple_user(self, uid="alice", tasks=1, **task_over):
        self.add_user(uid)
        for i in range(tasks):
            put_task(self.db, uid, f"{uid}t{i}", **task_over)


class StatusMappingTests(MigrationCase):
    def test_every_status_case(self):
        self.add_user("alice")
        put_task(self.db, "alice", "p0", progress=0)
        put_task(self.db, "alice", "p1", progress=1)
        put_task(self.db, "alice", "p99", progress=99)
        put_task(self.db, "alice", "p100d", progress=100, completedOn="2026-11-15")
        put_task(self.db, "alice", "p100n", progress=100)
        put_task(self.db, "alice", "p100null", progress=100, completedOn=None)
        put_task(self.db, "alice", "p65null", progress=65, completedOn=None)
        self.assertEqual(self.apply(), 0, self.output)
        doc = lambda tid: self.db.store[("tasks", tid)]  # noqa: E731
        self.assertEqual((doc("p0")["status"], doc("p0")["progress_pct"]), ("not_started", 0))
        self.assertEqual(doc("p1")["status"], "in_progress")
        self.assertEqual(doc("p99")["status"], "in_progress")
        self.assertEqual(doc("p65null")["status"], "in_progress")
        for tid in ("p100d", "p100n", "p100null"):
            self.assertEqual((doc(tid)["status"], doc(tid)["progress_pct"]), ("completed", 100))
        self.assertEqual(doc("p100d")["completed_on"], "2026-11-15")
        self.assertNotIn("completed_on", doc("p100n"))
        self.assertNotIn("completed_on", doc("p100null"))
        counts = self.student_report("alice")["findings"]
        self.assertEqual(counts["completed_without_date"], 2)
        self.assertEqual(counts["status_derived"], 4)

    def test_completed_on_with_open_progress_blocks_the_student(self):
        self.simple_user(progress=80, completedOn="2026-11-15")
        self.assertEqual(self.apply(), 2)
        self.assertEqual(self.state("alice"), m.BLOCKED)
        self.assertEqual(new_docs(self.db), {})

    def test_invalid_completed_on_blocks(self):
        self.simple_user(progress=100, completedOn="15/11/2026")
        self.assertEqual(self.apply(), 2)
        self.assertEqual(self.student_report("alice")["invalid"][0]["field"], "completedOn")


class FieldMappingTests(MigrationCase):
    def test_enums_and_fields(self):
        self.add_user("alice")
        for tid, cat, pri in [("a", "Assignment", "High"), ("b", "Research", "Medium"), ("c", "Project", "Low"),
                              ("d", "Examination", "High")]:
            put_task(self.db, "alice", tid, category=cat, priority=pri, title="  Padded  ")
        self.assertEqual(self.apply(), 0, self.output)
        got = {tid: self.db.store[("tasks", tid)] for tid in "abcd"}
        self.assertEqual([got[t]["category"] for t in "abcd"], ["assignment", "research", "project", "exam"])
        self.assertEqual([got[t]["importance"] for t in "abcd"], ["high", "medium", "low", "high"])
        self.assertEqual(got["a"]["title"], "Padded")
        self.assertEqual(got["a"]["student_id"], "alice")
        self.assertNotIn("quiz", [g["category"] for g in got.values()])
        self.assertEqual(set(got["a"]), {"task_id", "student_id", "subject_id", "title", "deadline", "importance",
                                          "category", "progress_pct", "status", "created_at", "updated_at"})

    def test_invalid_records_block_with_zero_writes_and_are_listed(self):
        bad = [dict(priority="Urgent"), dict(category="Quiz"), dict(title="   "), dict(title=...),
               dict(deadline="2026-02-30"), dict(deadline="soon"), dict(progress=True), dict(progress="50"),
               dict(progress=50.0), dict(progress=101), dict(course="x" * 101), dict(title="t" * 121),
               dict(createdAt=12345)]
        for i, over in enumerate(bad):
            with self.subTest(over=over):
                self.setUp()
                self.simple_user(**over)
                self.assertEqual(self.apply(), 2, self.output)
                self.assertEqual(self.state("alice"), m.BLOCKED)
                self.assertEqual(self.db.writes, [])
                self.assertTrue(self.student_report("alice")["invalid"])

    def test_invalid_document_id_blocks(self):
        self.add_user("alice")
        put_task(self.db, "alice", "bad id with spaces")
        self.assertEqual(self.apply(), 2)
        self.assertEqual(self.db.writes, [])

    def test_subjects_are_deterministic_merged_case_insensitively_and_uncategorized(self):
        self.add_user("alice")
        put_task(self.db, "alice", "t2", course="cs 101", createdAt="2026-11-05T00:00:00+00:00")
        put_task(self.db, "alice", "t1", course="CS 101", createdAt="2026-11-01T00:00:00+00:00")
        put_task(self.db, "alice", "t3", course="")
        put_task(self.db, "alice", "t4", course=...)
        self.assertEqual(self.apply(), 0, self.output)
        subjects = {d["subject_name"]: d for k, d in self.db.store.items() if k[0] == "subjects"}
        self.assertEqual(set(subjects), {"CS 101", "Uncategorized"})  # oldest task's spelling wins
        self.assertEqual(subjects["CS 101"]["subject_id"], store.deterministic_subject_id("alice", "CS 101"))
        self.assertEqual(self.db.store[("tasks", "t1")]["subject_id"], self.db.store[("tasks", "t2")]["subject_id"])
        self.assertEqual(self.db.store[("tasks", "t3")]["subject_id"], subjects["Uncategorized"]["subject_id"])
        self.assertEqual(self.db.store[("tasks", "t4")]["subject_id"], subjects["Uncategorized"]["subject_id"])
        self.assertEqual(self.student_report("alice")["findings"]["subject_spellings_merged"], 1)

    def test_same_subject_gets_the_same_id_on_a_fresh_rerun(self):
        self.simple_user(course="Physics")
        self.apply()
        first = {k: v for k, v in self.db.store.items() if k[0] == "subjects"}
        users = legacy_snapshot(self.db)
        self.setUp()
        self.add_user("alice")
        self.db.store.update(users)
        self.apply()
        self.assertEqual({k: v for k, v in self.db.store.items() if k[0] == "subjects"}, first)


class DateTests(MigrationCase):
    def test_missing_or_null_dates_are_omitted_never_fabricated(self):
        self.add_user("alice")
        put_task(self.db, "alice", "nodates", createdAt=..., updatedAt=...)
        put_task(self.db, "alice", "nulls", createdAt=None, updatedAt=None)
        put_task(self.db, "alice", "onlycreated", updatedAt=...)
        self.assertEqual(self.apply(), 0, self.output)
        for tid in ("nodates", "nulls"):
            doc = self.db.store[("tasks", tid)]
            self.assertNotIn("created_at", doc)
            self.assertNotIn("updated_at", doc)
        only = self.db.store[("tasks", "onlycreated")]
        self.assertEqual(only["created_at"], "2026-11-01T00:00:00+00:00")
        self.assertNotIn("updated_at", only)  # never filled from created_at
        self.assertTrue(all(v is not None for d in new_docs(self.db).values() for v in d.values()))
        counts = self.student_report("alice")["findings"]
        self.assertEqual(counts["missing:task_created_at"], 2)
        self.assertEqual(counts["missing:task_updated_at"], 3)

    def test_student_created_at_comes_from_auth(self):
        self.simple_user()
        self.apply()
        self.assertEqual(self.db.store[("students", "alice")]["created_at"], CREATED_ISO)
        self.assertEqual(self.student_report("alice")["info"]["created_at_source"], "auth")

    def test_missing_auth_creation_time_blocks_with_zero_writes(self):
        for missing in (None, 0):
            with self.subTest(missing=missing):
                self.setUp()
                self.simple_user()
                self.auth["alice"] = auth_info("alice", created_ms=missing)
                self.assertEqual(self.apply(), 2)
                self.assertEqual(self.state("alice"), m.BLOCKED)
                self.assertEqual(self.db.writes, [])
                self.assertIn({"code": "missing_auth_created_at"}, self.student_report("alice")["blocking"])


class StudentDocumentTests(MigrationCase):
    def test_settings_and_reminders_are_mapped_and_dropped_fields_counted(self):
        self.simple_user()
        put_settings(self.db, "alice")
        put_reminders(self.db, "alice")
        self.assertEqual(self.apply(), 0, self.output)
        self.assertEqual(self.db.store[("students", "alice")], {
            "student_id": "alice", "full_name": "Settings Name", "email": "alice@example.com",
            "created_at": CREATED_ISO, "lead_days": 3, "session_minutes": 25,
            "reminder_prefs": {"deadline": False, "dailySummary": True, "progressCheckin": True, "quietHours": False}})
        report = self.student_report("alice")
        self.assertEqual(report["findings"]["dropped:program"], 1)
        self.assertEqual(report["findings"]["dropped:weeklySummary"], 1)
        self.assertEqual((report["info"]["name_source"], report["info"]["email_source"]), ("settings", "auth"))

    def test_absent_settings_use_legacy_defaults_and_auth_names(self):
        for display, email, expected, source in [("Display", "x@y.com", "Display", "auth_display_name"),
                                                 ("", "prefix@y.com", "prefix", "auth_email_prefix"),
                                                 ("", None, "Student", "default")]:
            with self.subTest(source=source):
                self.setUp()
                self.simple_user()
                self.auth["alice"] = m.AuthInfo(email, display, CREATED_MS)
                self.assertEqual(self.apply(), 0, self.output)
                doc = self.db.store[("students", "alice")]
                self.assertEqual((doc["full_name"], doc["lead_days"], doc["session_minutes"]), (expected, 2, 45))
                self.assertEqual(doc["reminder_prefs"], store.REMINDER_DEFAULTS)
                self.assertEqual(self.student_report("alice")["info"]["name_source"], source)
                self.assertEqual(doc["email"], email or "")

    def test_invalid_preferences_block(self):
        for settings, reminders in [({"leadDays": 4}, {}), ({"leadDays": True}, {}), ({"sessionMinutes": 30}, {}),
                                    ({"name": "x" * 81}, {}), ({"name": 5}, {}), ({}, {"deadline": "yes"})]:
            with self.subTest(settings=settings, reminders=reminders):
                self.setUp()
                self.simple_user()
                put_settings(self.db, "alice", **settings)
                put_reminders(self.db, "alice", **reminders)
                self.assertEqual(self.apply(), 2)
                self.assertEqual(self.state("alice"), m.BLOCKED)
                self.assertEqual(self.db.writes, [])


class SafeguardTests(MigrationCase):
    def locked(self):
        self.simple_user()
        self.db.forbidden.append(())  # any database access at all raises AssertionError

    def test_apply_refusals_happen_before_any_database_access(self):
        self.locked()
        self.assertEqual(self.go("--apply"), 1)
        self.assertEqual(self.go("--apply", "--confirm-project", "other"), 1)
        self.assertEqual(self.go("--apply", "--confirm-project", "proj", enable_v2=True), 1)
        self.assertEqual(self.go("--apply", "--confirm-project", "proj", project_id=""), 1)

    def test_usage_errors_exit_1_not_2(self):
        self.locked()
        self.assertEqual(self.go("--bogus"), 1)
        self.assertEqual(self.go("--only-uid", "a/b"), 1)

    def test_confirm_must_also_match_the_connected_project(self):
        self.simple_user()
        self.db.project = "some-other-project"
        self.assertEqual(self.apply(), 1)
        self.assertEqual(self.db.writes, [])

    def test_dry_run_is_the_default_and_writes_nothing(self):
        self.simple_user()
        before = copy.deepcopy(self.db.store)
        self.assertEqual(self.go(), 3)
        self.assertEqual(self.db.writes, [])
        self.assertEqual(self.db.store, before)
        self.assertEqual(self.state("alice"), m.WOULD_MIGRATE)
        self.assertEqual(self.report()["mode"], "dry-run")

    def test_v2_flag_is_only_read_never_changed(self):
        import os
        before = os.environ.get("TAIM_ENABLE_V2")
        self.simple_user()
        self.apply()
        self.assertEqual(os.environ.get("TAIM_ENABLE_V2"), before)

    def test_dry_run_is_still_allowed_while_v2_is_on(self):
        self.simple_user()
        self.assertEqual(self.go(enable_v2=True), 3)


class ApplyAndExitCodeTests(MigrationCase):
    def test_exit_code_function(self):
        self.assertEqual(m.exit_code_for([m.MIGRATED, m.ALREADY_MIGRATED, m.NO_DATA]), 0)
        self.assertEqual(m.exit_code_for([m.MIGRATED, m.WOULD_MIGRATE]), 3)
        self.assertEqual(m.exit_code_for([m.NOT_SELECTED]), 3)
        self.assertEqual(m.exit_code_for([m.WOULD_MIGRATE, m.ORPHANED]), 2)
        for state in m.PROBLEM_STATES:
            self.assertEqual(m.exit_code_for([m.MIGRATED, state]), 2)

    def test_dry_run_apply_dry_run_sequence_and_legacy_untouched(self):
        self.simple_user(tasks=3)
        self.simple_user("bob")
        put_settings(self.db, "alice")
        legacy = legacy_snapshot(self.db)
        self.assertEqual(self.go(), 3)
        self.assertEqual(self.apply(), 0, self.output)
        self.assertEqual({s["state"] for s in self.report()["students"]}, {m.MIGRATED})
        writes_after_apply = len(self.db.writes)
        self.assertEqual(self.go(), 0, self.output)  # second dry-run: everything verified
        self.assertEqual({s["state"] for s in self.report()["students"]}, {m.ALREADY_MIGRATED})
        self.assertEqual(self.apply(), 0)
        self.assertEqual(len(self.db.writes), writes_after_apply)  # idempotent: nothing written again
        self.assertEqual(legacy_snapshot(self.db), legacy)
        self.assertTrue(all(op == "create" for op, _path in self.db.writes))
        self.assertFalse([w for w in self.db.writes if w[1][0] == "users"])

    def test_no_data_with_auth_counts_toward_zero_but_orphan_does_not(self):
        self.simple_user("alice")
        self.add_user("dave")
        self.db.store[("users", "dave")] = {"note": "parent document without legacy data"}
        self.assertEqual(self.apply(), 0, self.output)
        self.assertEqual(self.state("dave"), m.NO_DATA)
        self.assertNotIn(("students", "dave"), self.db.store)
        put_task(self.db, "carol", "ct")  # legacy data, but no Auth user
        self.assertEqual(self.apply(), 2)
        self.assertEqual(self.state("carol"), m.ORPHANED)
        self.assertEqual(self.state("alice"), m.ALREADY_MIGRATED)

    def test_orphan_with_only_a_parent_document_is_still_orphaned(self):
        self.db.store[("users", "ghost")] = {"x": 1}
        self.assertEqual(self.go(), 2)
        self.assertEqual(self.state("ghost"), m.ORPHANED)

    def test_unexpected_auth_error_is_failed_not_orphaned_and_others_continue(self):
        self.simple_user("alice")
        self.simple_user("bob")
        self.auth["bob"] = RuntimeError("auth service down")
        self.assertEqual(self.apply(), 2)
        self.assertEqual(self.state("bob"), m.FAILED)
        self.assertEqual(self.state("alice"), m.MIGRATED)
        self.assertNotIn(("students", "bob"), self.db.store)

    def test_read_error_for_one_student_is_isolated(self):
        self.simple_user("alice")
        self.simple_user("bob")
        real_get = self.db.collection

        def boom_for_bob(name):
            col = real_get(name)
            if name == "users":
                real_doc = col.document

                def document(doc_id=None):
                    if doc_id == "bob":
                        raise ConnectionError("read failed")
                    return real_doc(doc_id)
                col.document = document
            return col
        self.db.collection = boom_for_bob
        self.assertEqual(self.apply(), 2)
        self.assertEqual(self.state("bob"), m.FAILED)
        self.assertEqual(self.state("alice"), m.MIGRATED)

    def test_only_uid_gives_exit_3_and_writes_only_the_selected_student(self):
        self.simple_user("alice")
        self.simple_user("bob")
        self.assertEqual(self.apply("--only-uid", "alice"), 3)
        self.assertEqual(self.state("alice"), m.MIGRATED)
        self.assertEqual(self.state("bob"), m.NOT_SELECTED)
        self.assertIn(("students", "alice"), self.db.store)
        self.assertNotIn(("students", "bob"), self.db.store)
        self.assertEqual(self.go("--only-uid", "nobody"), 1)

    def test_no_discovered_students_is_reported(self):
        self.assertEqual(self.go(), 0)
        self.assertTrue(self.report()["warnings"])


class AtomicityTests(MigrationCase):
    def many(self, uid, n):
        self.add_user(uid)
        for i in range(n):
            put_task(self.db, uid, f"{uid}{i:04d}", course="Same")

    def test_single_batch_student_is_all_or_nothing(self):
        self.simple_user("alice", tasks=5)
        fail_commit_when(self.db, lambda ops, n: True)
        self.assertEqual(self.apply(), 2)
        self.assertEqual(self.state("alice"), m.FAILED)
        self.assertEqual(new_docs(self.db), {})
        batches = []
        self.db.batch = FakeFirestore.batch.__get__(self.db)
        real = self.db.batch

        def spy():
            b = real()
            batches.append(b)
            return b
        self.db.batch = spy
        self.assertEqual(self.apply(), 0)
        self.assertEqual(len(batches), 1)  # <= 400 documents: exactly one batch, marker included

    def test_multi_batch_failure_leaves_a_detectable_partial_state_and_resume_completes_it(self):
        self.many("alice", 450)  # 450 tasks + 1 subject + marker -> 400 + 51 children, then the marker alone
        fail_commit_when(self.db, lambda ops, n: n == 2)
        self.assertEqual(self.apply(), 2)
        self.assertEqual(self.state("alice"), m.PARTIAL)  # known non-atomic case across batches
        self.assertNotIn(("students", "alice"), self.db.store)
        self.assertEqual(len(new_docs(self.db)), 400)
        self.assertEqual(self.go(), 2)  # a dry-run reports the partial state too
        self.assertEqual(self.state("alice"), m.PARTIAL)

        self.db.batch = FakeFirestore.batch.__get__(self.db)  # remove the injected failure
        before = copy.deepcopy(new_docs(self.db))
        self.assertEqual(self.apply(), 0, self.output)
        self.assertEqual(self.state("alice"), m.MIGRATED)
        self.assertTrue(self.student_report("alice")["info"]["resumed"])
        self.assertEqual(len(new_docs(self.db)), 452)
        for key, value in before.items():
            self.assertEqual(self.db.store[key], value)  # nothing already written was touched
        self.assertEqual(self.go(), 0)

    def test_marker_is_written_last_and_batches_hold_at_most_400(self):
        self.many("alice", 450)
        sizes = []
        real = self.db.batch

        def spy():
            b = real()
            real_commit = b.commit

            def commit():
                sizes.append([op[1].path for op in b._ops])
                real_commit()
            b.commit = commit
            return b
        self.db.batch = spy
        self.assertEqual(self.apply(), 0)
        self.assertEqual([len(s) for s in sizes], [400, 51, 1])
        self.assertEqual(sizes[-1], ["students/alice"])
        self.assertEqual(sizes[0][0].split("/")[0], "subjects")  # subjects first

    def test_one_students_write_failure_leaves_the_others_migrated(self):
        for uid in ("alice", "bob", "carol"):
            self.simple_user(uid, tasks=2)
        fail_commit_when(self.db, lambda ops, n: any("bob" in ref.path or (data or {}).get("student_id") == "bob"
                                                      for _op, ref, data in ops))
        self.assertEqual(self.apply(), 2)
        self.assertEqual([self.state(u) for u in ("alice", "bob", "carol")], [m.MIGRATED, m.FAILED, m.MIGRATED])
        self.assertFalse([k for k, v in new_docs(self.db).items() if v.get("student_id") == "bob"])

    def test_read_back_mismatch_is_verify_failed(self):
        self.simple_user("alice")
        after_commit(self.db, lambda db: db.store[("tasks", "alicet0")].update(title="tampered"))
        self.assertEqual(self.apply(), 2)
        self.assertEqual(self.state("alice"), m.VERIFY_FAILED)

    def test_legacy_data_changing_during_the_run_is_reported(self):
        self.simple_user("alice")
        after_commit(self.db, lambda db: db.store[("users", "alice", "tasks", "alicet0")].update(progress=60))
        self.assertEqual(self.apply(), 2)
        self.assertEqual(self.state("alice"), m.LEGACY_CHANGED)


class ConflictTests(MigrationCase):
    def test_a_differing_target_blocks_only_that_student(self):
        self.simple_user("alice")
        self.simple_user("bob")
        self.db.store[("tasks", "alicet0")] = {"task_id": "alicet0", "student_id": "alice", "title": "different"}
        before_writes = len(self.db.writes)
        self.assertEqual(self.apply(), 2)
        self.assertEqual(self.state("alice"), m.BLOCKED)
        self.assertEqual(self.state("bob"), m.MIGRATED)
        self.assertEqual(self.db.store[("tasks", "alicet0")]["title"], "different")  # never overwritten
        self.assertFalse([w for w in self.db.writes[before_writes:] if w[1][1].startswith("alice")])
        self.assertNotIn(("students", "alice"), self.db.store)

    def test_a_legacy_change_after_migration_is_a_conflict_not_success(self):
        self.simple_user("alice")
        self.apply()
        self.db.store[("users", "alice", "tasks", "alicet0")]["progress"] = 90
        self.assertEqual(self.go(), 2)
        self.assertEqual(self.state("alice"), m.BLOCKED)

    def test_subject_name_collision_blocks(self):
        self.simple_user("alice", course="Math")
        self.db.store[("subjects", "manual1")] = {"subject_id": "manual1", "student_id": "alice", "subject_name": "math"}
        self.assertEqual(self.apply(), 2)
        self.assertEqual(self.state("alice"), m.BLOCKED)
        self.assertEqual(self.db.writes, [])

    def test_existing_new_layout_data_without_a_marker_blocks(self):
        self.simple_user("alice")
        self.db.store[("tasks", "manual")] = {"task_id": "manual", "student_id": "alice"}
        self.assertEqual(self.apply(), 2)
        self.assertEqual(self.state("alice"), m.BLOCKED)
        self.assertEqual(self.db.writes, [])

    def test_marker_without_all_documents_blocks(self):
        self.simple_user("alice")
        self.apply()
        del self.db.store[("tasks", "alicet0")]
        self.assertEqual(self.apply(), 2)
        self.assertEqual(self.state("alice"), m.BLOCKED)
        self.assertIn("marker_without_all_documents", [b["code"] for b in self.student_report("alice")["blocking"]])


class ReportTests(MigrationCase):
    def test_report_never_contains_titles_course_names_or_emails(self):
        self.simple_user("alice", course="Hidden Course", title="Secret Title")
        put_task(self.db, "alice", "bad", priority="Nope", title="Another Secret")
        self.auth["alice"] = auth_info("alice", display_name="Visible Name")
        put_settings(self.db, "alice", name="Hidden Person")
        self.go()
        text = pathlib.Path(sorted(pathlib.Path(self.tmp.name).glob("*.json"))[-1]).read_text(encoding="utf-8")
        for secret in ("Secret Title", "Another Secret", "Hidden Course", "alice@example.com", "Hidden Person",
                       "Visible Name"):
            self.assertNotIn(secret, text)
        self.assertIn("alice", text)  # the uid itself is in the report

    def test_gitignore_excludes_the_report_folder(self):
        ignore = (pathlib.Path(__file__).resolve().parents[2] / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("/backend/migration_reports/", ignore)


class Phase1CompatibilityTests(ApiTestCase):
    """What the migration writes must work with the Phase 1 API (gate on)."""

    def test_migrated_data_is_served_by_the_phase_1_routes(self):
        db = self.db
        put_task(db, "alice", "t1", title="First", course="Math", progress=100, completedOn="2026-11-15",
                 createdAt="2026-11-01T00:00:00+00:00")
        put_task(db, "alice", "t2", title="Second", course="Math", progress=40, createdAt=..., updatedAt=...)
        put_task(db, "alice", "t3", title="Third", course="", progress=0, deadline="2026-11-10")
        put_settings(db, "alice", name="Ana", leadDays=5)
        put_reminders(db, "alice")
        auth = {"alice": auth_info("alice")}
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            code = m.main(["--apply", "--confirm-project", "proj"], db=db, auth_lookup=auth.__getitem__,
                          enable_v2=False, project_id="proj", report_dir=pathlib.Path(tmp), out=out)
        self.assertEqual(code, 0, out.getvalue())

        tasks = self.call("GET", "/api/tasks").get_json()  # a task without created_at must not crash the sort
        self.assertEqual(sorted(t["title"] for t in tasks), ["First", "Second", "Third"])
        self.assertEqual(self.get_task("t1")["status"], "completed")
        subjects = {s["subject_name"] for s in self.call("GET", "/api/subjects").get_json()}
        self.assertEqual(subjects, {"Math", "Uncategorized"})
        settings = self.call("GET", "/api/settings").get_json()
        self.assertEqual((settings["full_name"], settings["leadDays"]), ("Ana", 5))
        self.assertFalse(self.call("GET", "/api/reminders/preferences").get_json()["deadline"])
        progress = self.call("GET", "/api/progress").get_json()
        self.assertEqual((progress["completed"], progress["overdue"]), (1, 1))
        self.assertEqual(self.call("POST", "/api/tasks/t2/complete").status_code, 200)
        self.assertEqual(self.call("GET", "/api/tasks", "bob").get_json(), [])


if __name__ == "__main__":
    unittest.main()
