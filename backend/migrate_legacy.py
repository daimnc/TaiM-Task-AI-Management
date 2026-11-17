"""Phase 2: one-way migration of legacy users/{uid}/... data into students / subjects / tasks.

Run from the backend folder:
    python migrate_legacy.py                                     dry-run (default): reads only, writes nothing
    python migrate_legacy.py --apply --confirm-project <id>      writes (create-only) to the new collections
    python migrate_legacy.py --only-uid <uid> [--only-uid ...]   limit processing to some students

Safeguards: legacy data is only ever READ. Target writes are create-only with deterministic ids, so nothing is
ever overwritten. --apply is refused while TAIM_ENABLE_V2 is on, and this script never changes that setting.

Exit codes: 0 every discovered student is MIGRATED / ALREADY_MIGRATED / NO_DATA; 1 usage, configuration or
safeguard error (nothing processed); 2 at least one unresolved problem (overrides 3); 3 no problems but some
students are still pending (every clean dry-run before --apply, and any --only-uid run).

Atomicity: a student is fully validated and every target pre-read before the first write. A student with
<= 400 documents is written in ONE batch (all or nothing). A larger student is written in several batches,
children first and the students/{uid} marker last in its own batch; that case is NOT atomic across batches, but
a partial state is detected (PARTIAL) and a re-run with --apply resumes it safely.
"""
import argparse
import hashlib
import json
import sys
from collections import Counter, namedtuple
from datetime import datetime, timedelta, timezone

import store
from config import Config
from validation import LEAD_DAYS, SESSION_MINUTES, STATUS_COMPLETED, STATUS_IN_PROGRESS, STATUS_NOT_STARTED
from validation import _date, _progress, _text  # the same field rules Phase 1 applies to new data

MAX_BATCH_OPS = 400
UNCATEGORIZED = "Uncategorized"

PRIORITY_MAP = {"High": "high", "Medium": "medium", "Low": "low"}
CATEGORY_MAP = {"Assignment": "assignment", "Research": "research", "Project": "project", "Examination": "exam"}

# ---- student states ----
MIGRATED, ALREADY_MIGRATED, NO_DATA = "MIGRATED", "ALREADY_MIGRATED", "NO_DATA"
WOULD_MIGRATE, NOT_SELECTED = "WOULD_MIGRATE", "NOT_SELECTED"
ORPHANED, BLOCKED, PARTIAL = "ORPHANED", "BLOCKED", "PARTIAL"
FAILED, VERIFY_FAILED, LEGACY_CHANGED = "FAILED", "VERIFY_FAILED", "LEGACY_CHANGED"
OK_STATES = {MIGRATED, ALREADY_MIGRATED, NO_DATA}
PENDING_STATES = {WOULD_MIGRATE, NOT_SELECTED}
PROBLEM_STATES = {ORPHANED, BLOCKED, PARTIAL, FAILED, VERIFY_FAILED, LEGACY_CHANGED}

EXIT_OK, EXIT_USAGE, EXIT_PROBLEMS, EXIT_PENDING = 0, 1, 2, 3
EXIT_MEANING = {
    EXIT_OK: "every discovered student is migrated, already migrated or has no legacy data",
    EXIT_USAGE: "usage, configuration or safeguard error; nothing was processed",
    EXIT_PROBLEMS: "at least one student has an unresolved problem",
    EXIT_PENDING: "no problems, but some students are still pending",
}

AuthInfo = namedtuple("AuthInfo", "email display_name created_at_ms")


class AuthNotFound(Exception):
    """No Firebase Auth user exists for this uid."""


class UsageError(Exception):
    pass


# =====================================================================================================
# Firebase Auth (injected in tests)
# =====================================================================================================
def firebase_auth_lookup(uid):
    from firebase_admin import auth
    try:
        record = auth.get_user(uid)
    except auth.UserNotFoundError:
        raise AuthNotFound(uid)
    meta = getattr(record, "user_metadata", None)
    return AuthInfo(record.email, record.display_name, getattr(meta, "creation_timestamp", None))


