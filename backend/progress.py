"""Progress statistics, calculated only from the student's stored tasks.

No history is invented. What each number means:
  completed         tasks whose status is "completed" (status is authoritative, not the progress number)
  completionRate    completed / all tasks, as a percentage (0 when there are no tasks)
  overdue           tasks that are not completed (including in_progress at 100%) whose deadline is before today
  onTimeRate        of the completed tasks that have a recorded completion day (completed_on), the percentage finished
                    on or before their deadline (0 when none are recorded). The server saves completed_on when a task
                    is completed, so tasks without it (e.g. finished before it existed) are skipped.
  weeklyProductivity  tasks completed on each day of the current week, Monday first (the frontend labels Mon..Sun)
  weeklyCompletion    tasks completed in each of the last 4 weeks (Monday-Sunday), oldest first, current week last
  weeklyChange        percentage change between the last two weeks of weeklyCompletion (0 when last week had none)
"""
from collections import Counter
from datetime import timedelta

from dates import safe_date
from validation import STATUS_COMPLETED


def _percent(part, whole):
    return (part * 100 + whole // 2) // whole if whole else 0


def _insight(total, open_count, overdue_tasks, completed):
    if total == 0:
        return "No tasks are recorded yet. Add tasks to see your statistics and a summary here."
    text = f"Summary of your recorded tasks: {open_count} open, {len(overdue_tasks)} overdue, {completed} completed."
    if overdue_tasks:
        category = Counter(t.get("category", "other") for t in overdue_tasks).most_common(1)[0][0]
        text += f" Most overdue tasks are in the {category} category."
    elif open_count:
        text += " None of your open tasks is overdue."
    return text + " This is a rule-based summary, not AI-generated."


def build_progress(task_docs, today):
    tasks = [data for _task_id, data in task_docs]
    done = [t for t in tasks if t.get("status") == STATUS_COMPLETED]
    open_tasks = [t for t in tasks if t.get("status") != STATUS_COMPLETED]
    overdue_tasks = []
    for t in open_tasks:
        deadline = safe_date(t.get("deadline"))
        if deadline is not None and deadline < today:
            overdue_tasks.append(t)

    on_time = known = 0
    completed_days = []
    for t in done:
        finished = safe_date(t.get("completed_on"))
        if finished is None:
            continue
        completed_days.append(finished)
        deadline = safe_date(t.get("deadline"))
        if deadline is not None:
            known += 1
            on_time += finished <= deadline

    monday = today - timedelta(days=today.weekday())
    weekly_productivity = [0] * 7
    for day in completed_days:
        offset = (day - monday).days
        if 0 <= offset <= 6:
            weekly_productivity[offset] += 1

    weekly_completion = []
    for weeks_ago in (3, 2, 1, 0):
        start = monday - timedelta(days=7 * weeks_ago)
        weekly_completion.append(sum(1 for d in completed_days if 0 <= (d - start).days <= 6))
    last_week, this_week = weekly_completion[2], weekly_completion[3]
    weekly_change = round((this_week - last_week) * 100 / last_week) if last_week else 0

    return {
        "completionRate": _percent(len(done), len(tasks)),
        "onTimeRate": _percent(on_time, known),
        "completed": len(done),
        "overdue": len(overdue_tasks),
        "weeklyChange": weekly_change,
        "weeklyProductivity": weekly_productivity,
        "weeklyCompletion": weekly_completion,
        "insight": _insight(len(tasks), len(open_tasks), overdue_tasks, len(done)),
        "insightSource": "rule-based",
    }
