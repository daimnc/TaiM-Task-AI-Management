"""Phase 4.3 Planner Assistance: the deterministic engine. Pure functions only.

No database, network, Flask or AI imports. Nothing here writes anything or modifies its inputs. The schedule, the
priority order, the minutes and every warning are decided HERE; the optional AI layer (planner_assist_ai.py) can only
add qualitative wording on top and never changes any of this.

How it decides (all rules are fixed and explained to the student through `reasons` and `limitations`):
  * Open work = every task whose status is not "completed" (status is authoritative; in_progress at 100% stays open).
  * Remaining minutes = the unfinished subtasks' estimated_minutes ("subtasks"). Without them, a PROVISIONAL guess from the
    student's focus-session length and the task type ("provisional"). A provisional figure is never a measurement.
  * Priority is NOT plain earliest-deadline-first. Overdue work is ranked by importance and age; other dated work is
    ranked by urgency, workload pressure, importance, and whether it is already started.
  * Daily allocation reserves the capacity needed to meet cumulative on-time deadlines before using the rest for overdue
    catch-up work. This prevents overdue work or one individually ranked task from causing an avoidable deadline miss.
  * Work is never placed after its deadline. A task with a missing or unreadable deadline is never given an invented date:
    it stays in the priority list and is reported under warnings.unscheduledTasks.
"""
import math
import re
from datetime import timedelta

from dates import safe_date

IMPORTANCE_RANK = {"high": 2, "medium": 1, "low": 0}
SESSIONS_BY_CATEGORY = {"quiz": 1, "assignment": 2, "other": 2, "exam": 3, "research": 3, "project": 4}
DEFAULT_SESSION_MINUTES = 45
MIN_PROVISIONAL_MINUTES = 15
TIGHT_RATIO = 0.6          # needs at least this share of the time available up to its deadline -> "tight"
MAX_TIPS = 3
_DATE_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")

SOURCE_SUBTASKS, SOURCE_PROVISIONAL = "subtasks", "provisional"
ESTIMATE_LABELS = {
    SOURCE_SUBTASKS: "Estimate from your unfinished subtasks",
    SOURCE_PROVISIONAL: "Provisional estimate, not a measurement of the work left",
}


def _plural(n, word):
    return f"{n} {word}{'' if n == 1 else 's'}"


def _int(value, default=0):
    return value if isinstance(value, int) and not isinstance(value, bool) else default


def _importance(raw):
    value = raw.get("importance")
    return value if value in IMPORTANCE_RANK else "medium"


def _progress(raw):
    return min(max(_int(raw.get("progress_pct")), 0), 100)


def _deadline(raw):
    """(date or None, problem or None). Only a real YYYY-MM-DD date counts; nothing is ever guessed."""
    text = raw.get("deadline")
    if text is None or (isinstance(text, str) and not text.strip()):
        return None, "missing_deadline"
    if not isinstance(text, str) or not _DATE_RE.match(text):
        return None, "invalid_deadline"
    day = safe_date(text)
    return (day, None) if day else (None, "invalid_deadline")


def estimate_minutes(raw, session_minutes):
    """(minutes, source). Subtask minutes are the student's own figures; provisional ones are a labelled rough guess."""
    subs = raw.get("subtasks") if isinstance(raw.get("subtasks"), list) else []
    open_minutes = [s["estimated_minutes"] for s in subs
                    if isinstance(s, dict) and s.get("status") != "completed"
                    and isinstance(s.get("estimated_minutes"), int) and not isinstance(s.get("estimated_minutes"), bool)
                    and s["estimated_minutes"] >= 1]
    if open_minutes:
        return sum(open_minutes), SOURCE_SUBTASKS
    sessions = SESSIONS_BY_CATEGORY.get(raw.get("category"), 2)
    guess = session_minutes * sessions * (100 - _progress(raw)) / 100
    return max(MIN_PROVISIONAL_MINUTES, int(math.ceil(guess / 5.0)) * 5), SOURCE_PROVISIONAL


def _score(rec, daily):
    """Higher = work on it sooner. Only used for dated, not-overdue tasks. Weights: urgency 40, pressure 30, importance 20, started 10."""
    d = rec["daysUntil"]
    proximity = 1.0 / (d + 1)
    pressure = min(rec["remainingMinutes"] / ((d + 1) * daily), 1.5) / 1.5
    importance = IMPORTANCE_RANK[rec["importance"]] / 2.0
    started = 1.0 if rec["status"] == "in_progress" else 0.0
    return round(40 * proximity + 30 * pressure + 20 * importance + 10 * started, 6)


