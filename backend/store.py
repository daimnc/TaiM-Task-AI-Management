"""All Firestore reads and writes live here.

Data layout (approved decisions H1/H2; every document carries its owner, so OWNERSHIP IS CHECKED IN CODE):

    students/{uid}               student_id, full_name, email, created_at,
                                 lead_days, session_minutes, reminder_prefs{deadline, dailySummary,
                                 progressCheckin, quietHours}
    subjects/{subject_id}        subject_id, student_id, subject_name
    tasks/{task_id}              task_id, student_id, subject_id, title, deadline, importance, category,
                                 progress_pct, status, completed_on (only while completed), created_at, updated_at,
                                 subtasks (optional list, embedded: subtask_id, title, estimated_minutes, status)

The legacy `users/{uid}/...` data is never read, written or deleted here.

Ownership rules (mandatory):
  * `uid` is always the verified Firebase UID (g.uid). It is a required argument of every function below.
    Nothing from a request body (student_id, task_id, completed_on, created_at...) is ever used as an identity or
    stored as server data.
  * Lists are queried with student_id == uid.
  * A single task or subject is only reachable through get_owned_task / get_owned_subject. A document that is
    missing and a document that belongs to somebody else look identical (None -> 404), so existence is not leaked.
  * A task may only reference a subject the same student owns.
Queries use equality filters only and sort in Python, so no composite Firestore index is needed.
"""
import hashlib
import re
import secrets
from datetime import datetime, timezone

from errors import ApiError
from validation import MAX_SAFE_INTEGER, MAX_SUBTASKS, STATUS_COMPLETED, STATUS_IN_PROGRESS, STATUS_NOT_STARTED

_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,128}$")

REMINDER_DEFAULTS = {"deadline": True, "dailySummary": True, "progressCheckin": False, "quietHours": True}
DEFAULT_LEAD_DAYS = 2
DEFAULT_SESSION_MINUTES = 45


def _now():
    return datetime.now(timezone.utc).isoformat()


def valid_id(value):
    return isinstance(value, str) and bool(_ID_RE.match(value))


def normalize_subject_name(name):
    """Subjects are unique per student ignoring case and extra spaces."""
    return " ".join(name.split()).casefold()


def deterministic_subject_id(uid, subject_name):
    """Same student + same subject name (ignoring case/extra spaces) -> always the same id.
    Used by the Phase 2 migration so re-runs map every legacy subject to the same document."""
    digest = hashlib.sha256(f"{uid}\x1f{normalize_subject_name(subject_name)}".encode("utf-8")).hexdigest()
    return "sub_" + digest[:24]


# ---- Students (profile + settings + reminder preferences live in ONE document, keyed by the verified uid) ----
def _student_ref(db, uid):
    return db.collection("students").document(uid)


def _student_defaults(uid, claims):
    """Used until the student saves settings. Identity fields come from the verified token, never from the request."""
    name = claims.get("name") or (claims.get("email") or "").split("@")[0] or "Student"
    email = claims.get("email")
    return {
        "student_id": uid,
        "full_name": str(name)[:80],
        "email": email if isinstance(email, str) else "",
        "created_at": _now(),
        "lead_days": DEFAULT_LEAD_DAYS,
        "session_minutes": DEFAULT_SESSION_MINUTES,
        "reminder_prefs": dict(REMINDER_DEFAULTS),
    }


def get_student(db, uid, claims):
    """Stored student merged over the defaults. Never writes."""
    snap = _student_ref(db, uid).get()
    stored = (snap.to_dict() or {}) if snap.exists else {}
    data = {**_student_defaults(uid, claims), **stored}
    data["student_id"] = uid
    prefs = dict(REMINDER_DEFAULTS)
    if isinstance(stored.get("reminder_prefs"), dict):
        prefs.update({k: v for k, v in stored["reminder_prefs"].items() if k in REMINDER_DEFAULTS})
    data["reminder_prefs"] = prefs
    return data


def ensure_student(db, uid, claims):
    """Create students/{uid} the first time a student writes data. Returns the student."""
    ref = _student_ref(db, uid)
    if not ref.get().exists:
        ref.set(get_student(db, uid, claims))
    return get_student(db, uid, claims)


def update_student(db, uid, claims, changes=None, reminder_changes=None):
    data = get_student(db, uid, claims)
    data.update(changes or {})
    if reminder_changes:
        data["reminder_prefs"].update(reminder_changes)
    data["student_id"] = uid
    _student_ref(db, uid).set(data)
    return data


# ---- Subjects ----
def _subjects(db):
    return db.collection("subjects")


