import { api, auth } from '../api/client.js';
import { load, esc, bars, fmtDate, dueText, topOpenTask, sortByDue, importancePill, categoryLabel, subjectName, isCompleted, empty, today, iso } from '../ui.js';
import { taskCounts } from '../taskStats.js';
const greet = () => { const h = new Date().getHours(); return h < 12 ? 'Good morning' : h < 18 ? 'Good afternoon' : 'Good evening' };
export default {
    title: 'Dashboard', render(el) {
        load(el, () => Promise.all([api.getTasks(), api.getProgress(), api.getSettings(), api.getSubjects()]), ([tasks, p, s, subjects]) => {
            const c = taskCounts(tasks, iso(today())), act = sortByDue(tasks.filter(t => !isCompleted(t))), pick = topOpenTask(tasks), mins = s.sessionMinutes;
            const stat = (l, v, sub, cls = '') => `<div class="card stat ${cls}"><span class="mut">${l}</span><b>${v}</b><span class="mut">${sub}</span></div>`;
            const change = p.weeklyChange >= 0 ? `↑ ${p.weeklyChange}%` : `↓ ${Math.abs(p.weeklyChange)}%`;
            el.innerHTML = `<section class="hero"><h2>${greet()}, ${esc(auth.user?.name || 'Student')} 👋</h2><p>Your academic workload is organized. Let's make today productive.</p></section>
 <div class="stats">${stat('Active Tasks', c.open, 'Not completed')}${stat('Due Soon', c.dueSoon, 'Today to 3 days')}${stat('Overdue', c.overdue, 'Past the deadline', c.overdue ? 'warn' : '')}${stat('Completed', p.completed, 'Tasks completed')}</div>
 <div class="grid2"><div class="col">
  <div class="card ai"><span class="pill violet">✦ PRIORITY SUGGESTION · RULE-BASED</span>${pick ? `<h3>Start with your ${esc(pick.title)}</h3><p>${dueText(pick.deadline)} with ${pick.progress_pct}% recorded progress. Try a ${mins}-minute session today.</p><a class="btn primary" href="#/planner?task=${encodeURIComponent(pick.task_id)}">Plan this task</a> <a class="btn" href="#/pomodoro?task=${encodeURIComponent(pick.task_id)}">Start focus timer</a>` : `<h3>All caught up</h3><p>No open tasks.</p>`}</div>
  <div class="card"><h3>Upcoming Tasks</h3>${act.slice(0, 4).map(t => `<div class="item row"><div><b>${esc(t.title)}</b><small>${esc(categoryLabel(t.category))} · ${esc(subjectName(subjects, t.subject_id))} · Due ${fmtDate(t.deadline)}</small></div>${importancePill(t.importance)}</div>`).join('') || empty('No upcoming tasks')}</div>
 </div><div class="col">
  <div class="card"><h3>Weekly Productivity</h3>${bars(p.weeklyProductivity, ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'])}<p class="hint">Completion rate ${p.completionRate}% · ${change} from last week</p></div>
  <div class="card"><h3>Focus for Today</h3>${act.slice(0, 3).map((t, i) => `<div class="item"><b>${i + 1}. ${esc(t.title)}</b><small>${dueText(t.deadline)} · ${mins} minutes</small></div>`).join('') || empty('Nothing to focus on')}</div>
 </div></div>`})
    }
};
