"""All Firestore reads and writes live here.

Data layout (approved decisions H1/H2; every document carries its owner, so OWNERSHIP IS CHECKED IN CODE):

    students/{uid}               student_id, full_name, email, created_at,
                                 lead_days, session_minutes, reminder_prefs{deadline, dailySummary,
                                 progressCheckin, quietHours}
    subjects/{subject_id}        subject_id, student_id, subject_name
    tasks/{task_id}              task_id, student_id, subject_id, title, deadline, importance, category,
                                 progress_pct, status, completed_on (only while completed), created_at, updated_at

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
from datetime import datetime, timezone

from errors import ApiError
from validation import STATUS_COMPLETED, STATUS_IN_PROGRESS, STATUS_NOT_STARTED

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
    }


def get_owned_task(db, uid, task_id):
    """(ref, data) when this student owns the task, otherwise None (missing and foreign look the same)."""
    if not valid_id(task_id):
        return None
    ref = _tasks(db).document(task_id)
    snap = ref.get()
    if not snap.exists:
        return None
    data = snap.to_dict() or {}
    if data.get("student_id") != uid:
        return None
    return ref, data


def list_task_docs(db, uid):
    """[(task_id, raw_data), ...] for this student only, in the order tasks were created."""
    items = [(snap.id, snap.to_dict() or {}) for snap in _tasks(db).where("student_id", "==", uid).stream()]
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


def update_task(db, uid, task_id, fields):
    """Edits title/subject/category/deadline/importance/progress. Changing progress NEVER changes status.
    Returns the updated task, or None when this student has no such task."""
    owned = get_owned_task(db, uid, task_id)
    if owned is None:
        return None
    ref, data = owned
    if "subject_id" in fields:
        _require_owned_subject(db, uid, fields["subject_id"])
    if "progress_pct" in fields and data.get("status") == STATUS_COMPLETED and fields["progress_pct"] < 100:
        message = "a completed task stays at 100%. Reopen the task before lowering its progress."
        raise ApiError(422, f"progress_pct: {message}", errors={"progress_pct": message})
    data.update(fields)
    data["task_id"], data["student_id"] = task_id, uid
    data["updated_at"] = _now()
    ref.set(data)
    return public_task(data)


def start_task(db, uid, task_id):
    """not_started -> in_progress (progress unchanged). Already in_progress: no change. Completed: 409."""
    owned = get_owned_task(db, uid, task_id)
    if owned is None:
        return None
    ref, data = owned
    status = data.get("status", STATUS_NOT_STARTED)
    if status == STATUS_COMPLETED:
        raise ApiError(409, "This task is completed. Use reopen to work on it again.")
    if status == STATUS_NOT_STARTED:
        data["status"] = STATUS_IN_PROGRESS
        data["updated_at"] = _now()
        ref.set(data)
    return public_task(data)


def complete_task(db, uid, task_id, today):
    """not_started / in_progress -> completed with progress 100 and completed_on = today.
    Already completed: no change (the original completed_on is kept)."""
    owned = get_owned_task(db, uid, task_id)
    if owned is None:
        return None
    ref, data = owned
    if data.get("status") != STATUS_COMPLETED:
        data["status"] = STATUS_COMPLETED
        data["progress_pct"] = 100
        data["completed_on"] = today.isoformat()
        data["updated_at"] = _now()
        ref.set(data)
    return public_task(data)


def reopen_task(db, uid, task_id):
    """completed -> in_progress, progress unchanged, completed_on removed. Any other status: 409."""
    owned = get_owned_task(db, uid, task_id)
    if owned is None:
        return None
    ref, data = owned
    if data.get("status") != STATUS_COMPLETED:
        raise ApiError(409, "Only a completed task can be reopened.")
    data["status"] = STATUS_IN_PROGRESS
    data.pop("completed_on", None)
    data["updated_at"] = _now()
    ref.set(data)
    return public_task(data)


def delete_task(db, uid, task_id):
    """True if deleted, False when this student has no such task."""
    owned = get_owned_task(db, uid, task_id)
    if owned is None:
        return False
    owned[0].delete()
    return True
