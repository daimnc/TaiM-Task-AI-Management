"""All /api routes except /api/health (which stays in app.py). Every route here requires a verified Firebase token.

The student is always g.uid (from the verified token). No route reads a student id from the URL, query or body.
Routes that use the students/subjects/tasks data are also behind the TAIM_ENABLE_V2 gate (default: off).
"""
from functools import wraps

from flask import Blueprint, current_app, g, jsonify

import dates
import fallback_ai
import store
from errors import ApiError
from progress import build_progress
from security import require_auth
from validation import (CHAT_RULES, PLAN_RULES, REMINDER_RULES, SETTINGS_RULES, SUBJECT_RULES, TASK_CREATE_FORBIDDEN,
                        TASK_RULES, TASK_UPDATE_FORBIDDEN, TASK_UPDATE_RULES, read_json_object, reject_fields,
                        validate, validate_subtask_batch)

api = Blueprint("api", __name__, url_prefix="/api")


def _db():
    return current_app.extensions["taim_db"]


def require_v2(view):
    """Use AFTER @require_auth. While the gate is off (the default) the new data routes answer 503, so the app can
    never touch the new collections before the legacy data has been migrated and verified."""
    @wraps(view)
    def wrapper(*args, **kwargs):
        if not current_app.config.get("ENABLE_V2"):
            raise ApiError(503, "The new data layout is not enabled yet. Migration must be completed and verified first.")
        return view(*args, **kwargs)
    return wrapper


def _or_404(value, what):
    if value is None:
        raise ApiError(404, f"{what} not found.")
    return value


# ---- Subjects ----
@api.get("/subjects")
@require_auth
@require_v2
def list_subjects():
    return jsonify(store.list_subjects(_db(), g.uid))


@api.post("/subjects")
@require_auth
@require_v2
def create_subject():
    fields = validate(read_json_object(), SUBJECT_RULES)
    store.ensure_student(_db(), g.uid, g.user_claims)
    return jsonify(store.create_subject(_db(), g.uid, fields)), 201


@api.patch("/subjects/<subject_id>")
@require_auth
@require_v2
def rename_subject(subject_id):
    fields = validate(read_json_object(), SUBJECT_RULES, partial=True)
    return jsonify(_or_404(store.rename_subject(_db(), g.uid, subject_id, fields), "Subject"))


@api.delete("/subjects/<subject_id>")
@require_auth
@require_v2
def delete_subject(subject_id):
    _or_404(store.delete_subject(_db(), g.uid, subject_id) or None, "Subject")
    return "", 204


# ---- Tasks ----
@api.get("/tasks")
@require_auth
@require_v2
def list_tasks():
    return jsonify(store.list_tasks(_db(), g.uid))


@api.post("/tasks")
@require_auth
@require_v2
def create_task():
    body = read_json_object()
    reject_fields(body, TASK_CREATE_FORBIDDEN)
    fields = validate(body, TASK_RULES)
    store.ensure_student(_db(), g.uid, g.user_claims)
    return jsonify(store.create_task(_db(), g.uid, fields)), 201


@api.patch("/tasks/<task_id>")
@require_auth
@require_v2
def update_task(task_id):
    body = read_json_object()
    reject_fields(body, TASK_UPDATE_FORBIDDEN)
    fields = validate(body, TASK_UPDATE_RULES, partial=True)
    return jsonify(_or_404(store.update_task(_db(), g.uid, task_id, fields), "Task"))


@api.post("/tasks/<task_id>/start")
@require_auth
@require_v2
def start_task(task_id):
    return jsonify(_or_404(store.start_task(_db(), g.uid, task_id), "Task"))


@api.post("/tasks/<task_id>/complete")
@require_auth
@require_v2
def complete_task(task_id):
    return jsonify(_or_404(store.complete_task(_db(), g.uid, task_id, dates.today()), "Task"))


