"""All /api routes except /api/health (which stays in app.py). Every route here requires a verified Firebase token."""
from flask import Blueprint, current_app, g, jsonify

import dates
import fallback_ai
import store
from errors import ApiError
from progress import build_progress
from security import require_auth
from validation import (CHAT_RULES, PLAN_RULES, REMINDER_RULES, SETTINGS_RULES, TASK_RULES,
                        read_json_object, validate)

api = Blueprint("api", __name__, url_prefix="/api")

REMINDER_DEFAULTS = {"deadline": True, "dailySummary": True, "progressCheckin": False, "quietHours": True}


def _db():
    return current_app.extensions["taim_db"]


def _task_id_or_404(task_id):
    if not store.valid_task_id(task_id):
        raise ApiError(404, "Task not found.")
    return task_id


def _settings_defaults():
    """Used until the student saves settings. Name comes from the verified token, never from the request."""
    claims = g.user_claims
    name = claims.get("name") or (claims.get("email") or "").split("@")[0] or "Student"
    return {"name": name[:80], "program": "", "leadDays": 2, "sessionMinutes": 45, "weeklySummary": True}


# ---- Tasks ----
@api.get("/tasks")
@require_auth
def list_tasks():
    return jsonify(store.list_tasks(_db(), g.uid))


@api.post("/tasks")
@require_auth
def create_task():
    fields = validate(read_json_object(), TASK_RULES)
    return jsonify(store.create_task(_db(), g.uid, fields, dates.today())), 201


@api.patch("/tasks/<task_id>")
@require_auth
def update_task(task_id):
    _task_id_or_404(task_id)
    fields = validate(read_json_object(), TASK_RULES, partial=True)
    task = store.update_task(_db(), g.uid, task_id, fields, dates.today())
    if task is None:
        raise ApiError(404, "Task not found.")
    return jsonify(task)


@api.delete("/tasks/<task_id>")
@require_auth
def delete_task(task_id):
    _task_id_or_404(task_id)
    if not store.delete_task(_db(), g.uid, task_id):
        raise ApiError(404, "Task not found.")
    return "", 204


# ---- Settings ----
@api.get("/settings")
@require_auth
def get_settings():
    return jsonify(store.get_prefs(_db(), g.uid, "settings", _settings_defaults()))


@api.put("/settings")
@require_auth
def put_settings():
    changes = validate(read_json_object(), SETTINGS_RULES, partial=True)
    return jsonify(store.save_prefs(_db(), g.uid, "settings", _settings_defaults(), changes))


# ---- Reminder preferences ----
@api.get("/reminders/preferences")
@require_auth
def get_reminder_preferences():
    return jsonify(store.get_prefs(_db(), g.uid, "reminders", REMINDER_DEFAULTS))


@api.put("/reminders/preferences")
@require_auth
def put_reminder_preferences():
    changes = validate(read_json_object(), REMINDER_RULES, partial=True)
    return jsonify(store.save_prefs(_db(), g.uid, "reminders", REMINDER_DEFAULTS, changes))


# ---- Progress ----
@api.get("/progress")
@require_auth
def get_progress():
    return jsonify(build_progress(store.list_task_docs(_db(), g.uid), dates.today()))


# ---- AI endpoints (deterministic fallback, no AI model) ----
@api.post("/ai/plan")
@require_auth
def ai_plan():
    fields = validate(read_json_object(), PLAN_RULES)
    return jsonify(fallback_ai.build_plan(fields["title"], fields["deadline"], fields["hoursPerDay"], dates.today()))


@api.post("/ai/chat")
@require_auth
def ai_chat():
    fields = validate(read_json_object(), CHAT_RULES)
    tasks = store.list_tasks(_db(), g.uid)
    return jsonify(fallback_ai.build_reply(fields["message"], tasks, dates.today()))