def _auth_created_at(info):
    """ISO UTC text from the Auth creation time (milliseconds), or None when it is missing or unusable."""
    ms = info.created_at_ms
    if isinstance(ms, bool) or not isinstance(ms, (int, float)) or ms <= 0:
        return None
    return (datetime.fromtimestamp(0, timezone.utc) + timedelta(milliseconds=int(ms))).isoformat()


# =====================================================================================================
# Findings
# =====================================================================================================
class Findings:
    """Collects what the report shows. Never stores titles, course text, names or emails: only ids, field names,
    reasons and counts."""

    def __init__(self):
        self.counts = Counter()
        self.invalid = []   # [{"doc", "field", "reason"}]
        self.blocking = []  # [{"code", "doc"?}] other blocking reasons (conflicts, missing Auth time...)

    def note(self, code, n=1):
        self.counts[code] += n

    def bad(self, doc, field, reason):
        self.invalid.append({"doc": doc, "field": field, "reason": reason})

    def block(self, code, doc=None):
        self.blocking.append({"code": code, **({"doc": doc} if doc else {})})

    @property
    def blocked(self):
        return bool(self.invalid or self.blocking)


# =====================================================================================================
# Reading legacy data (read-only)
# =====================================================================================================
def read_legacy(user_ref):
    """Everything the legacy code ever wrote for one user: tasks, preferences/settings, preferences/reminders."""
    tasks = {snap.id: snap.to_dict() for snap in user_ref.collection("tasks").stream()}
    prefs = user_ref.collection("preferences")
    settings, reminders = prefs.document("settings").get(), prefs.document("reminders").get()
    return {
        "tasks": tasks,
        "settings": (settings.to_dict() or {}) if settings.exists else None,
        "reminders": (reminders.to_dict() or {}) if reminders.exists else None,
    }


