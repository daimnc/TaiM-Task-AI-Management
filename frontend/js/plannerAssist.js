// Phase 4.3: Planner Assistance helpers. Pure functions (no network, no DOM), so they run in Node tests.
// The server response is untrusted until validPlanAssist() passes, and every piece of text goes through esc().
import { esc } from './ui.js';

const AI_NAMES = { groq: 'Groq', gemini: 'Google Gemini', ai: 'an AI model' };
const FOCUS = { next: 'Next', overdue: 'Overdue', capacity: 'Capacity', deadlines: 'Deadlines', estimates: 'Estimates', balance: 'Balance' };
export const focusLabel = f => Object.hasOwn(FOCUS, f) ? FOCUS[f] : '';
export const IMPORTANCE = { high: 'High', medium: 'Medium', low: 'Low' };

// AI is claimed ONLY for a real (non-demo) answer that says aiGenerated:true with a known source. The AI only wrote the coaching words.
export const assistSource = r => {
  if (r && r.mock === true) return { kind: 'demo', pill: 'DEMO SAMPLE · NO AI MODEL USED', heading: 'Browser demo sample. Not calculated from your tasks and not AI-generated.', cls: '' };
  if (r && r.aiGenerated === true && Object.hasOwn(AI_NAMES, r.source)) return { kind: r.source, pill: `✦ AI COACHING NOTE · ${AI_NAMES[r.source].toUpperCase()}`, heading: `Coaching words by ${AI_NAMES[r.source]}. The schedule, order and numbers below were calculated by TAiM.`, cls: 'violet' };
  return { kind: 'rule', pill: 'RULE-BASED · NO AI MODEL USED', heading: 'Calculated and written by TAiM. Not AI-generated.', cls: 'st-not_started' };
};

const isObj = v => v !== null && typeof v === 'object' && !Array.isArray(v);
const isNum = v => typeof v === 'number' && Number.isFinite(v);
const texts = a => Array.isArray(a) && a.every(x => typeof x === 'string');
const rowsOk = (a, f) => Array.isArray(a) && a.every(x => isObj(x) && f(x));
export const validPlanAssist = r => isObj(r) && typeof r.summary === 'string' && rowsOk(r.tips, t => typeof t.text === 'string')
  && isObj(r.capacity) && ['dailyMinutes', 'horizonDays', 'totalAvailableMinutes', 'totalNeededMinutes', 'allocatedMinutes', 'unallocatedMinutes'].every(k => isNum(r.capacity[k]))
  && (r.nextTask === null || (isObj(r.nextTask) && typeof r.nextTask.title === 'string'))
  && rowsOk(r.prioritizedTasks, t => typeof t.title === 'string' && Array.isArray(t.reasons))
  && rowsOk(r.schedule, d => typeof d.date === 'string' && isNum(d.capacityMinutes) && isNum(d.allocatedMinutes) && rowsOk(d.items, i => typeof i.title === 'string' && isNum(i.minutes)))
  && isObj(r.warnings) && isNum(r.warnings.overdueCount) && rowsOk(r.warnings.atRiskTasks, t => typeof t.title === 'string') && rowsOk(r.warnings.unscheduledTasks, t => typeof t.title === 'string')
  && (r.limitations === undefined || texts(r.limitations));