def _reasons(rec, daily):
    d, out = rec["daysUntil"], []
    if d is None:
        out.append(rec["deadlineProblemText"])
    elif d < 0:
        out.append(f"Overdue by {_plural(-d, 'day')}")
    elif d == 0:
        out.append("Due today")
    elif d == 1:
        out.append("Due tomorrow")
    else:
        out.append(f"Due in {d} days")
    if rec["importance"] == "high":
        out.append("High importance")
    elif rec["importance"] == "low":
        out.append("Low importance")
    if rec["status"] == "in_progress":
        out.append(f"Already started ({rec['progressPct']}% done)")
    if d is not None and d >= 0 and rec["remainingMinutes"] >= TIGHT_RATIO * (d + 1) * daily:
        out.append("Tight: needs most of the time you have before the deadline")
    if rec["estimateSource"] == SOURCE_PROVISIONAL:
        out.append("Provisional time estimate")
    return out[:5]


def _collect(task_docs, subject_names, session_minutes, today):
    open_tasks = []
    for task_id, raw in task_docs:
        raw = raw if isinstance(raw, dict) else {}
        if raw.get("status") == "completed":
            continue
        day, problem = _deadline(raw)
        minutes, source = estimate_minutes(raw, session_minutes)
        open_tasks.append({
            "taskId": task_id,
            "title": raw.get("title") if isinstance(raw.get("title"), str) and raw.get("title").strip() else "Untitled task",
            "subjectName": subject_names.get(raw.get("subject_id"), "Unknown subject"),
            "deadline": day.isoformat() if day else None,
            "daysUntil": (day - today).days if day else None,
            "importance": _importance(raw),
            "status": raw.get("status") if raw.get("status") in ("not_started", "in_progress") else "not_started",
            "progressPct": _progress(raw),
            "remainingMinutes": minutes,
            "estimateSource": source,
            "estimateLabel": ESTIMATE_LABELS[source],
            "deadlineProblem": problem,
            "deadlineProblemText": ("No deadline is set" if problem == "missing_deadline" else "The deadline is not a readable date"),
        })
    return open_tasks


def _rank(open_tasks, daily):
    overdue = [t for t in open_tasks if t["daysUntil"] is not None and t["daysUntil"] < 0]
    dated = [t for t in open_tasks if t["daysUntil"] is not None and t["daysUntil"] >= 0]
    undated = [t for t in open_tasks if t["daysUntil"] is None]
    overdue.sort(key=lambda t: (-IMPORTANCE_RANK[t["importance"]], t["daysUntil"], t["taskId"]))
    dated.sort(key=lambda t: (-_score(t, daily), t["daysUntil"], -IMPORTANCE_RANK[t["importance"]], t["taskId"]))
    undated.sort(key=lambda t: (-IMPORTANCE_RANK[t["importance"]], t["status"] != "in_progress", t["taskId"]))
    return overdue + dated + undated


def _schedule(ranked, today, daily, horizon):
    """Fill days while protecting individual and cumulative on-time deadlines."""
    days = [{"date": (today + timedelta(days=d)).isoformat(), "dayOffset": d, "capacityMinutes": daily,
             "allocatedMinutes": 0, "remainingCapacityMinutes": daily, "overloaded": False, "items": []} for d in range(horizon)]
    plan = [t for t in ranked if t["daysUntil"] is not None]
    left = {t["taskId"]: t["remainingMinutes"] for t in plan}
    order = {t["taskId"]: i for i, t in enumerate(plan)}
    for d, day in enumerate(days):
        cap = daily
        eligible = [t for t in plan if left[t["taskId"]] > 0 and (t["daysUntil"] < 0 or t["daysUntil"] >= d)]
        on_time = [t for t in eligible if t["daysUntil"] >= 0]
        overdue = [t for t in eligible if t["daysUntil"] < 0]

        # Preserve the previous must-start behavior, including tasks too large to
        # finish today: any on-time task needing today's capacity gets first use.
        must_start = [t for t in on_time if left[t["taskId"]] > (t["daysUntil"] - d) * daily]
        must_start.sort(key=lambda t: (t["daysUntil"], order[t["taskId"]]))

        # If no single task is urgent on its own, check cumulative workload at
        # every deadline. Individually feasible tasks can still compete for the
        # same future capacity, so reserve only the aggregate shortfall today.
        reserve, critical_tasks = 0, []
        if not must_start:
            for deadline in sorted({t["daysUntil"] for t in on_time}):
                due_group = [t for t in on_time if t["daysUntil"] <= deadline]
                demand = sum(left[t["taskId"]] for t in due_group)
                future_capacity = max(0, deadline - d) * daily
                shortfall = demand - future_capacity
                if shortfall > reserve:
                    reserve, critical_tasks = shortfall, due_group
            reserve = min(cap, max(0, reserve))
            critical_tasks.sort(key=lambda t: order[t["taskId"]])

        overdue.sort(key=lambda t: order[t["taskId"]])
        remaining = sorted(eligible, key=lambda t: order[t["taskId"]])

        def allocate(tasks, budget):
            nonlocal cap
            used = 0
            for t in tasks:
                if cap <= 0 or used >= budget:
                    break
                take = min(left[t["taskId"]], cap, budget - used)
                if take <= 0:
                    continue
                left[t["taskId"]] -= take
                cap -= take
                used += take
                existing = next((item for item in day["items"] if item["taskId"] == t["taskId"]), None)
                if existing:
                    existing["minutes"] += take
                else:
                    day["items"].append({"taskId": t["taskId"], "title": t["title"], "subjectName": t["subjectName"], "minutes": take,
                                         "estimateSource": t["estimateSource"], "deadline": t["deadline"], "importance": t["importance"],
                                         "overdue": t["daysUntil"] < 0})
            return used

        if must_start:
            allocate(must_start, cap)
        elif reserve:
            allocate(critical_tasks, reserve)
        allocate(overdue, cap)
        allocate(remaining, cap)
        day["allocatedMinutes"] = daily - cap
        day["remainingCapacityMinutes"] = cap
    return days, left