def public_subject(data):
    return {"subject_id": data.get("subject_id", ""), "subject_name": data.get("subject_name", "")}


def get_owned_subject(db, uid, subject_id):
    """(ref, data) when this student owns the subject, otherwise None (missing and foreign look the same)."""
    if not valid_id(subject_id):
        return None
    ref = _subjects(db).document(subject_id)
    snap = ref.get()
    if not snap.exists:
        return None
    data = snap.to_dict() or {}
    if data.get("student_id") != uid:
        return None
    return ref, data


def _subject_docs(db, uid):
    items = [snap.to_dict() or {} for snap in _subjects(db).where("student_id", "==", uid).stream()]
    items.sort(key=lambda d: (normalize_subject_name(d.get("subject_name", "")), d.get("subject_id", "")))
    return items


def list_subjects(db, uid):
    return [public_subject(d) for d in _subject_docs(db, uid)]


def _name_taken(db, uid, name, except_id=None):
    wanted = normalize_subject_name(name)
    return any(d.get("subject_id") != except_id and normalize_subject_name(d.get("subject_name", "")) == wanted
               for d in _subject_docs(db, uid))


def _duplicate_name_error():
    return ApiError(422, "subject_name: you already have a subject with that name.",
                    errors={"subject_name": "you already have a subject with that name."})


def create_subject(db, uid, fields):
    if _name_taken(db, uid, fields["subject_name"]):
        raise _duplicate_name_error()
    ref = _subjects(db).document()
    data = {"subject_id": ref.id, "student_id": uid, "subject_name": fields["subject_name"]}
    ref.set(data)
    return public_subject(data)


def rename_subject(db, uid, subject_id, fields):
    """Returns the updated subject, or None when this student has no such subject."""
    owned = get_owned_subject(db, uid, subject_id)
    if owned is None:
        return None
    ref, data = owned
    if _name_taken(db, uid, fields["subject_name"], except_id=subject_id):
        raise _duplicate_name_error()
    data["subject_name"] = fields["subject_name"]
    data["subject_id"], data["student_id"] = subject_id, uid
    ref.set(data)
    return public_subject(data)


def delete_subject(db, uid, subject_id):
    """True if deleted, False when this student has no such subject.
    Raises 409 while any of the student's tasks still reference the subject."""
    owned = get_owned_subject(db, uid, subject_id)
    if owned is None:
        return False
    ref, _data = owned
    in_use = list(_tasks(db).where("student_id", "==", uid).where("subject_id", "==", subject_id).limit(1).stream())
    if in_use:
        message = ("This subject still has tasks. Reassign or delete those tasks before deleting the subject.")
        raise ApiError(409, message, errors={"subject_id": message})
    ref.delete()
    return True


# ---- Tasks ----
def _tasks(db):
    return db.collection("tasks")


_SUBTASK_KEYS = {"subtask_id", "title", "estimated_minutes", "status"}


