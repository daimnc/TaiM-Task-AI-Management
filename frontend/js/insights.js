// Phase 4.2: AI Insights card helpers. Pure functions (no network, no DOM), so they run in Node tests.
// Every piece of text that reaches the page goes through esc(). The response is treated as untrusted until validInsights() passes.
import { esc } from './ui.js';

export const INSIGHT_AREAS = { completion: 'Completion', workload: 'Workload', deadlines: 'Deadlines', patterns: 'Patterns' };
export const areaLabel = a => Object.hasOwn(INSIGHT_AREAS, a) ? INSIGHT_AREAS[a] : '';
const AI_NAMES = { groq: 'Groq', gemini: 'Google Gemini', ai: 'an AI model' };

// What produced this answer. AI is claimed ONLY for a real (non-demo) response that says aiGenerated:true with a known source.
export const insightSource = r => {
  if (r && r.mock === true) return { kind: 'demo', pill: 'DEMO SAMPLE · NO AI MODEL USED', heading: 'Browser demo sample. Not calculated from your tasks and not AI-generated.', cls: '' };
  if (r && r.aiGenerated === true && Object.hasOwn(AI_NAMES, r.source)) {
    return { kind: r.source, pill: `✦ AI-GENERATED · ${AI_NAMES[r.source].toUpperCase()}`, heading: `AI interpretation by ${AI_NAMES[r.source]}. Review it with the calculated facts below.`, cls: 'violet' };
  }
  return { kind: 'rule', pill: 'RULE-BASED · NO AI MODEL USED', heading: 'Written by TAiM from your calculated numbers. Not AI-generated.', cls: 'st-not_started' };
};

const isObj = v => v !== null && typeof v === 'object' && !Array.isArray(v);
// Shape check before rendering anything. A response that fails it is shown as an error, never half-drawn.
export const validInsights = r => isObj(r) && typeof r.summary === 'string' && Array.isArray(r.insights) && Array.isArray(r.suggestions)
  && isObj(r.facts) && isObj(r.facts.completion) && isObj(r.facts.deadlines) && isObj(r.facts.workload) && isObj(r.facts.patterns)
  && r.insights.every(i => isObj(i) && typeof i.text === 'string') && r.suggestions.every(s => isObj(s) && typeof s.text === 'string')
  && (r.limitations === undefined || (Array.isArray(r.limitations) && r.limitations.every(x => typeof x === 'string')));

const n = v => typeof v === 'number' && Number.isFinite(v) ? String(v) : '—';

