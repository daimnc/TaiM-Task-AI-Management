"""Request validation. Each rule is a small function that returns the cleaned value or raises ValueError(message).

A rule table maps field name -> (rule, required_when_creating, default_when_creating).
Unknown fields in a request are ignored and never stored.
"""
import re

from flask import request

from dates import parse_date
from errors import ApiError

# ---- Allowed values (approved decision H5) ----
CATEGORIES = ("assignment", "project", "exam", "quiz", "research", "other")
IMPORTANCE = ("low", "medium", "high")
STATUS_NOT_STARTED, STATUS_IN_PROGRESS, STATUS_COMPLETED = "not_started", "in_progress", "completed"
STATUSES = (STATUS_NOT_STARTED, STATUS_IN_PROGRESS, STATUS_COMPLETED)
LEAD_DAYS = (1, 2, 3, 5, 7)
SESSION_MINUTES = (25, 45, 60, 90)

_DATE_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,128}$")


# ---- Reading the request ----
def read_json_object():
    body = request.get_json(force=True, silent=True)
    if not isinstance(body, dict):
        raise ApiError(400, "Request body must be a JSON object.")
    return body


def fail(errors):
    detail = "; ".join(f"{field}: {message}" for field, message in errors.items())
    raise ApiError(422, detail, errors=errors)


# ---- Reusable rules ----
def _text(max_length, allow_empty=False):
    def rule(value):
        if not isinstance(value, str):
            raise ValueError("must be text.")
        value = value.strip()
        if not value and not allow_empty:
            raise ValueError("must not be empty.")
        if len(value) > max_length:
            raise ValueError(f"must be {max_length} characters or fewer.")
        return value
    return rule


def _one_of(allowed):
    def rule(value):
        if isinstance(value, bool) or not isinstance(value, (str, int)) or value not in allowed:
            raise ValueError("must be one of: " + ", ".join(str(a) for a in allowed) + ".")
        return value
    return rule


def _id(value):
    if not isinstance(value, str) or not _ID_RE.match(value):
        raise ValueError("must be a valid id.")
    return value


def _date(value):
    if not isinstance(value, str) or not _DATE_RE.match(value):
        raise ValueError("must be a real date in YYYY-MM-DD format.")
    try:
        parse_date(value)
    except ValueError:
        raise ValueError("must be a real date in YYYY-MM-DD format.")
    return value


def _bool(value):
    if not isinstance(value, bool):
        raise ValueError("must be true or false.")
    return value


def _progress(value):
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 100:
        raise ValueError("must be a whole number from 0 to 100.")
    return value


def _hours_per_day(value):
    """The planner form sends this as text ("0.5", "1", ...), so numeric text is accepted too."""
    if isinstance(value, bool):
        raise ValueError("must be a number of hours.")
    if isinstance(value, str):
        try:
            value = float(value.strip())
        except ValueError:
            raise ValueError("must be a number of hours.")
    elif not isinstance(value, (int, float)):
        raise ValueError("must be a number of hours.")
    hours = float(value)
    if not 0.25 <= hours <= 8:  # also rejects NaN and infinity
        raise ValueError("must be between 0.25 and 8 hours.")
    return hours


# ---- Rule tables: field -> (rule, required, default) ----
# `status`, `progress_pct`, `completed_on`, `student_id`, `task_id`, `created_at` are never accepted from the client
# as task data: the server owns them (see TASK_CREATE_FORBIDDEN / TASK_UPDATE_FORBIDDEN and store.py).
SUBJECT_RULES = {
    "subject_name": (_text(100), True, None),
}

TASK_RULES = {
    "title": (_text(120), True, None),
    "subject_id": (_id, True, None),
    "category": (_one_of(CATEGORIES), True, None),
    "deadline": (_date, True, None),
    "importance": (_one_of(IMPORTANCE), True, None),
}

# PATCH accepts the same fields as create, plus progress (changing progress never changes status).
TASK_UPDATE_RULES = {**TASK_RULES, "progress_pct": (_progress, False, None)}