def fingerprint(legacy):
    text = json.dumps(legacy, sort_keys=True, default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def has_legacy_data(legacy):
    return bool(legacy["tasks"]) or legacy["settings"] is not None or legacy["reminders"] is not None


# =====================================================================================================
# Mapping legacy -> new documents
# =====================================================================================================
def _stamp(raw, key, field, doc, findings):
    """Optional legacy timestamp text. Missing/null/empty -> omitted and reported. Never fabricated."""
    value = raw.get(key)
    if value is None or value == "":
        findings.note(f"missing:task_{field}")
        return None
    if not isinstance(value, str):
        findings.bad(doc, key, "must be text.")
        return None
    return value


def _map_task(uid, task_id, raw, findings):
    """Returns (doc, course, sort_key); doc is None when the record is invalid (reasons go to findings)."""
    ref = f"tasks/{task_id}"
    before = len(findings.invalid)
    if not store.valid_id(task_id):
        findings.bad(ref, "id", "not a valid document id.")
    if not isinstance(raw, dict):
        findings.bad(ref, "document", "is empty or not a map.")
        return None, "", ("", task_id)

    def required(field, convert):
        value = raw.get(field)
        if value is None:
            findings.bad(ref, field, "is required.")
            return None
        try:
            return convert(value)
        except ValueError as problem:
            findings.bad(ref, field, str(problem))
            return None

    def mapped(table):
        def convert(value):
            if not isinstance(value, str) or value not in table:
                raise ValueError("must be one of: " + ", ".join(table) + ".")
            return table[value]
        return convert

    title = required("title", _text(120))
    deadline = required("deadline", _date)
    importance = required("priority", mapped(PRIORITY_MAP))
    category = required("category", mapped(CATEGORY_MAP))
    progress = required("progress", _progress)
    course = ""
    if raw.get("course") is not None:
        try:
            course = _text(100, allow_empty=True)(raw["course"])
        except ValueError as problem:
            findings.bad(ref, "course", str(problem))

    created_at = _stamp(raw, "createdAt", "created_at", ref, findings)
    updated_at = _stamp(raw, "updatedAt", "updated_at", ref, findings)

    completed_on = raw.get("completedOn")
    completed_on = None if completed_on in (None, "") else completed_on
    if completed_on is not None:
        try:
            completed_on = _date(completed_on)
        except ValueError as problem:
            findings.bad(ref, "completedOn", str(problem))
            completed_on = None
    if progress is not None and progress < 100 and raw.get("completedOn") not in (None, ""):
        findings.bad(ref, "completedOn", "is set although progress is below 100 (legacy code cannot produce this).")

    sort_key = (raw.get("createdAt") if isinstance(raw.get("createdAt"), str) else "", task_id)
    if len(findings.invalid) > before:
        return None, course, sort_key

    if progress == 100:
        status = STATUS_COMPLETED
        if completed_on is None:
            findings.note("completed_without_date")
    else:
        status = STATUS_NOT_STARTED if progress == 0 else STATUS_IN_PROGRESS
        findings.note("status_derived")
    doc = {"task_id": task_id, "student_id": uid, "subject_id": None, "title": title, "deadline": deadline,
           "importance": importance, "category": category, "progress_pct": progress, "status": status}
    if status == STATUS_COMPLETED and completed_on is not None:
        doc["completed_on"] = completed_on
    if created_at is not None:
        doc["created_at"] = created_at
    if updated_at is not None:
        doc["updated_at"] = updated_at
    return doc, course, sort_key


def _choice(raw, key, allowed, default, doc, findings):
    if raw is None or raw.get(key) is None:
        return default
    value = raw[key]
    if isinstance(value, bool) or not isinstance(value, int) or value not in allowed:
        findings.bad(doc, key, "must be one of: " + ", ".join(str(a) for a in allowed) + ".")
        return default
    return value


def _map_student(uid, auth, legacy, findings, info):
    settings, reminders = legacy["settings"], legacy["reminders"]
    created_at = _auth_created_at(auth)
    if created_at is None:
        findings.block("missing_auth_created_at")
    info["created_at_source"] = "auth" if created_at else "missing"

    name, info["name_source"] = None, None
    if settings is not None and settings.get("name") is not None:
        try:
            name = _text(80, allow_empty=True)(settings["name"])
            info["name_source"] = "settings"
        except ValueError as problem:
            findings.bad("preferences/settings", "name", str(problem))
    if not name and not findings.invalid:
        email_prefix = (auth.email or "").split("@")[0] if isinstance(auth.email, str) else ""
        if isinstance(auth.display_name, str) and auth.display_name.strip():
            name, info["name_source"] = auth.display_name, "auth_display_name"
        elif email_prefix:
            name, info["name_source"] = email_prefix, "auth_email_prefix"
        else:
            name, info["name_source"] = "Student", "default"
        name = name[:80]

    email = auth.email if isinstance(auth.email, str) else ""
    info["email_source"] = "auth" if email else "missing"
    if not email:
        findings.note("missing:student_email")

    lead = _choice(settings, "leadDays", LEAD_DAYS, store.DEFAULT_LEAD_DAYS, "preferences/settings", findings)
    session = _choice(settings, "sessionMinutes", SESSION_MINUTES, store.DEFAULT_SESSION_MINUTES,
                      "preferences/settings", findings)
    prefs = dict(store.REMINDER_DEFAULTS)
    for key in prefs:
        if reminders is not None and reminders.get(key) is not None:
            if not isinstance(reminders[key], bool):
                findings.bad("preferences/reminders", key, "must be true or false.")
            else:
                prefs[key] = reminders[key]

    for key in ("program", "weeklySummary"):
        if settings is not None and key in settings:
            findings.note(f"dropped:{key}")
    known = {"settings": {"name", "program", "leadDays", "sessionMinutes", "weeklySummary"},
             "reminders": set(store.REMINDER_DEFAULTS)}
    for label, raw in (("settings", settings), ("reminders", reminders)):
        if raw:
            findings.note("ignored_unknown_fields", len(set(raw) - known[label]))

    doc = {"student_id": uid, "full_name": name, "email": email, "created_at": created_at, "lead_days": lead,
           "session_minutes": session, "reminder_prefs": prefs}
    return doc


def build_plan(uid, auth, legacy, findings, info):
    """Returns {"subjects": {id: doc}, "tasks": {id: doc}, "student": doc}; fully validated or findings.blocked."""
    mapped = []
    for task_id in sorted(legacy["tasks"]):
        doc, course, sort_key = _map_task(uid, task_id, legacy["tasks"][task_id], findings)
        mapped.append((sort_key, doc, course))
    mapped.sort(key=lambda item: item[0])

    names = {}  # normalized name -> first-seen spelling (oldest createdAt, then id: stable across re-runs)
    spellings = set()
    for _key, doc, course in mapped:
        name = course or UNCATEGORIZED
        norm = store.normalize_subject_name(name)
        if norm in names and names[norm] != name:
            spellings.add(norm)
        names.setdefault(norm, name)
    if spellings:
        findings.note("subject_spellings_merged", len(spellings))

    subjects, tasks = {}, {}
    for norm, name in names.items():
        sid = store.deterministic_subject_id(uid, name)
        subjects[sid] = {"subject_id": sid, "student_id": uid, "subject_name": name}
    for _key, doc, course in mapped:
        if doc is not None:
            doc["subject_id"] = store.deterministic_subject_id(uid, course or UNCATEGORIZED)
            tasks[doc["task_id"]] = doc
    return {"subjects": subjects, "tasks": tasks, "student": _map_student(uid, auth, legacy, findings, info)}


# =====================================================================================================
# Targets: pre-read, classify, write, verify
# =====================================================================================================
def _targets(db, uid, plan):
    """[(path, ref, expected)] in write order: subjects, tasks, then the students marker."""
    items = [(f"subjects/{i}", db.collection("subjects").document(i), d) for i, d in sorted(plan["subjects"].items())]
    items += [(f"tasks/{i}", db.collection("tasks").document(i), d) for i, d in sorted(plan["tasks"].items())]
    items.append((f"students/{uid}", db.collection("students").document(uid), plan["student"]))
    return items


def _read_targets(targets):
    """path -> 'absent' | 'identical' | 'differs'."""
    states = {}
    for path, ref, expected in targets:
        snap = ref.get()
        states[path] = "absent" if not snap.exists else ("identical" if snap.to_dict() == expected else "differs")
    return states


def _check_extras(db, uid, plan, marker_state, findings):
    """Documents that already belong to this student in the new collections but are not part of the plan."""
    planned_subject_ids, planned_names = set(plan["subjects"]), {store.normalize_subject_name(s["subject_name"])
                                                                for s in plan["subjects"].values()}
    extra_subjects = [(s.id, s.to_dict() or {}) for s in db.collection("subjects").where("student_id", "==", uid)
                      .stream() if s.id not in planned_subject_ids]
    extra_tasks = [t.id for t in db.collection("tasks").where("student_id", "==", uid).stream()
                   if t.id not in plan["tasks"]]
    findings.note("extra_target_subjects", len(extra_subjects))
    findings.note("extra_target_tasks", len(extra_tasks))
    for sid, data in extra_subjects:
        if store.normalize_subject_name(str(data.get("subject_name", ""))) in planned_names:
            findings.block("subject_name_collision", f"subjects/{sid}")
    if marker_state == "absent" and (extra_subjects or extra_tasks):
        findings.block("unexpected_target_documents_without_marker")


def _batches(missing):
    """missing = [(ref, data)] in write order, marker last. <= 400 ops: one atomic batch. Otherwise children in
    batches of 400 and the marker alone in the final batch."""
    if len(missing) <= MAX_BATCH_OPS:
        return [missing] if missing else []
    children, marker = missing[:-1], missing[-1:]
    return [children[i:i + MAX_BATCH_OPS] for i in range(0, len(children), MAX_BATCH_OPS)] + [marker]


def _snapshot_equal(targets):
    """Read-back verification: every planned document exists and equals what was planned."""
    return all(snap.exists and snap.to_dict() == expected
               for snap, expected in ((ref.get(), expected) for _path, ref, expected in targets))


# =====================================================================================================
# One student
# =====================================================================================================
def process_student(db, auth_lookup, uid, apply):
    findings, info = Findings(), {}
    result = {"uid": uid, "state": None, "info": info}

    def finish(state):
        result.update(state=state, findings=dict(sorted(findings.counts.items())), invalid=findings.invalid,
                      blocking=findings.blocking)
        return result

    try:
        try:
            auth = auth_lookup(uid)
        except AuthNotFound:
            findings.block("no_auth_record")
            return finish(ORPHANED)

        user_ref = db.collection("users").document(uid)
        legacy = read_legacy(user_ref)
        before = fingerprint(legacy)
        if not has_legacy_data(legacy):
            return finish(NO_DATA)
        info.update(legacy_tasks=len(legacy["tasks"]))

        plan = build_plan(uid, auth, legacy, findings, info)
        info.update(subjects_planned=len(plan["subjects"]), tasks_planned=len(plan["tasks"]))
        if findings.blocked:
            return finish(BLOCKED)

        targets = _targets(db, uid, plan)
        states = _read_targets(targets)
        marker_state = states[f"students/{uid}"]
        for path, state in states.items():
            if state == "differs":
                findings.block("conflicting_target_document", path)
        children_absent = [p for p, s in states.items() if s == "absent" and p != f"students/{uid}"]
        if marker_state != "absent" and children_absent:
            findings.block("marker_without_all_documents")
        _check_extras(db, uid, plan, marker_state, findings)
        if findings.blocked:
            return finish(BLOCKED)

        missing = [(ref, data) for path, ref, data in targets if states[path] == "absent"]
        info.update(docs_total=len(targets), docs_to_write=len(missing), docs_identical=len(targets) - len(missing))
        if not missing:
            return finish(ALREADY_MIGRATED)
        was_partial = marker_state == "absent" and len(missing) < len(targets)
        if not apply:
            return finish(PARTIAL if was_partial else WOULD_MIGRATE)

        if fingerprint(read_legacy(user_ref)) != before:
            findings.block("legacy_changed_before_write")
            return finish(LEGACY_CHANGED)

        batches = _batches(missing)
        info["batches"] = len(batches)
        committed = 0
        for ops in batches:
            try:
                batch = db.batch()
                for ref, data in ops:
                    batch.create(ref, data)
                batch.commit()
            except Exception as error:
                findings.block(f"write_failed:{type(error).__name__}")
                info["batches_committed"] = committed
                return finish(PARTIAL if (committed or was_partial) else FAILED)
            committed += 1

        if not _snapshot_equal(targets):
            findings.block("read_back_mismatch")
            return finish(VERIFY_FAILED)
        if fingerprint(read_legacy(user_ref)) != before:
            findings.block("legacy_changed_during_run")
            return finish(LEGACY_CHANGED)
        info["resumed"] = was_partial
        return finish(MIGRATED)
    except Exception as error:  # per-student error boundary: one student never stops the others
        findings.block(f"error:{type(error).__name__}")
        return finish(FAILED)


# =====================================================================================================
# The run, exit code, report
# =====================================================================================================
def exit_code_for(states):
    if any(s in PROBLEM_STATES for s in states):
        return EXIT_PROBLEMS
    if any(s in PENDING_STATES for s in states):
        return EXIT_PENDING
    return EXIT_OK


def run(db, auth_lookup, apply, only_uids=None):
    uids = sorted({ref.id for ref in db.collection("users").list_documents()})
    selected = set(only_uids) if only_uids else None
    if selected is not None and not selected <= set(uids):
        raise UsageError("--only-uid: no legacy users/ document for: " + ", ".join(sorted(selected - set(uids))))
    students = []
    for uid in uids:
        if selected is not None and uid not in selected:
            students.append({"uid": uid, "state": NOT_SELECTED, "info": {}, "findings": {}, "invalid": [],
                             "blocking": []})
        else:
            students.append(process_student(db, auth_lookup, uid, apply))
    states = [s["state"] for s in students]
    warnings = [] if students else ["No legacy students were discovered (nothing to migrate)."]
    return {"mode": "apply" if apply else "dry-run", "students": students, "warnings": warnings,
            "summary": dict(sorted(Counter(states).items())), "exit_code": exit_code_for(states)}


def write_report(report, report_dir):
    report_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    path = report_dir / f"migration-{stamp}-{report['mode']}.json"
    path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    return path


# =====================================================================================================
# Command line
# =====================================================================================================
class _Parser(argparse.ArgumentParser):
    def error(self, message):  # argparse would exit with 2, which this script reserves for "unresolved problems"
        raise UsageError(message)


def _parse(argv):
    parser = _Parser(prog="migrate_legacy.py", description=__doc__.split("\n\n")[0])
    parser.add_argument("--apply", action="store_true", help="write to the new collections (default: dry-run)")
    parser.add_argument("--confirm-project", metavar="PROJECT_ID", help="required with --apply; must equal FIREBASE_PROJECT_ID")
    parser.add_argument("--only-uid", action="append", metavar="UID", help="process only this student (repeatable)")
    return parser.parse_args(argv)


def main(argv=None, *, db=None, auth_lookup=None, enable_v2=None, project_id=None, report_dir=None, out=None):
    """The keyword arguments exist only so the tests can inject a fake database; normal use passes none."""
    out = out or sys.stdout

    def say(text):
        print(text, file=out)

    try:
        args = _parse(argv)
        enable_v2 = Config.ENABLE_V2 if enable_v2 is None else enable_v2
        project_id = Config.FIREBASE_PROJECT_ID if project_id is None else project_id
        if args.apply:
            if enable_v2:
                raise UsageError("--apply is refused while TAIM_ENABLE_V2 is on. Turn it off first; this script never changes it.")
            if not args.confirm_project:
                raise UsageError("--apply requires --confirm-project <FIREBASE_PROJECT_ID>.")
            if not project_id:
                raise UsageError("FIREBASE_PROJECT_ID is not configured, so --apply cannot be confirmed.")
            if args.confirm_project != project_id:
                raise UsageError("--confirm-project does not match FIREBASE_PROJECT_ID.")
        for uid in args.only_uid or []:
            if not uid or "/" in uid:
                raise UsageError(f"--only-uid: invalid uid {uid!r}.")
        if db is None:
            from firebase import initialize_firebase
            db = initialize_firebase()
            if db is None:
                raise UsageError("Firestore is not available. Check FIREBASE_PROJECT_ID and keys/serviceAccount.json.")
        client_project = getattr(db, "project", None)
        if args.apply and isinstance(client_project, str) and client_project != args.confirm_project:
            raise UsageError("--confirm-project does not match the connected Firestore project.")
        report = run(db, auth_lookup or firebase_auth_lookup, args.apply, args.only_uid)
    except UsageError as problem:
        say(f"Error: {problem}")
        return EXIT_USAGE

    report["project_id"] = project_id or None
    for warning in report["warnings"]:
        say(f"Warning: {warning}")
    say(f"Mode: {report['mode']}" + ("" if args.apply else "  (no writes were made)"))
    for student in report["students"]:
        say(f"  {student['uid']}: {student['state']}")
    say("Summary: " + (", ".join(f"{k}={v}" for k, v in report["summary"].items()) or "no students"))
    try:
        directory = report_dir if report_dir is not None else Config.BASE_DIR / "migration_reports"
        say(f"Report: {write_report(report, directory)}")
    except OSError as problem:
        say(f"Warning: the report file could not be written ({type(problem).__name__}).")
    say(f"Exit code {report['exit_code']}: {EXIT_MEANING[report['exit_code']]}.")
    return report["exit_code"]


if __name__ == "__main__":
    sys.exit(main())
