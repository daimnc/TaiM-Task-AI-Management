"""All /api routes except /api/health (which stays in app.py). Every route here requires a verified Firebase token.

The student is always g.uid (from the verified token). No route reads a student id from the URL, query or body.
Routes that use the students/subjects/tasks data are also behind the TAIM_ENABLE_V2 gate (default: off).
"""
from functools import wraps

from flask import Blueprint, current_app, g, jsonify

import ai_provider
import assistant_ai
import dates
import fallback_ai
import insights
import insights_ai
import planner_assist
import planner_assist_ai
import store
from errors import ApiError
from progress import build_progress
from security import require_auth
from validation import (CHAT_RULES, INSIGHTS_RULES, PLAN_RULES, PLANNER_ASSIST_RULES, REMINDER_RULES, SETTINGS_RULES, SUBJECT_RULES, TASK_CREATE_FORBIDDEN,
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


# ---- AI endpoints (Groq/Gemini only with consent and configuration; otherwise the deterministic template) ----
def _plan_with_ai(fields, today):
    """(response, None) when Groq or Gemini produced valid steps, otherwise a template reason.
    Nothing is saved here: the student reviews suggestions and adds them as subtasks themselves."""
    if fields["aiConsent"] is not True:
        return None, ai_provider.fallback_notice("consent")
    provider = current_app.extensions.get("taim_ai")
    if provider is None:
        return None, ai_provider.fallback_notice("not_configured")
    allowed, wait = current_app.extensions["taim_ai_limiter"].allow(g.uid)  # one allowance per real plan request
    if not allowed:
        return None, ai_provider.fallback_notice("rate_limited", wait)
    try:
        result = provider.generate_steps(fields["title"], fields["requirements"], fields["deadline"], fields["hoursPerDay"])
        if isinstance(result, ai_provider.ProviderResult):
            raw, source = result.steps, result.source
        else:  # backwards-compatible with injected test providers
            raw, source = result, getattr(provider, "source", ai_provider.SOURCE)
        steps = ai_provider.sanitize_steps(raw)
        return ai_provider.build_ai_response(steps, fields["deadline"], today, source), None
    except ai_provider.ProviderError as problem:
        reason = problem.reason
    except Exception as problem:  # never turn an AI problem into a 500; log only the type, never task text or the key
        reason = type(problem).__name__
    current_app.logger.warning("AI plan fell back to the template (%s).", reason)
    return None, ai_provider.fallback_notice(reason)


@api.post("/ai/plan")
@require_auth
def ai_plan():
    # Reads no stored data, so it is not behind the data-layout gate.
    fields = validate(read_json_object(), PLAN_RULES)
    today = dates.today()
    response, reason = _plan_with_ai(fields, today)
    if response is None:
        response = fallback_ai.build_plan(fields["title"], fields["deadline"], fields["hoursPerDay"], today, reason)
    return jsonify(response)


@api.post("/ai/chat")
@require_auth
@require_v2
def ai_chat():
    fields = validate(read_json_object(), CHAT_RULES)
    today = dates.today()
    task_records = store.list_task_docs(_db(), g.uid)
    tasks = [data for _task_id, data in task_records]
    subjects = store.list_subjects(_db(), g.uid)
    anonymizer = current_app.extensions["taim_assistant_anonymizer"]
    mappings = anonymizer.mappings(g.uid, task_records, subjects)
    provider = current_app.extensions.get("taim_ai")
    response = None
    notice = None

    if fields["aiConsent"] is True and provider is not None:
        allowed, wait = current_app.extensions["taim_assistant_limiter"].allow(g.uid)
        if not allowed:
            raise ApiError(429, f"AI request limit reached. Try again in about {wait} seconds.",
                           headers={"Retry-After": str(wait), "Cache-Control": "no-store"})
        try:
            response = assistant_ai.generate_reply(
                provider, fields["message"], fields["history"], tasks, subjects, today,
                current_app.logger, mappings=mappings)
        except ai_provider.ProviderError as problem:
            notice = ai_provider.fallback_notice(problem.reason)
        except Exception as problem:
            current_app.logger.warning("AI Assistant fell back (%s).", type(problem).__name__)
            notice = ai_provider.fallback_notice("unavailable")
    elif fields["aiConsent"] is True:
        notice = ai_provider.fallback_notice("not_configured")
    else:
        notice = "AI was not used because consent was not given. Your reply is generated by TAiM's rule-based assistant."

    if response is None:
        response = fallback_ai.build_reply(fields["message"], tasks, today)
        response.update({"mock": False, "aiGenerated": False, "source": "rule-based"})
        response["notice"] = notice or "A rule-based reply was used because AI was unavailable."
    result = jsonify(response)
    result.headers["Cache-Control"] = "no-store"
    return result


@api.post("/ai/insights")
@require_auth
@require_v2
def ai_insights():
    """Phase 4.2. Facts are calculated here from the student's own tasks. Only with aiConsent: true and a configured
    provider are anonymised numbers sent to Groq/Gemini; otherwise rule-based text is returned. Nothing is saved."""
    fields = validate(read_json_object(), INSIGHTS_RULES)
    facts = insights.build_facts(store.list_task_docs(_db(), g.uid), store.list_subjects(_db(), g.uid), dates.today())
    result = insights_ai.build_insights_response(
        facts, fields["aiConsent"], current_app.extensions.get("taim_ai"),
        current_app.extensions["taim_insights_limiter"], g.uid, current_app.logger)
    response = jsonify(result)
    response.headers["Cache-Control"] = "no-store"
    return response


@api.post("/ai/planner-assist")
@require_auth
@require_v2
def ai_planner_assist():
    """Phase 4.3. The schedule, priorities and warnings are calculated here from the student's own tasks (read-only, nothing
    is saved). Only with aiConsent: true and a configured provider is an anonymised summary sent to Groq/Gemini, and the AI
    can only reword the coaching text."""
    fields = validate(read_json_object(), PLANNER_ASSIST_RULES)
    student = store.get_student(_db(), g.uid, g.user_claims)
    plan = planner_assist.build_plan_assist(store.list_task_docs(_db(), g.uid), store.list_subjects(_db(), g.uid), student,
                                            dates.today(), fields["hoursPerDay"], fields["horizonDays"])
    result = planner_assist_ai.build_planner_assist_response(
        plan, fields["aiConsent"], current_app.extensions.get("taim_ai"),
        current_app.extensions["taim_planner_limiter"], g.uid, current_app.logger)
    response = jsonify(result)
    response.headers["Cache-Control"] = "no-store"
    return response
