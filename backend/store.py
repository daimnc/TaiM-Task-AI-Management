"""All Firestore reads and writes live here.

Data layout (every path starts with the verified Firebase UID, so students cannot see each other's data):

    users/{uid}/tasks/{taskId}            title, course, category, deadline, priority, progress,
                                          completedOn (set by the server when progress reaches 100),
                                          createdAt, updatedAt
    users/{uid}/preferences/settings      name, program, leadDays, sessionMinutes, weeklySummary
    users/{uid}/preferences/reminders     deadline, dailySummary, progressCheckin, quietHours
"""
import re
from datetime import datetime, timezone

_TASK_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,128}$")


def _user(db, uid):
    return db.collection("users").document(uid)


def _tasks(db, uid):
    return _user(db, uid).collection("tasks")


def _prefs_doc(db, uid, name):
    return _user(db, uid).collection("preferences").document(name)


def _now():
    return datetime.now(timezone.utc).isoformat()


def valid_task_id(task_id):
    return bool(_TASK_ID_RE.match(task_id))


def public_task(task_id, data):
    """Only the fields the frontend expects. Internal fields (completedOn, createdAt...) are never sent."""
    return {
        "id": task_id,
        "title": data.get("title", ""),
        "course": data.get("course", ""),
        "category": data.get("category", "Assignment"),
        "deadline": data.get("deadline", ""),
        "priority": data.get("priority", "Medium"),
        "progress": data.get("progress", 0),
    }


def _track_completion(data, today, was_complete=False):
    """Keep `completedOn` (the day a task reached 100%) accurate, without ever inventing a date.

    - Below 100%: any completion date is removed.
    - At 100% and it was NOT already complete before this save: the task genuinely just finished, so record today.
    - At 100% and it was already complete: leave `completedOn` exactly as stored. If an older task never had one,
      it stays missing (the progress statistics skip tasks with no recorded completion day).
    """
    if data.get("progress") != 100:
        data.pop("completedOn", None)
    elif not was_complete:
        data["completedOn"] = today.isoformat()


# ---- Tasks ----
def list_task_docs(db, uid):
    """[(id, raw_data), ...] in the order tasks were created."""
    items = [(snap.id, snap.to_dict() or {}) for snap in _tasks(db, uid).stream()]
    items.sort(key=lambda item: (item[1].get("createdAt", ""), item[0]))
    return items


def list_tasks(db, uid):
    return [public_task(task_id, data) for task_id, data in list_task_docs(db, uid)]


def create_task(db, uid, fields, today):
    data = dict(fields)
    data["createdAt"] = data["updatedAt"] = _now()
    _track_completion(data, today)  # a task created at 100% is recorded as finished today
    ref = _tasks(db, uid).document()
    ref.set(data)
    return public_task(ref.id, data)


def update_task(db, uid, task_id, fields, today):
    """Returns the updated task, or None when this student has no task with that id."""
    ref = _tasks(db, uid).document(task_id)
    snap = ref.get()
    if not snap.exists:
        return None
    data = snap.to_dict() or {}
    was_complete = data.get("progress") == 100  # check BEFORE applying the changes
    data.update(fields)
    data["updatedAt"] = _now()
    _track_completion(data, today, was_complete)
    ref.set(data)
    return public_task(task_id, data)


def delete_task(db, uid, task_id):
    """Returns True if deleted, False when this student has no task with that id."""
    ref = _tasks(db, uid).document(task_id)
    if not ref.get().exists:
        return False
    ref.delete()
    return True


# ---- Settings and reminder preferences (same pattern) ----
def get_prefs(db, uid, doc_name, defaults):
    snap = _prefs_doc(db, uid, doc_name).get()
    stored = (snap.to_dict() or {}) if snap.exists else {}
    return {key: stored.get(key, default) for key, default in defaults.items()}


def save_prefs(db, uid, doc_name, defaults, changes):
    merged = get_prefs(db, uid, doc_name, defaults)
    merged.update(changes)
    _prefs_doc(db, uid, doc_name).set(merged)
    return merged
