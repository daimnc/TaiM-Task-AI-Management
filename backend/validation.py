"""Request validation. Each rule is a small function that returns the cleaned value or raises ValueError(message).

A rule table maps field name -> (rule, required_when_creating, default_when_creating).
Unknown fields in a request are ignored and never stored.
"""
import re

from flask import request

from dates import parse_date
from errors import ApiError

# ---- Allowed values (these match the dropdowns in the frontend) ----
CATEGORIES = ("Assignment", "Research", "Project", "Examination")
PRIORITIES = ("High", "Medium", "Low")
LEAD_DAYS = (1, 2, 3, 5, 7)
SESSION_MINUTES = (25, 45, 60, 90)

_DATE_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")


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
TASK_RULES = {
    "title": (_text(120), True, None),
    "course": (_text(100, allow_empty=True), False, ""),
    "category": (_one_of(CATEGORIES), True, None),
    "deadline": (_date, True, None),
    "priority": (_one_of(PRIORITIES), True, None),
    "progress": (_progress, False, 0),
}

SETTINGS_RULES = {
    "name": (_text(80), False, None),
    "program": (_text(100, allow_empty=True), False, None),
    "leadDays": (_one_of(LEAD_DAYS), False, None),
    "sessionMinutes": (_one_of(SESSION_MINUTES), False, None),
    "weeklySummary": (_bool, False, None),
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
