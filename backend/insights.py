"""Facts engine for AI Insights (Phase 4.2, Batch 1). Pure functions: no database, no network, no AI, no writes.

`build_facts(task_docs, subjects, today)` turns a student's stored tasks and subjects into plain numbers. Everything an
insight says about the student is calculated here, so a model (added in a later batch) only has to put words around
numbers that already exist, and every number it quotes can be checked against the exact fact it claims to describe
(see `flatten_facts`).

`rule_based_insights(facts)` writes the same four areas in plain words without any model. It is the fallback and what a
student gets when they do not consent to AI.

Inputs, exactly what store.py already returns:
  task_docs  [(task_id, raw_task_dict), ...]   from store.list_task_docs(db, uid)   (this student's tasks only)
  subjects   [{subject_id, subject_name}, ...] from store.list_subjects(db, uid)
  today      a datetime.date

What the numbers mean, and what they do NOT mean:
  * Status is authoritative (a task is completed only when its status is "completed"), as in progress.py.
  * `completed_on` is the day TAiM recorded the task as complete. It is NOT the time spent studying and not
    necessarily the day the work happened. Patterns built on it say so (DATE_DISCLOSURE).
  * Only tasks that are completed right now count. A task that was reopened or deleted leaves no trace in the data, so
    it contributes nothing and nothing is guessed about it (HISTORY_DISCLOSURE).
  * There is no time-of-day, no study-time log and no daily capacity in the stored data, so none of those are claimed.
    "Heavy" deadlines are a simple count of tasks (see the constants), not an estimate of hours.
  * Patterns need a minimum amount of history; below it the figures are None and the text says "not enough data".
"""
import statistics
from datetime import timedelta

from dates import safe_date
from progress import build_progress
from validation import STATUS_COMPLETED

# ---- Thresholds (approved defaults; named so they are easy to find and change) ----
HORIZON_DAYS = 14               # per-day deadline counts cover today .. today + 13
SOON_DAYS = 3                   # "due within 3 days" = due today up to today + 3 days (day offsets 0..3), never overdue
HEAVY_SOON_TASKS = 3            # heavy when at least this many open tasks are due within SOON_DAYS, OR
HEAVY_OVERDUE_SOON_TASKS = 2    # when at least 1 task is overdue AND at least this many are due within SOON_DAYS
MIN_PATTERN_COMPLETIONS = 5     # completed tasks with a usable completion day AND deadline before margins/rates are described
MIN_WEEKDAY_COMPLETIONS = 8     # completed tasks with a usable completion day before a weekday pattern is described
MIN_WEEKDAY_TOP = 3             # the busiest weekday needs at least this many completions to count as a pattern
CONCENTRATION_PCT = 50          # one subject holding at least this share of open tasks is "concentrated" ...
CONCENTRATION_MIN_OPEN = 4      # ... but only when there are at least this many open tasks
MAX_SUBJECT_ROWS = 8            # subjects listed individually; the rest are summed in `otherSubjects`
MAX_UPCOMING = 5                # nearest-deadline open tasks listed
LAST_MINUTE_MARGIN_DAYS = 1     # finished on the deadline day or this many days before it counts as "last minute"

AREAS = ("completion", "workload", "deadlines", "patterns")
WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
UNKNOWN_SUBJECT = "Unknown subject"
_IMPORTANCE_RANK = {"high": 3, "medium": 2, "low": 1}

DATE_DISCLOSURE = ("Completion dates are the day a task was marked complete in TAiM. They are not the time you "
                   "actually spent studying, and the work may have happened on other days.")
HISTORY_DISCLOSURE = ("Only tasks that are completed right now are counted. Tasks that were reopened or deleted are "
                      "not part of this history, and nothing is assumed about them.")


