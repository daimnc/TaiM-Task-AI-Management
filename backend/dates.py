"""Small date helpers. Dates are 'YYYY-MM-DD' text, the same as the frontend."""
from datetime import datetime, timedelta, timezone

from config import Config

_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def today():
    """Today's date in the configured timezone (default UTC+8)."""
    tz = timezone(timedelta(hours=Config.UTC_OFFSET_HOURS))
    return datetime.now(tz).date()


def parse_date(text):
    return datetime.strptime(text, "%Y-%m-%d").date()


def safe_date(text):
    """Like parse_date, but returns None instead of raising for missing or broken values."""
    try:
        return parse_date(text)
    except (TypeError, ValueError):
        return None


def short_date(day):
    return f"{_MONTHS[day.month - 1]} {day.day}"


def due_text(days):
    """Same wording as the frontend's dueText()."""
    if days < 0:
        return "Overdue"
    if days == 0:
        return "Due today"
    if days == 1:
        return "Due tomorrow"
    return f"Due in {days} days"