export const mins = v => { if (!isNum(v)) return '—'; const m = Math.round(v), h = Math.floor(m / 60), r = m % 60; return h ? (r ? `${h} h ${r} min` : `${h} h`) : `${m} min`; };
export const dayLabel = s => { const d = new Date(String(s) + 'T00:00:00'); return Number.isNaN(d.getTime()) ? String(s) : d.toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' }) };
const pct = (a, b) => isNum(a) && isNum(b) && b > 0 ? Math.min(Math.max(Math.round(a / b * 100), 0), 100) : 0;
const estimate = t => t.estimateSource === 'provisional' ? `<span class="pill st-not_started" title="A rough guess, not a measurement of the work left">PROVISIONAL ESTIMATE</span>` : t.estimateSource === 'subtasks' ? `<span class="pill st-completed" title="Added up from your unfinished subtasks">FROM SUBTASKS</span>` : '';
const imp = i => Object.hasOwn(IMPORTANCE, i) ? `<span class="pill ${i}">${IMPORTANCE[i]}</span>` : '';

export function warningsHtml(w, cap) {
  const out = [];
  if (w.overdueCount > 0) out.push(`<p class="warnbox"><b>${esc(w.overdueCount)} overdue</b> task${w.overdueCount === 1 ? '' : 's'}: catch-up work is placed first in the schedule.</p>`);
  if (w.overloaded) out.push(`<p class="warnbox"><b>Over capacity.</b> About ${esc(mins(w.deficitMinutes))} of work due in this period cannot fit in the time you set aside${Array.isArray(w.overloadedDays) && w.overloadedDays.length ? ` (full days: ${esc(w.overloadedDays.map(dayLabel).join(', '))})` : ''}.</p>`);
  if (w.atRiskTasks.length) out.push(`<div class="warnbox"><b>At risk</b><ul class="pa-list">${w.atRiskTasks.map(t => `<li><b>${esc(t.title)}</b> <small>${esc(t.subjectName)}</small><br>${esc(t.message ?? '')}</li>`).join('')}</ul></div>`);
  if (w.unscheduledTasks.length) out.push(`<div class="warnbox"><b>Not scheduled (no usable deadline)</b><ul class="pa-list">${w.unscheduledTasks.map(t => `<li><b>${esc(t.title)}</b> <small>${esc(t.subjectName)}</small><br>${esc(t.message ?? '')}</li>`).join('')}</ul></div>`);
  return out.join('');
}

export const nextHtml = t => t ? `<div class="pa-next"><small class="tag">WHAT TO WORK ON NEXT</small><h4>${esc(t.title)}</h4><p class="hint">${esc(t.subjectName ?? '')}${t.deadline ? ` · due ${esc(dayLabel(t.deadline))}` : ''}</p>
  <p>${imp(t.importance)} ${estimate(t)} <span class="mut">about ${esc(mins(t.remainingMinutes))} left</span></p>${Array.isArray(t.reasons) && t.reasons.length ? `<ul class="pa-list">${t.reasons.map(x => `<li>${esc(x)}</li>`).join('')}</ul>` : ''}</div>`
  : '<div class="state">No open tasks. Nothing to plan.</div>';

export const capacityHtml = c => `<dl class="facts">${[['Available (all days)', mins(c.totalAvailableMinutes)], ['Needed (dated tasks)', mins(c.totalNeededMinutes)], ['Placed in the schedule', mins(c.allocatedMinutes)], ['Not placed in this period', mins(c.unallocatedMinutes)]]
  .map(([k, v]) => `<div><dt>${esc(k)}</dt><dd>${esc(v)}</dd></div>`).join('')}</dl>`;

export const scheduleHtml = days => days.map(d => `<div class="pa-day${d.overloaded ? ' over' : ''}"><div class="pa-dayhead"><b>${esc(dayLabel(d.date))}</b><small>${esc(mins(d.allocatedMinutes))} of ${esc(mins(d.capacityMinutes))}${d.overloaded ? ' · full, work is left over' : ''}</small></div>
  <div class="pa-bar" role="img" aria-label="${pct(d.allocatedMinutes, d.capacityMinutes)}% of the day's time used"><i style="width:${pct(d.allocatedMinutes, d.capacityMinutes)}%"></i></div>
  ${d.items.length ? `<ul class="pa-list">${d.items.map(i => `<li><span class="pa-min">${esc(mins(i.minutes))}</span> ${esc(i.title)} <small>${esc(i.subjectName ?? '')}</small> ${estimate(i)}${i.overdue ? ' <span class="pill high">OVERDUE</span>' : ''}</li>`).join('')}</ul>` : '<p class="hint">Nothing planned.</p>'}</div>`).join('');

export const priorityHtml = ts => ts.length ? `<ol class="pa-order">${ts.map(t => `<li><b>${esc(t.title)}</b> ${imp(t.importance)} ${estimate(t)}${t.scheduled === false ? ' <span class="pill st-not_started">NOT SCHEDULED</span>' : ''}<br><small class="mut">${esc((t.reasons || []).join(' · '))}</small></li>`).join('')}</ol>` : '<p class="hint">No open tasks.</p>';

// Full result: source label, coaching words, warnings, next task, capacity, schedule, priority order, limits.
export function assistHtml(r) {
  const s = assistSource(r), ai = s.kind === 'groq' || s.kind === 'gemini' || s.kind === 'ai';
  const tips = r.tips.map(t => `<li>${focusLabel(t.focus) ? `<small class="tag">${esc(focusLabel(t.focus))}</small>` : ''}<span class="tip-text">${esc(t.text)}</span></li>`).join('');
  const limits = (r.limitations || []).map(x => `<li>${esc(x)}</li>`).join('');
  return `<p class="srcline ${esc(s.kind)}"><span class="pill ${esc(s.cls)}">${esc(s.pill)}</span> <b>${esc(s.heading)}</b></p>${r.notice ? `<p class="hint">${esc(r.notice)}</p>` : ''}`
    + `<div class="ins-block ${ai ? 'ai' : 'plain'}"><h4>${ai ? 'AI coaching note' : 'Coaching note'}</h4><p class="ins-sum">${esc(r.summary)}</p>${tips ? `<ul class="tip-list">${tips}</ul>` : ''}</div>`
    + warningsHtml(r.warnings, r.capacity)
    + `<div class="ins-block">${nextHtml(r.nextTask)}</div>`
    + `<div class="ins-block facts-block"><h4>Time check <small class="tag">worked out by TAiM, not by AI</small></h4>${capacityHtml(r.capacity)}</div>`
    + `<div class="ins-block"><h4>Suggested schedule <small class="tag">${esc(r.capacity.horizonDays)} day${r.capacity.horizonDays === 1 ? '' : 's'}, up to ${esc(mins(r.capacity.dailyMinutes))} a day</small></h4>${scheduleHtml(r.schedule)}</div>`
    + `<div class="ins-block"><h4>Priority order</h4>${priorityHtml(r.prioritizedTasks)}</div>`
    + (limits ? `<div class="ins-block"><h4>Good to know</h4><ul class="lim-list">${limits}</ul></div>` : '')
    + '<div class="note">This is a suggested plan based on the tasks and time you entered. It is not saved and does not change your tasks.</div>';
}