def _warnings(ranked, left, days, daily, horizon):
    at_risk, unscheduled, overdue_count, deficit = [], [], 0, 0
    deficit_tasks = []
    for t in ranked:
        d = t["daysUntil"]
        if d is None:
            unscheduled.append({
                "taskId": t["taskId"], "title": t["title"], "subjectName": t["subjectName"], "importance": t["importance"],
                "status": t["status"], "progressPct": t["progressPct"], "remainingMinutes": t["remainingMinutes"],
                "estimateSource": t["estimateSource"], "reason": t["deadlineProblem"],
                "message": ("It has no deadline, so TAiM did not place it in the schedule or guess a date. Set a deadline to include it."
                            if t["deadlineProblem"] == "missing_deadline" else
                            "Its deadline is not a readable date, so TAiM did not place it in the schedule or guess a date. Fix the deadline to include it.")})
            continue
        unalloc = left[t["taskId"]]
        due_in_horizon = d < 0 or d <= horizon - 1
        if due_in_horizon and unalloc > 0:
            deficit += unalloc
            deficit_tasks.append(t)
        reason = message = None
        if d < 0:
            overdue_count += 1
            reason, message = "overdue", f"Overdue by {_plural(-d, 'day')}. Catch-up work is placed first in the schedule."
        elif t["remainingMinutes"] > (d + 1) * daily:
            reason = "exceeds_capacity_before_deadline"
            message = (f"Needs about {t['remainingMinutes']} min, but your daily limit allows only {(d + 1) * daily} min "
                       f"up to the deadline.")
        elif due_in_horizon and unalloc > 0:
            reason = "not_fully_scheduled"
            message = f"{unalloc} min could not be fitted before the deadline alongside your other work."
        if reason:
            at_risk.append({"taskId": t["taskId"], "title": t["title"], "subjectName": t["subjectName"], "deadline": t["deadline"],
                            "daysUntil": d, "importance": t["importance"], "remainingMinutes": t["remainingMinutes"],
                            "estimateSource": t["estimateSource"], "unallocatedMinutes": unalloc, "reason": reason, "message": message})
    overloaded_days = []
    for day in days:
        if day["remainingCapacityMinutes"] == 0 and any(
                t["daysUntil"] < 0 or t["daysUntil"] >= day["dayOffset"] for t in deficit_tasks):
            day["overloaded"] = True
            overloaded_days.append(day["date"])
    return {"overdueCount": overdue_count, "overloaded": deficit > 0, "overloadedDays": overloaded_days,
            "deficitMinutes": deficit, "atRiskTasks": at_risk, "unscheduledTasks": unscheduled}