// The calculated facts as [{title, rows:[[label, value]]}]. Plain strings; escaped when drawn.
export function factSections(f) {
  const c = f?.completion || {}, d = f?.deadlines || {}, w = f?.workload || {}, p = f?.patterns || {};
  const weekly = Array.isArray(c.weeklyCompletion) ? c.weeklyCompletion.map(n).join(', ') : '—';
  const completion = [
    ['Tasks recorded', n(c.totalTasks)],
    ['Completed', `${n(c.completed)} (${n(c.completionRate)}%)`],
    ['Open', `${n(c.open)} (${n(c.inProgress)} in progress, ${n(c.notStarted)} not started)`],
    ...(c.openSubtasksTotal ? [['Subtasks done on open tasks', `${n(c.openSubtasksDone)} of ${n(c.openSubtasksTotal)}`]] : []),
    ['Completed in the last 4 weeks (oldest first)', weekly],
    ['Change from last week', c.weeklyChangeKnown ? `${c.weeklyChange > 0 ? '+' : ''}${n(c.weeklyChange)}%` : 'Not available (nothing was completed last week)'],
  ];
  const deadlines = [
    ['Overdue', n(d.overdue)], ['Due today', n(d.dueToday)], ['Due in 1 to 3 days', n(d.dueIn1To3)],
    ['Due in 4 to 7 days', n(d.dueIn4To7)], ['Due later', n(d.dueLater)],
    ...(d.noValidDeadline ? [['Missing or unreadable deadline', n(d.noValidDeadline)]] : []),
    ['Heavy stretch', d.heavy ? `Yes (${n(d.dueWithin3Days)} due within ${n(d.soonDays)} days${d.heavyReason === 'overdue_plus_soon' ? `, plus ${n(d.overdue)} overdue` : ''})` : 'No'],
  ];
  const subjects = Array.isArray(w.subjects) ? w.subjects : [];
  const workload = subjects.length ? [
    ...subjects.map(s => [String(s.name ?? 'Unknown subject'), `${n(s.openTasks)} open (${n(s.sharePct)}%) · ${n(s.overdue)} overdue · ${n(s.highImportance)} high importance` + (s.remainingMinutes ? ` · about ${n(s.remainingMinutes)} min of subtasks left` : '')]),
    ...(w.otherSubjects?.count ? [[`${n(w.otherSubjects.count)} other subjects`, `${n(w.otherSubjects.openTasks)} open`]] : []),
    ...(w.unestimatedTasksTotal ? [['Open tasks with no subtasks', `${n(w.unestimatedTasksTotal)} (no time estimate available)`]] : []),
  ] : [['Open tasks', 'None']];
  const patterns = p.enoughForPatterns ? [
    ['Completed tasks used', n(p.completedWithDateAndDeadline)],
    ['Marked complete on or before the deadline', `${n(p.onTimeRate)}%`], ['Marked complete after the deadline', `${n(p.lateSharePct)}%`],
    ['Marked complete on the deadline day or the day before', `${n(p.lastMinuteSharePct)}%`],
    ['Typical days before the deadline', n(p.medianDaysBeforeDeadline)],
    ...(p.weekdayPattern ? [['Most common weekday for marking complete', `${['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'][p.weekdayPattern.weekday] ?? '—'} (${n(p.weekdayPattern.sharePct)}%)`]] : []),
  ] : [['Not enough data yet', `${n(p.completedWithDateAndDeadline)} of ${n(p.minForPatterns)} completed tasks needed`]];
  return [{ title: 'Completion', rows: completion }, { title: 'Deadlines', rows: deadlines }, { title: 'Workload by subject', rows: workload }, { title: 'Patterns', rows: patterns }];
}

export const factsHtml = f => factSections(f).map(s => `<section><h5>${esc(s.title)}</h5><dl class="facts">${s.rows.map(([k, v]) => `<div><dt>${esc(k)}</dt><dd>${esc(v)}</dd></div>`).join('')}</dl></section>`).join('');

// Full result: source label, then the INTERPRETATION (AI or rule-based), then the separate CALCULATED FACTS, then limits.
export function insightsHtml(r) {
  const s = insightSource(r), ai = s.kind === 'groq' || s.kind === 'gemini' || s.kind === 'ai';
  const items = r.insights.map(i => `<li><b>${esc(areaLabel(i.area) || 'Insight')}</b><p>${esc(i.text)}</p></li>`).join('');
  const tips = r.suggestions.map(t => `<li>${areaLabel(t.area) ? `<small class="tag">${esc(areaLabel(t.area))}</small>` : ''}<span class="tip-text">${esc(t.text)}</span></li>`).join('');
  const limits = (r.limitations || []).map(x => `<li>${esc(x)}</li>`).join('');
  return `<p class="srcline ${esc(s.kind)}"><span class="pill ${esc(s.cls)}">${esc(s.pill)}</span> <b>${esc(s.heading)}</b></p>`
    + (r.notice ? `<p class="hint">${esc(r.notice)}</p>` : '')
    + `<div class="ins-block ${ai ? 'ai' : 'plain'}"><h4>${ai ? 'AI interpretation' : 'Insights'}</h4><p class="ins-sum">${esc(r.summary)}</p>`
    + (items ? `<ul class="ins-list">${items}</ul>` : '')
    + (tips ? `<h4>Suggestions</h4><ul class="tip-list">${tips}</ul>` : '') + '</div>'
    + `<div class="ins-block facts-block"><h4>Calculated facts <small class="tag">worked out by TAiM, not by AI</small></h4>${factsHtml(r.facts)}</div>`
    + (limits ? `<div class="ins-block"><h4>Good to know</h4><ul class="lim-list">${limits}</ul></div>` : '')
    + '<div class="note">Insights are suggestions based on task history entered into TAiM. They are not a diagnosis or judgment.</div>';
}