@api.post("/tasks/<task_id>/reopen")
@require_auth
@require_v2
def reopen_task(task_id):
    return jsonify(_or_404(store.reopen_task(_db(), g.uid, task_id), "Task"))


@api.delete("/tasks/<task_id>")
@require_auth
@require_v2
def delete_task(task_id):
    _or_404(store.delete_task(_db(), g.uid, task_id) or None, "Task")
    return "", 204


# ---- Subtasks (embedded in the parent task; every route answers with the updated PARENT task) ----
@api.post("/tasks/<task_id>/subtasks")
@require_auth
@require_v2
def add_subtasks(task_id):
    items = validate_subtask_batch(read_json_object())  # the whole batch is checked before anything is saved
    return jsonify(_or_404(store.add_subtasks(_db(), g.uid, task_id, items, dates.today()), "Task")), 201


@api.post("/tasks/<task_id>/subtasks/<subtask_id>/complete")
@require_auth
@require_v2
def complete_subtask(task_id, subtask_id):
    return jsonify(_or_404(store.complete_subtask(_db(), g.uid, task_id, subtask_id, dates.today()), "Task"))


@api.post("/tasks/<task_id>/subtasks/<subtask_id>/reopen")
@require_auth
@require_v2
def reopen_subtask(task_id, subtask_id):
    return jsonify(_or_404(store.reopen_subtask(_db(), g.uid, task_id, subtask_id, dates.today()), "Task"))


@api.delete("/tasks/<task_id>/subtasks/<subtask_id>")
@require_auth
@require_v2
def delete_subtask(task_id, subtask_id):
    return jsonify(_or_404(store.delete_subtask(_db(), g.uid, task_id, subtask_id, dates.today()), "Task"))


# ---- Settings (stored on the student document) ----
def _settings_view(student):
    return {"full_name": student["full_name"], "leadDays": student["lead_days"],
            "sessionMinutes": student["session_minutes"]}


@api.get("/settings")
@require_auth
@require_v2
def get_settings():
    return jsonify(_settings_view(store.get_student(_db(), g.uid, g.user_claims)))


@api.put("/settings")
@require_auth
@require_v2
def put_settings():
    changes = validate(read_json_object(), SETTINGS_RULES, partial=True)
    stored = {"full_name": changes.get("full_name"), "lead_days": changes.get("leadDays"),
              "session_minutes": changes.get("sessionMinutes")}
    stored = {key: value for key, value in stored.items() if value is not None}
    return jsonify(_settings_view(store.update_student(_db(), g.uid, g.user_claims, changes=stored)))


# ---- Reminder preferences (stored on the student document) ----
@api.get("/reminders/preferences")
@require_auth
@require_v2
def get_reminder_preferences():
    return jsonify(store.get_student(_db(), g.uid, g.user_claims)["reminder_prefs"])


@api.put("/reminders/preferences")
@require_auth
@require_v2
def put_reminder_preferences():
    changes = validate(read_json_object(), REMINDER_RULES, partial=True)
    student = store.update_student(_db(), g.uid, g.user_claims, reminder_changes=changes)
    return jsonify(student["reminder_prefs"])


# ---- Progress ----
@api.get("/progress")
@require_auth
@require_v2
def get_progress():
    return jsonify(build_progress(store.list_task_docs(_db(), g.uid), dates.today()))


# ---- AI endpoints (deterministic fallback, no AI model) ----
@api.post("/ai/plan")
@require_auth
def ai_plan():
    # Reads no stored data, so it is not behind the data-layout gate.
    fields = validate(read_json_object(), PLAN_RULES)
    return jsonify(fallback_ai.build_plan(fields["title"], fields["deadline"], fields["hoursPerDay"], dates.today()))


@api.post("/ai/chat")
@require_auth
@require_v2
def ai_chat():
    fields = validate(read_json_object(), CHAT_RULES)
    tasks = store.list_tasks(_db(), g.uid)
    return jsonify(fallback_ai.build_reply(fields["message"], tasks, dates.today()))