TASK_CREATE_FORBIDDEN = {
    "status": "is set by the server: new tasks start as not_started.",
    "progress_pct": "is set by the server: new tasks start at 0.",
}
TASK_UPDATE_FORBIDDEN = {
    "status": "cannot be changed here. Use the start, complete or reopen actions.",
}

# ---- Subtasks (embedded in the parent task document) ----
MAX_SUBTASKS = 20  # per parent task, counting the ones already saved
SUBTASK_STATUSES = (STATUS_NOT_STARTED, STATUS_COMPLETED)


MAX_SAFE_INTEGER = 9007199254740991  # JavaScript's Number.MAX_SAFE_INTEGER: a technical limit, not a workload limit


def _minutes(value):
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= MAX_SAFE_INTEGER:
        raise ValueError(f"must be a whole number of minutes, at least 1 (at most {MAX_SAFE_INTEGER}).")
    return value


# estimated_minutes is optional (default 30). subtask_id and status are server-owned. Other unknown fields
# (for example a due date) are ignored and never stored.
SUBTASK_RULES = {
    "title": (_text(120), True, None),
    "estimated_minutes": (_minutes, False, 30),
}
SUBTASK_FORBIDDEN = {
    "subtask_id": "is set by the server.",
    "status": "is set by the server: new subtasks start as not_started.",
}

SETTINGS_RULES = {
    "full_name": (_text(80), False, None),
    "leadDays": (_one_of(LEAD_DAYS), False, None),
    "sessionMinutes": (_one_of(SESSION_MINUTES), False, None),
}

REMINDER_RULES = {
    "deadline": (_bool, False, None),
    "dailySummary": (_bool, False, None),
    "progressCheckin": (_bool, False, None),
    "quietHours": (_bool, False, None),
}

PLAN_RULES = {
    "title": (_text(120), True, None),
    "requirements": (_text(2000, allow_empty=True), False, ""),
    "deadline": (_date, True, None),
    "hoursPerDay": (_hours_per_day, False, 1.0),
}

CHAT_RULES = {
    "message": (_text(1000), True, None),
}


def reject_fields(body, forbidden):
    """422 when the client sends a field that only the server may set. `forbidden` maps field -> message."""
    errors = {name: message for name, message in forbidden.items() if name in body}
    if errors:
        fail(errors)


def validate(body, rules, partial=False):
    """Return the cleaned fields, or raise a 422 ApiError.

    partial=False: creating. Required fields must be present and missing optional fields get their default.
    partial=True: updating. Only the fields that were sent are checked and returned (at least one is needed).
    """
    clean, errors = {}, {}
    for name, (rule, required, default) in rules.items():
        if name in body:
            try:
                clean[name] = rule(body[name])
            except ValueError as problem:
                errors[name] = str(problem)
        elif not partial:
            if required:
                errors[name] = "is required."
            else:
                clean[name] = default
    if partial and not clean and not errors:
        errors["body"] = "send at least one of: " + ", ".join(rules) + "."
    if errors:
        fail(errors)
    return clean


def validate_subtask_batch(body):
    """Validate a whole {"subtasks": [...]} request BEFORE anything is saved. Returns the cleaned list.
    Every problem in every item is reported at once, keyed like "subtasks[2].title"."""
    items = body.get("subtasks")
    if not isinstance(items, list) or not items:
        fail({"subtasks": "must be a non-empty list."})
    if len(items) > MAX_SUBTASKS:
        fail({"subtasks": f"at most {MAX_SUBTASKS} subtasks can be added at once."})
    clean, errors = [], {}
    for index, item in enumerate(items):
        at = f"subtasks[{index}]"
        if not isinstance(item, dict):
            errors[at] = "must be an object."
            continue
        for name, message in SUBTASK_FORBIDDEN.items():
            if name in item:
                errors[f"{at}.{name}"] = message
        fields = {}
        for name, (rule, required, default) in SUBTASK_RULES.items():
            if name in item:
                try:
                    fields[name] = rule(item[name])
                except ValueError as problem:
                    errors[f"{at}.{name}"] = str(problem)
            elif required:
                errors[f"{at}.{name}"] = "is required."
            else:
                fields[name] = default
        clean.append(fields)
    if errors:
        fail(errors)
    return clean
