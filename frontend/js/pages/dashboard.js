import { api, auth } from '../api/client.js';
import { load, esc, bars, fmtDate, dueText, daysUntil, isDone, topPick, sortByDue, pill, empty } from '../ui.js';
export default {
    title: 'Dashboard', render(el) {
        load(el, () => Promise.all([api.getTasks(), api.getProgress()]), ([tasks, p]) => {
            const act = sortByDue(tasks.filter(t => !isDone(t))), pick = topPick(tasks), soon = act.filter(t => daysUntil(t.deadline) <= 3).length;
            const stat = (l, v, s) => `<div class="card stat"><span class="mut">${l}</span><b>${v}</b><span class="mut">${s}</span></div>`;
            el.innerHTML = `<section class="hero"><h2>Good morning, ${esc(auth.user?.name || 'Student')} 👋</h2><p>Your academic workload is organized. Let's make today productive.</p></section>
 <div class="stats">${stat('Active Tasks', act.length, 'Currently in progress')}${stat('Completed', p.completed, 'This semester')}${stat('Due Soon', soon, 'Within 3 days')}${stat('Weekly Progress', p.completionRate + '%', '↑ ' + p.weeklyChange + '% from last week')}</div>
 <div class="grid2"><div class="col">
  <div class="card ai"><span class="pill violet">✦ AI PRIORITY RECOMMENDATION · DEMO</span>${pick ? `<h3>Start with your ${esc(pick.title)}</h3><p>${dueText(pick.deadline)} with ${pick.progress}% recorded progress. Try a 25-minute session today.</p><a class="btn primary" href="#/planner?task=${pick.id}">Plan this task</a>` : `<h3>All caught up</h3><p>No open tasks.</p>`}</div>
  <div class="card"><h3>Upcoming Tasks</h3>${act.slice(0, 4).map(t => `<div class="item row"><div><b>${esc(t.title)}</b><small>${esc(t.category)} · Due ${fmtDate(t.deadline)}</small></div>${pill(t.priority)}</div>`).join('') || empty('No upcoming tasks')}</div>
 </div><div class="col">
  <div class="card"><h3>Weekly Productivity</h3>${bars(p.weeklyProductivity, ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'])}</div>
  <div class="card"><h3>AI Focus for Today</h3>${act.slice(0, 3).map((t, i) => `<div class="item"><b>${i + 1}. ${esc(t.title)}</b><small>${dueText(t.deadline)} · ${t.progress < 50 ? 25 : 45} minutes</small></div>`).join('') || empty('Nothing to focus on')}</div>
 </div></div>`})
    }
};