def _pct(part, whole):
    """Whole percent, rounded half up with integer arithmetic (same formula as progress.py)."""
    return (part * 100 + whole // 2) // whole if whole else 0


def _subtasks(task):
    items = task.get("subtasks")
    return [s for s in items if isinstance(s, dict)] if isinstance(items, list) else []


def _minutes(subtask):
    value = subtask.get("estimated_minutes")
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else 0


def _subject_names(subjects):
    names = {}
    for subject in subjects or []:
        if isinstance(subject, dict) and isinstance(subject.get("subject_id"), str):
            name = subject.get("subject_name")
            names[subject["subject_id"]] = name if isinstance(name, str) and name.strip() else UNKNOWN_SUBJECT
    return names


# ---- The facts ----
def build_facts(task_docs, subjects, today):
    """All calculated facts for one student. Plain dict of numbers, strings, lists and None; JSON-serialisable.
    Does not modify its inputs."""
    task_docs = list(task_docs)
    names = _subject_names(subjects)
    progress = build_progress(task_docs, today)  # single source of truth for rates and weekly figures

    done_docs = [(i, t) for i, t in task_docs if t.get("status") == STATUS_COMPLETED]
    open_docs = [(i, t) for i, t in task_docs if t.get("status") != STATUS_COMPLETED]
    in_progress = sum(1 for _i, t in open_docs if t.get("status") == "in_progress")

    open_sub_done = open_sub_total = 0
    for _i, t in open_docs:
        subs = _subtasks(t)
        open_sub_total += len(subs)
        open_sub_done += sum(1 for s in subs if s.get("status") == STATUS_COMPLETED)

    weekly = progress["weeklyCompletion"]
    completion = {
        "totalTasks": len(task_docs),
        "completed": len(done_docs),
        "open": len(open_docs),
        "inProgress": in_progress,
        "notStarted": len(open_docs) - in_progress,
        "completionRate": progress["completionRate"],
        "openSubtasksDone": open_sub_done,
        "openSubtasksTotal": open_sub_total,
        "weeklyCompletion": list(weekly),
        "weeklyChange": progress["weeklyChange"],
        "weeklyChangeKnown": weekly[2] > 0,  # false when last week had no completions: a change cannot be calculated
    }

    # ---- Deadlines (open tasks only) ----
    buckets = {"overdue": 0, "dueToday": 0, "dueIn1To3": 0, "dueIn4To7": 0, "dueLater": 0}
    per_day = [0] * HORIZON_DAYS
    no_valid_deadline = 0
    dated_open = []  # (deadline, -importance, task_id, task, days)
    for task_id, t in open_docs:
        deadline = safe_date(t.get("deadline"))
        if deadline is None:
            no_valid_deadline += 1
            continue
        days = (deadline - today).days
        dated_open.append((deadline, -_IMPORTANCE_RANK.get(t.get("importance"), 0), task_id, t, days))
        if days < 0:
            buckets["overdue"] += 1
        elif days == 0:
            buckets["dueToday"] += 1
        elif days <= SOON_DAYS:
            buckets["dueIn1To3"] += 1
        elif days <= 7:
            buckets["dueIn4To7"] += 1
        else:
            buckets["dueLater"] += 1
        if 0 <= days < HORIZON_DAYS:
            per_day[days] += 1

    # One boundary for both heavy conditions: open tasks due today through today + SOON_DAYS (the same tasks that the
    # dueToday and dueIn1To3 buckets hold). Overdue tasks are counted separately and are never part of this number.
    due_soon = buckets["dueToday"] + buckets["dueIn1To3"]
    heavy_reason = None
    if due_soon >= HEAVY_SOON_TASKS:
        heavy_reason = "cluster"
    elif buckets["overdue"] >= 1 and due_soon >= HEAVY_OVERDUE_SOON_TASKS:
        heavy_reason = "overdue_plus_soon"
    peak = max(per_day)
    deadlines = {
        **buckets,
        "dueWithin7Days": buckets["dueToday"] + buckets["dueIn1To3"] + buckets["dueIn4To7"],
        "noValidDeadline": no_valid_deadline,
        "perDay": per_day,
        "peakDayOffset": per_day.index(peak) if peak else None,
        "peakDayCount": peak,
        "soonDays": SOON_DAYS,
        "dueWithin3Days": due_soon,  # dueToday + dueIn1To3
        "heavy": heavy_reason is not None,
        "heavyReason": heavy_reason,
        "upcoming": [],  # filled below, once subjects have labels
    }

    # ---- Subject workload (open tasks only) ----
    groups = {}  # subject_id ("" = unknown) -> accumulator
    for task_id, t in open_docs:
        sid = t.get("subject_id") if t.get("subject_id") in names else ""
        g = groups.setdefault(sid, {"openTasks": 0, "overdue": 0, "highImportance": 0, "dueWithin7Days": 0,
                                    "remainingMinutes": 0, "unestimatedTasks": 0})
        g["openTasks"] += 1
        if t.get("importance") == "high":
            g["highImportance"] += 1
        deadline = safe_date(t.get("deadline"))
        if deadline is not None:
            days = (deadline - today).days
            if days < 0:
                g["overdue"] += 1
            elif days <= 7:
                g["dueWithin7Days"] += 1
        subs = _subtasks(t)
        if subs:
            g["remainingMinutes"] += sum(_minutes(s) for s in subs if s.get("status") != STATUS_COMPLETED)
        else:
            g["unestimatedTasks"] += 1  # no subtasks means no estimate; never guessed
    ranked = sorted(groups.items(), key=lambda kv: (-kv[1]["openTasks"], names.get(kv[0], UNKNOWN_SUBJECT).casefold(), kv[0]))
    shown, hidden = ranked[:MAX_SUBJECT_ROWS], ranked[MAX_SUBJECT_ROWS:]
    label_of, rows = {}, []
    for n, (sid, g) in enumerate(shown, start=1):
        label_of[sid] = f"S{n}"
        rows.append({"label": f"S{n}", "subjectId": sid, "name": names.get(sid, UNKNOWN_SUBJECT),
                     "openTasks": g["openTasks"], "sharePct": _pct(g["openTasks"], len(open_docs)),
                     **{k: g[k] for k in ("overdue", "highImportance", "dueWithin7Days", "remainingMinutes", "unestimatedTasks")}})
    top_share = rows[0]["sharePct"] if rows else 0
    workload = {
        "openTasks": len(open_docs),
        "subjects": rows,
        "otherSubjects": {"count": len(hidden), "openTasks": sum(g["openTasks"] for _s, g in hidden)},
        "remainingMinutesTotal": sum(g["remainingMinutes"] for g in groups.values()),
        "unestimatedTasksTotal": sum(g["unestimatedTasks"] for g in groups.values()),
        "topSubjectShare": top_share,
        "concentrated": bool(rows) and len(open_docs) >= CONCENTRATION_MIN_OPEN and top_share >= CONCENTRATION_PCT,
    }

    dated_open.sort(key=lambda x: (x[0], x[1], x[2]))
    for n, (_deadline, _imp, _tid, t, days) in enumerate(dated_open[:MAX_UPCOMING], start=1):
        sid = t.get("subject_id") if t.get("subject_id") in names else ""
        deadlines["upcoming"].append({"label": f"T{n}", "title": str(t.get("title", "")), "subjectLabel": label_of.get(sid),
                                      "daysUntil": days, "importance": t.get("importance", "medium")})

    # ---- Productivity patterns (completed tasks only; see the module notes) ----
    finished_days, margins = [], []
    for _i, t in done_docs:
        finished = safe_date(t.get("completed_on"))
        if finished is None:
            continue
        finished_days.append(finished)
        deadline = safe_date(t.get("deadline"))
        if deadline is not None:
            margins.append((deadline - finished).days)  # positive = finished early, negative = late
    weekday_counts = [0] * 7
    for day in finished_days:
        weekday_counts[day.weekday()] += 1
    enough_margin = len(margins) >= MIN_PATTERN_COMPLETIONS
    weekday_pattern = None
    if len(finished_days) >= MIN_WEEKDAY_COMPLETIONS:
        top = sorted(weekday_counts, reverse=True)
        if top[0] >= MIN_WEEKDAY_TOP and top[0] > top[1]:  # a tie for first place is not a pattern
            weekday_pattern = {"weekday": weekday_counts.index(top[0]), "count": top[0],
                               "sharePct": _pct(top[0], len(finished_days))}
    patterns = {
        "completedTotal": len(done_docs),
        "completedWithDate": len(finished_days),
        "completedWithDateAndDeadline": len(margins),
        "minForPatterns": MIN_PATTERN_COMPLETIONS,
        "minForWeekday": MIN_WEEKDAY_COMPLETIONS,
        "enoughForPatterns": enough_margin,
        "onTimeRate": _pct(sum(1 for m in margins if m >= 0), len(margins)) if enough_margin else None,
        "lateSharePct": _pct(sum(1 for m in margins if m < 0), len(margins)) if enough_margin else None,
        "lastMinuteSharePct": (_pct(sum(1 for m in margins if 0 <= m <= LAST_MINUTE_MARGIN_DAYS), len(margins))
                               if enough_margin else None),
        "medianDaysBeforeDeadline": statistics.median_low(margins) if enough_margin else None,
        "weekdayCounts": weekday_counts,
        "weekdayPattern": weekday_pattern,
    }

    data_quality = {
        "completedWithoutDate": len(done_docs) - len(finished_days),
        "openWithoutValidDeadline": no_valid_deadline,
        "notes": [DATE_DISCLOSURE, HISTORY_DISCLOSURE],
    }
    return {"asOf": today.isoformat(), "completion": completion, "workload": workload, "deadlines": deadlines,
            "patterns": patterns, "dataQuality": data_quality}


def flatten_facts(facts):
    """{dotted.path: number} for every numeric fact, so a later step can check a claim against the ONE fact it is about
    (for example "deadlines.overdue" or "workload.subjects.S1.openTasks"), not merely against any number that happens to exist.
    Lists of items that have a "label" are addressed by label; other lists by position. Booleans, None and text are skipped."""
    out = {}

    def walk(value, path):
        if isinstance(value, bool) or value is None or isinstance(value, str):
            return
        if isinstance(value, (int, float)):
            out[path] = value
        elif isinstance(value, dict):
            for key, item in value.items():
                walk(item, f"{path}.{key}" if path else str(key))
        elif isinstance(value, list):
            for index, item in enumerate(value):
                key = item["label"] if isinstance(item, dict) and isinstance(item.get("label"), str) else str(index)
                walk(item, f"{path}.{key}")

    walk(facts, "")
    return out


# ---- Rule-based wording (no model) ----
def _n(count, singular, plural=None):
    return f"{count} {singular if count == 1 else (plural or singular + 's')}"


def _completion_text(f):
    c = f["completion"]
    text = (f"{c['completed']} of {_n(c['totalTasks'], 'task')} completed ({c['completionRate']}%); "
            f"{c['open']} open ({c['inProgress']} in progress, {c['notStarted']} not started).")
    if c["openSubtasksTotal"]:
        text += f" On open tasks, {c['openSubtasksDone']} of {_n(c['openSubtasksTotal'], 'subtask')} are done."
    w = c["weeklyCompletion"]
    if c["weeklyChangeKnown"]:
        direction = "up" if c["weeklyChange"] > 0 else "down" if c["weeklyChange"] < 0 else "unchanged"
        text += (f" This week {_n(w[3], 'task')} completed against {w[2]} last week"
                 + (f" ({direction} {abs(c['weeklyChange'])}%)." if direction != "unchanged" else " (unchanged)."))
    elif sum(w):
        text += f" Completed in the last 4 weeks, oldest first: {', '.join(str(x) for x in w)}."
    return text


def _workload_text(f):
    w = f["workload"]
    if not w["openTasks"]:
        return "You have no open tasks, so there is no workload to spread across subjects."
    parts = [f"{r['name']} {r['openTasks']} ({r['sharePct']}%)" for r in w["subjects"][:4]]
    text = f"Open tasks by subject: {'; '.join(parts)}."
    if w["concentrated"]:
        top = w["subjects"][0]
        text += f" Most of your open work ({top['sharePct']}%) is in {top['name']}."
    if w["remainingMinutesTotal"]:
        text += f" Subtasks still to do add up to about {w['remainingMinutesTotal']} minutes."
    if w["unestimatedTasksTotal"]:
        text += (f" {_n(w['unestimatedTasksTotal'], 'open task')} {'has' if w['unestimatedTasksTotal'] == 1 else 'have'} no "
                 "subtasks, so no time estimate is available for them.")
    return text


def _deadlines_text(f):
    d = f["deadlines"]
    if not f["workload"]["openTasks"]:
        return "You have no open tasks, so nothing is due."
    text = (f"{d['overdue']} overdue, {d['dueToday']} due today, {d['dueIn1To3']} due in the next 1 to 3 days, "
            f"{d['dueIn4To7']} due in 4 to 7 days.")
    if d["heavy"]:
        if d["heavyReason"] == "cluster":
            text += f" Heavy stretch: {_n(d['dueWithin3Days'], 'open task')} due within {d['soonDays']} days (counting today)."
        else:
            text += (f" Heavy stretch: you have {d['overdue']} overdue and {_n(d['dueWithin3Days'], 'open task')} "
                     f"due within {d['soonDays']} days (counting today).")
    else:
        text += " No heavy stretch: fewer than 3 open tasks are due within 3 days."
    if d["noValidDeadline"]:
        text += f" {_n(d['noValidDeadline'], 'open task')} could not be included because its deadline is missing or unreadable."
    return text


def _patterns_text(f):
    p = f["patterns"]
    if not p["enoughForPatterns"]:
        return (f"Not enough data yet to describe your patterns: {p['completedWithDateAndDeadline']} of the "
                f"{p['minForPatterns']} completed tasks needed that have a recorded completion day. {DATE_DISCLOSURE}")
    m = p["medianDaysBeforeDeadline"]
    when = (f"{m} day{'s' if m != 1 else ''} before the deadline" if m > 0 else "on the deadline day" if m == 0
            else f"{-m} day{'s' if m != -1 else ''} after the deadline")
    text = (f"Across {p['completedWithDateAndDeadline']} completed tasks, the typical task was marked complete {when}. "
            f"{p['onTimeRate']}% were marked complete on or before the deadline, {p['lateSharePct']}% after it, and "
            f"{p['lastMinuteSharePct']}% on the deadline day or the day before.")
    wp = p["weekdayPattern"]
    if wp:
        text += f" {wp['sharePct']}% of completions were marked on a {WEEKDAYS[wp['weekday']]}."
    return f"{text} {DATE_DISCLOSURE}"


def rule_based_insights(facts):
    """Plain-words insights from the facts alone: {summary, insights[{area, text}], suggestions[], notes[]}.
    One insight per area, always in AREAS order. At most 3 suggestions, each tied to a calculated fact."""
    c, w, d = facts["completion"], facts["workload"], facts["deadlines"]
    if c["totalTasks"] == 0:
        summary = "No tasks are recorded yet. Add tasks to see insights here."
    else:
        summary = (f"You have {c['open']} open and {c['completed']} completed task{'s' if c['completed'] != 1 else ''}; "
                   f"{d['overdue']} overdue and {d['dueWithin7Days']} due within the next 7 days.")
    texts = {"completion": _completion_text(facts), "workload": _workload_text(facts),
             "deadlines": _deadlines_text(facts), "patterns": _patterns_text(facts)}
    suggestions = []
    nearest = d["upcoming"][0] if d["upcoming"] else None
    if d["overdue"] and nearest and nearest["daysUntil"] < 0:
        suggestions.append({
            "area": "deadlines",
            "text": f"Start with \"{nearest['title']}\": it is the most overdue task you have open.",
        })
    elif d["heavy"]:
        suggestions.append({
            "area": "deadlines",
            "text": f"Several tasks are due within {d['soonDays']} days; consider starting the earliest one now.",
        })
    if w["concentrated"]:
        suggestions.append({
            "area": "workload",
            "text": f"Most of your open work is in {w['subjects'][0]['name']}; "
                    "check whether anything there can start earlier.",
        })
    if len(suggestions) < 3 and d["dueToday"]:
        suggestions.append({
            "area": "deadlines",
            "text": f"{_n(d['dueToday'], 'task')} due today. Finish or update {'it' if d['dueToday'] == 1 else 'them'} first.",
        })
    return {"summary": summary, "insights": [{"area": a, "text": texts[a]} for a in AREAS],
            "suggestions": suggestions[:3], "notes": list(facts["dataQuality"]["notes"])}
