"""Deterministic, rule-based replacement for AI. NO AI MODEL IS USED HERE.

It exists so /api/ai/plan and /api/ai/chat work without any paid provider. Every response says so:
  mock: true            (the frontend shows "Mock response - not real AI." when this is set)
  aiGenerated: false
  source: "deterministic-fallback"
  notice: plain-text explanation

When a real provider is chosen later, replace the two functions called from routes.py
(build_plan / build_reply) and keep the same response shape.
"""
import re
from datetime import timedelta

from dates import due_text, parse_date, safe_date, short_date
from validation import STATUS_COMPLETED

SOURCE = "deterministic-fallback"

_STEPS = [
    "Define scope and outline",
    "Gather and review sources",
    "Draft main sections",
    "Revise and add citations",
    "Final proofread and submit",
]


def _labels(notice):
    return {"mock": True, "aiGenerated": False, "source": SOURCE, "notice": notice}


def spread_offsets(deadline, count, today):
    """Day offsets from today for `count` steps spread evenly; the last offset is the deadline (never before today)."""
    days_left = max((parse_date(deadline) - today).days, 0)
    return [(days_left * (index + 1) + count // 2) // count for index in range(count)]  # rounded half up


def build_plan(title, deadline, hours_per_day, today, reason=None):
    """Fixed five-step template spread evenly between today and the deadline (the last step is due on the deadline).
    The title and requirements are not analysed. `reason` (plain text) is appended to the notice when AI was wanted
    but could not be used."""
    count = len(_STEPS)
    offsets = spread_offsets(deadline, count, today)
    minutes_per_day = int(round(hours_per_day * 60))
    subtasks, previous = [], 0
    for step, offset in zip(_STEPS, offsets):
        step_days = max(offset - previous, 1)
        previous = offset
        subtasks.append({
            "title": step,
            "dueDate": (today + timedelta(days=offset)).isoformat(),
            "minutes": minutes_per_day * step_days,
        })
    notice = ("Rule-based fallback plan: a fixed five-step template spread evenly before the deadline. "
              "No AI model was used.")
    result = _labels(f"{notice} {reason}" if reason else notice)
    result["subtasks"] = subtasks
    return result


def _open_tasks(tasks):
    return [t for t in tasks if t.get("status") != STATUS_COMPLETED]


def _top_pick(open_tasks):
    """High-importance task with the least progress; otherwise the task due soonest."""
    high = [t for t in open_tasks if t.get("importance") == "high"]
    if high:
        return min(high, key=lambda t: (t.get("progress_pct", 0), t.get("deadline", "")))
    return min(open_tasks, key=lambda t: t.get("deadline", ""))


def _days_until(task, today):
    deadline = safe_date(task.get("deadline"))
    return (deadline - today).days if deadline else 0


def build_reply(message, tasks, today):
    """Keyword rules over the student's own stored tasks. `tasks` are the public task dicts."""
    question = message.lower()
    open_tasks = _open_tasks(tasks)
    if re.search(r"first|priorit|start", question):
        if open_tasks:
            pick = _top_pick(open_tasks)
            reply = (f'Based on your recorded tasks, start with "{pick["title"]}" ({pick["progress_pct"]}% done, '
                     f'{due_text(_days_until(pick, today)).lower()}). Try a 25-minute session.')
        else:
            reply = "You have no open tasks."
    elif re.search(r"due|deadline|soon", question):
        if open_tasks:
            soonest = sorted(open_tasks, key=lambda t: t.get("deadline", ""))[:3]
            parts = []
            for t in soonest:
                deadline = safe_date(t.get("deadline"))
                parts.append(f'{t["title"]} ({short_date(deadline) if deadline else "no date"})')
            reply = "Upcoming: " + "; ".join(parts) + "."
        else:
            reply = "Nothing is due."
    else:
        reply = 'I can help with prioritizing tasks and deadlines. Try asking "What should I work on first?"'
    result = _labels("Rule-based fallback reply based on keywords and your recorded tasks. No AI model was used.")
    result["reply"] = reply
    return result