def _limitations(open_tasks, session_minutes, today, horizon):
    notes = []
    prov = sum(1 for t in open_tasks if t["estimateSource"] == SOURCE_PROVISIONAL)
    if prov:
        notes.append(f"{_plural(prov, 'open task')} {'has' if prov == 1 else 'have'} no unfinished subtask minutes, so TAiM used a provisional "
                     f"estimate from your {session_minutes}-minute focus session and the task type. These are rough guesses, not measurements "
                     "of the work left. Add subtasks with minutes for a real estimate.")
    if any(t["daysUntil"] is None for t in open_tasks):
        notes.append("Tasks without a readable deadline are listed but not scheduled, and are not counted in the totals.")
    notes.append(f"Dates use the server's local date ({today.isoformat()}). A task due today can be worked on today; nothing is planned after its deadline.")
    notes.append(f"This is a suggestion for the next {_plural(horizon, 'day')} based on the daily time you entered. It is not saved and does not change your tasks.")
    return notes


def _rule_coaching(plan):
    ranked, caps, warn = plan["prioritizedTasks"], plan["capacity"], plan["warnings"]
    if not ranked:
        return {"summary": "You have no open tasks, so there is nothing to schedule right now.", "tips": []}
    nxt = ranked[0]
    summary = f"Start with \"{nxt['title']}\": {nxt['reasons'][0].lower()}."
    if warn["deficitMinutes"] > 0:
        summary += f" Your plan is over capacity by {warn['deficitMinutes']} min, so some work cannot fit before its deadline."
    elif caps["allocatedMinutes"] > 0:
        summary += f" All work due in the next {_plural(caps['horizonDays'], 'day')} fits in the time you set aside."
    tips = []
    if warn["overdueCount"]:
        tips.append({"focus": "overdue", "text": f"Clear the {_plural(warn['overdueCount'], 'overdue task')} first. Catch-up work is already placed at the start of the schedule."})
    if warn["deficitMinutes"] > 0 or any(a["reason"] == "exceeds_capacity_before_deadline" for a in warn["atRiskTasks"]):
        tips.append({"focus": "capacity", "text": "Some deadlines need more time than your daily limit allows. Raise the daily time, split the task into smaller subtasks, or talk to your instructor early."})
    if warn["unscheduledTasks"]:
        tips.append({"focus": "deadlines", "text": f"Set a valid deadline on {_plural(len(warn['unscheduledTasks']), 'task')} so they can be scheduled."})
    if any(t["estimateSource"] == SOURCE_PROVISIONAL for t in ranked):
        tips.append({"focus": "estimates", "text": "Some time estimates are provisional. Adding subtasks with minutes makes the schedule more reliable."})
    if not tips:
        tips.append({"focus": "next", "text": f"Work in focused sessions on \"{nxt['title']}\" and follow the schedule day by day."})
    return {"summary": summary, "tips": tips[:MAX_TIPS]}


def build_plan_assist(task_docs, subjects, student, today, hours_per_day=2.0, horizon_days=7):
    """The whole authoritative answer, without the optional AI wording. `task_docs` is store.list_task_docs() output,
    `subjects` is store.list_subjects() output, `student` supplies session_minutes. Inputs are only read."""
    session = student.get("session_minutes") if isinstance(student, dict) else None
    session = session if session in (25, 45, 60, 90) else DEFAULT_SESSION_MINUTES
    daily = max(int(round(hours_per_day * 60)), 1)
    names = {s.get("subject_id"): s.get("subject_name") for s in subjects if isinstance(s, dict)}
    ranked = _rank(_collect(task_docs, names, session, today), daily)
    days, left = _schedule(ranked, today, daily, horizon_days)
    warn = _warnings(ranked, left, days, daily, horizon_days)
    planned = {}
    for day in days:
        for item in day["items"]:
            planned[item["taskId"]] = planned.get(item["taskId"], 0) + item["minutes"]
    for i, t in enumerate(ranked):
        t["rank"] = i + 1
        t["scheduled"] = t["daysUntil"] is not None
        t["plannedMinutes"] = planned.get(t["taskId"], 0)
        t["unallocatedMinutes"] = left.get(t["taskId"])
        t["reasons"] = _reasons(t, daily)
        t.pop("deadlineProblemText")
    needed = sum(t["remainingMinutes"] for t in ranked if t["scheduled"])
    allocated = sum(planned.values())
    plan = {
        "asOf": today.isoformat(),
        "capacity": {"hoursPerDay": float(hours_per_day), "dailyMinutes": daily, "horizonDays": horizon_days,
                     "totalAvailableMinutes": daily * horizon_days, "totalNeededMinutes": needed,
                     "allocatedMinutes": allocated, "unallocatedMinutes": needed - allocated},
        "nextTask": dict(ranked[0]) if ranked else None,
        "prioritizedTasks": ranked,
        "schedule": days,
        "warnings": warn,
        "limitations": _limitations(ranked, session, today, horizon_days),
    }
    plan.update(_rule_coaching(plan))
    return plan