def _percent_done(done, total):
    """Rounded half up with integer arithmetic (same formula as the mock engine)."""
    return (done * 100 + total // 2) // total


def _subtask_list(data):
    """Return validated embedded subtasks; only a genuinely missing field is backward-compatible."""
    if "subtasks" not in data:
        return []

    items = data["subtasks"]
    message = "must be a valid list of stored subtasks."
    if not isinstance(items, list) or len(items) > MAX_SUBTASKS:
        raise ApiError(422, f"subtasks: {message}", errors={"subtasks": message})

    seen_ids = set()
    for index, item in enumerate(items):
        valid = (
            isinstance(item, dict)
            and set(item) == _SUBTASK_KEYS
            and valid_id(item.get("subtask_id"))
            and isinstance(item.get("title"), str)
            and 0 < len(item["title"]) <= 120
            and item["title"] == item["title"].strip()
            and isinstance(item.get("estimated_minutes"), int)
            and not isinstance(item.get("estimated_minutes"), bool)
            and 1 <= item["estimated_minutes"] <= MAX_SAFE_INTEGER
            and item.get("status") in (STATUS_NOT_STARTED, STATUS_COMPLETED)
        )
        if not valid or item["subtask_id"] in seen_ids:
            detail = f"contains an invalid stored item at index {index}."
            raise ApiError(422, f"subtasks: {detail}", errors={"subtasks": detail})
        seen_ids.add(item["subtask_id"])
    return items


def _check_parent_matches_subtasks(data):
    """While subtasks exist they alone decide the parent's progress and status. Tasks without subtasks are skipped."""
    items = data.get("subtasks") if isinstance(data.get("subtasks"), list) else []
    if not items:
        return
    total = len(items)
    done = sum(1 for item in items if item.get("status") == STATUS_COMPLETED)
    problems = []
    progress = data.get("progress_pct")
    if isinstance(progress, bool) or not isinstance(progress, int) or progress != _percent_done(done, total):
        problems.append("progress does not match its subtasks")
    expected = (STATUS_COMPLETED,) if done == total else (STATUS_IN_PROGRESS,) if done else (STATUS_NOT_STARTED, STATUS_IN_PROGRESS)
    if data.get("status") not in expected:
        problems.append("status does not match its subtasks")
    if problems:
        detail = "is inconsistent: " + " and ".join(problems) + "."
        raise ApiError(422, f"subtasks: {detail}", errors={"subtasks": detail})


def _validated_subtasks(data):
    items = _subtask_list(data)
    _check_parent_matches_subtasks(data)
    return items


def public_subtask(data):
    return {
        "subtask_id": data.get("subtask_id", ""),
        "title": data.get("title", ""),
        "estimated_minutes": data.get("estimated_minutes", 30),
        "status": data.get("status", STATUS_NOT_STARTED),
    }


def public_task(data):
    """Only the fields the frontend may see. student_id and internal fields (completed_on, created_at...) stay private."""
    return {
        "task_id": data.get("task_id", ""),
        "subject_id": data.get("subject_id", ""),
        "title": data.get("title", ""),
        "deadline": data.get("deadline", ""),
        "importance": data.get("importance", "medium"),
        "category": data.get("category", "other"),
        "progress_pct": data.get("progress_pct", 0),
        "status": data.get("status", STATUS_NOT_STARTED),
        "subtasks": [public_subtask(item) for item in _subtask_list(data)],
    }


def get_owned_task(db, uid, task_id, transaction=None):
    """(ref, data) when this student owns the task, otherwise None (missing and foreign look the same).
    Pass `transaction` to read inside a Firestore transaction."""
    if not valid_id(task_id):
        return None
    ref = _tasks(db).document(task_id)
    snap = ref.get() if transaction is None else ref.get(transaction=transaction)
    if not snap.exists:
        return None
    data = snap.to_dict() or {}
    if data.get("student_id") != uid:
        return None
    # Validate stored embedded data before any task operation can read or modify it.
    _validated_subtasks(data)
    return ref, data


def list_task_docs(db, uid):
    """[(task_id, raw_data), ...] for this student only, in the order tasks were created."""
    items = []
    for snap in _tasks(db).where("student_id", "==", uid).stream():
        data = snap.to_dict() or {}
        _validated_subtasks(data)  # Do not let list/progress consumers silently ignore corrupted embedded data.
        items.append((snap.id, data))
    items.sort(key=lambda item: (item[1].get("created_at", ""), item[0]))
    return items


def list_tasks(db, uid):
    return [public_task(data) for _task_id, data in list_task_docs(db, uid)]


def _require_owned_subject(db, uid, subject_id):
    if get_owned_subject(db, uid, subject_id) is None:
        message = "must be one of your subjects."
        raise ApiError(422, f"subject_id: {message}", errors={"subject_id": message})


def create_task(db, uid, fields):
    """New tasks always start as not_started with 0% progress, whatever the client sent."""
    _require_owned_subject(db, uid, fields["subject_id"])
    ref = _tasks(db).document()
    now = _now()
    data = {
        "task_id": ref.id,
        "student_id": uid,
        "subject_id": fields["subject_id"],
        "title": fields["title"],
        "deadline": fields["deadline"],
        "importance": fields["importance"],
        "category": fields["category"],
        "progress_pct": 0,
        "status": STATUS_NOT_STARTED,
        "created_at": now,
        "updated_at": now,
    }
    ref.set(data)
    return public_task(data)


CONFLICT_MESSAGE = "This task was changed by another request at the same time. Please try again."


def _is_conflict(db, exc):
    """True when `exc` means a transaction kept conflicting and ran out of attempts."""
    if isinstance(exc, tuple(getattr(db, "conflict_errors", ()))):  # in-memory test database
        return True
    if any(cls.__name__ == "Aborted" for cls in type(exc).__mro__):  # google.api_core.exceptions.Aborted
        return True
    return isinstance(exc, ValueError) and "attempts" in str(exc)  # Firestore: "Failed to commit transaction in 5 attempts."


def _in_transaction(db, work):
    """Run work(txn) atomically. Firestore re-runs `work` when a document it read changed (up to 5 attempts).
    `work` must read first, write only with txn.set / txn.delete, and have no other side effects.
    ApiError raised inside rolls everything back and propagates. Running out of attempts -> 409."""
    runner = getattr(db, "run_in_transaction", None)
    try:
        if runner is not None:  # in-memory test database
            return runner(work)
        from google.cloud.firestore import transactional  # real Firestore
        return transactional(work)(db.transaction())
    except ApiError:
        raise
    except Exception as exc:
        if _is_conflict(db, exc):
            raise ApiError(409, CONFLICT_MESSAGE) from exc
        raise


def update_task(db, uid, task_id, fields):
    """Edits title/subject/category/deadline/importance/progress. Changing progress NEVER changes status.
    Returns the updated task, or None when this student has no such task."""
    def work(txn):
        owned = get_owned_task(db, uid, task_id, txn)
        if owned is None:
            return None
        ref, data = owned
        if "subject_id" in fields:
            _require_owned_subject(db, uid, fields["subject_id"])
        if "progress_pct" in fields and _subtask_list(data):
            message = "is calculated from the subtasks of this task and cannot be set directly."
            raise ApiError(422, f"progress_pct: {message}", errors={"progress_pct": message})
        if "progress_pct" in fields and data.get("status") == STATUS_COMPLETED and fields["progress_pct"] < 100:
            message = "a completed task stays at 100%. Reopen the task before lowering its progress."
            raise ApiError(422, f"progress_pct: {message}", errors={"progress_pct": message})
        data.update(fields)
        data["task_id"], data["student_id"] = task_id, uid
        data["updated_at"] = _now()
        txn.set(ref, data)
        return public_task(data)
    return _in_transaction(db, work)


def start_task(db, uid, task_id):
    """not_started -> in_progress (progress unchanged). Already in_progress: no change. Completed: 409."""
    def work(txn):
        owned = get_owned_task(db, uid, task_id, txn)
        if owned is None:
            return None
        ref, data = owned
        status = data.get("status", STATUS_NOT_STARTED)
        if status == STATUS_COMPLETED:
            raise ApiError(409, "This task is completed. Use reopen to work on it again.")
        if status == STATUS_NOT_STARTED:
            data["status"] = STATUS_IN_PROGRESS
            data["updated_at"] = _now()
            txn.set(ref, data)
        return public_task(data)
    return _in_transaction(db, work)


def complete_task(db, uid, task_id, today):
    """not_started / in_progress -> completed with progress 100 and completed_on = today.
    Already completed: no change (the original completed_on is kept).
    A task that has subtasks is completed only through its subtasks: 409."""
    def work(txn):
        owned = get_owned_task(db, uid, task_id, txn)
        if owned is None:
            return None
        ref, data = owned
        if _subtask_list(data):
            raise ApiError(409, "This task has subtasks. Complete or reopen its subtasks instead.")
        if data.get("status") != STATUS_COMPLETED:
            data["status"] = STATUS_COMPLETED
            data["progress_pct"] = 100
            data["completed_on"] = today.isoformat()
            data["updated_at"] = _now()
            txn.set(ref, data)
        return public_task(data)
    return _in_transaction(db, work)


def reopen_task(db, uid, task_id):
    """completed -> in_progress, progress unchanged, completed_on removed. Any other status: 409.
    A task that has subtasks is reopened only by reopening one of its subtasks: 409."""
    def work(txn):
        owned = get_owned_task(db, uid, task_id, txn)
        if owned is None:
            return None
        ref, data = owned
        if _subtask_list(data):
            raise ApiError(409, "This task has subtasks. Complete or reopen its subtasks instead.")
        if data.get("status") != STATUS_COMPLETED:
            raise ApiError(409, "Only a completed task can be reopened.")
        data["status"] = STATUS_IN_PROGRESS
        data.pop("completed_on", None)
        data["updated_at"] = _now()
        txn.set(ref, data)
        return public_task(data)
    return _in_transaction(db, work)


def delete_task(db, uid, task_id):
    """True if deleted, False when this student has no such task."""
    owned = get_owned_task(db, uid, task_id)
    if owned is None:
        return False
    owned[0].delete()
    return True


# ---- Subtasks (embedded in the parent task document; the server alone decides parent progress and status) ----
def _recalculate_from_subtasks(data, today):
    """Derive the parent's progress and status from its subtasks. No subtasks: nothing is touched (manual rules).

    progress_pct = done * 100 / total, rounded half up with integer arithmetic (same formula as the mock engine).
    All done        -> completed (completed_on = today, kept if it was already completed)
    Some done       -> in_progress
    None done       -> not_started stays not_started, in_progress stays in_progress, completed becomes in_progress
    Leaving "completed" clears completed_on."""
    items = _subtask_list(data)
    if not items:
        return
    total = len(items)
    done = sum(1 for item in items if item.get("status") == STATUS_COMPLETED)
    previous = data.get("status", STATUS_NOT_STARTED)
    data["progress_pct"] = _percent_done(done, total)
    if done == total:
        data["status"] = STATUS_COMPLETED
        if previous != STATUS_COMPLETED or not data.get("completed_on"):
            data["completed_on"] = today.isoformat()
    else:
        data.pop("completed_on", None)
        if previous == STATUS_COMPLETED or done > 0:
            data["status"] = STATUS_IN_PROGRESS


def _save_subtasks(txn, ref, data, items, today):
    data["subtasks"] = items
    _recalculate_from_subtasks(data, today)
    _check_parent_matches_subtasks(data)  # final invariant: never persist a parent that disagrees with its subtasks
    data["updated_at"] = _now()
    txn.set(ref, data)
    return public_task(data)


def _subtask_not_found():
    return ApiError(404, "Subtask not found.")


def _find_subtask(data, subtask_id):
    if not valid_id(subtask_id):
        raise _subtask_not_found()
    items = list(_subtask_list(data))
    for index, item in enumerate(items):
        if item.get("subtask_id") == subtask_id:
            return items, index
    raise _subtask_not_found()


def add_subtasks(db, uid, task_id, items, today):
    """Append already-validated subtasks (each {title, estimated_minutes}) in ONE write: all or nothing.
    Existing subtasks are never replaced. Returns the updated parent task, or None when this student has no such task."""
    def work(txn):
        owned = get_owned_task(db, uid, task_id, txn)
        if owned is None:
            return None
        ref, data = owned
        existing = list(_subtask_list(data))
        if len(existing) + len(items) > MAX_SUBTASKS:
            message = f"a task can have at most {MAX_SUBTASKS} subtasks (it already has {len(existing)})."
            raise ApiError(422, f"subtasks: {message}", errors={"subtasks": message})
        taken = {item.get("subtask_id") for item in existing if isinstance(item, dict)}
        created = []
        for item in items:
            subtask_id = secrets.token_hex(10)
            while subtask_id in taken:
                subtask_id = secrets.token_hex(10)
            taken.add(subtask_id)
            created.append({"subtask_id": subtask_id, "title": item["title"],
                            "estimated_minutes": item["estimated_minutes"], "status": STATUS_NOT_STARTED})
        return _save_subtasks(txn, ref, data, existing + created, today)
    return _in_transaction(db, work)


def complete_subtask(db, uid, task_id, subtask_id, today):
    """Marks one subtask completed (already completed: no change). Returns the updated parent, or None (no such task).
    Raises 404 for a missing subtask."""
    def work(txn):
        owned = get_owned_task(db, uid, task_id, txn)
        if owned is None:
            return None
        ref, data = owned
        items, index = _find_subtask(data, subtask_id)
        if items[index].get("status") == STATUS_COMPLETED:
            return public_task(data)
        items[index] = {**items[index], "status": STATUS_COMPLETED}
        return _save_subtasks(txn, ref, data, items, today)
    return _in_transaction(db, work)


def reopen_subtask(db, uid, task_id, subtask_id, today):
    """completed -> not_started. Any other status: 409. A completed parent becomes in_progress (completed_on cleared)."""
    def work(txn):
        owned = get_owned_task(db, uid, task_id, txn)
        if owned is None:
            return None
        ref, data = owned
        items, index = _find_subtask(data, subtask_id)
        if items[index].get("status") != STATUS_COMPLETED:
            raise ApiError(409, "Only a completed subtask can be reopened.")
        items[index] = {**items[index], "status": STATUS_NOT_STARTED}
        return _save_subtasks(txn, ref, data, items, today)
    return _in_transaction(db, work)


def delete_subtask(db, uid, task_id, subtask_id, today):
    """Removes one subtask. Remaining subtasks still drive the parent. Deleting the LAST one leaves the parent's
    progress and status as they were and hands control back to the manual rules. Returns the parent or None."""
    def work(txn):
        owned = get_owned_task(db, uid, task_id, txn)
        if owned is None:
            return None
        ref, data = owned
        items, index = _find_subtask(data, subtask_id)
        del items[index]
        return _save_subtasks(txn, ref, data, items, today)
    return _in_transaction(db, work)
