// Phase 4.3 Planner Assistance tests (helpers, card behaviour against a tiny fake DOM, mock contract, wiring). Run from the project root:
//   node --test frontend/tests/plannerAssist.test.mjs
// No browser, jsdom, network, Firebase or AI provider is used.
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { api } from '../js/api/client.js';
import { seedV2, mockV2Request, mockPlannerAssist, MockHttpError } from '../js/api/mockData.js';
import { assistHtml, assistSource, validPlanAssist, mins, dayLabel, focusLabel } from '../js/plannerAssist.js';
import { ASSIST_CARD, wireAssist } from '../js/components/plannerAssist.js';

const src = f => readFileSync(new URL('../' + f, import.meta.url), 'utf8');
const XSS = '<img src=x onerror=alert(1)>';
const tick = () => new Promise(r => setTimeout(r, 0));
const real = (over = {}) => ({ ...mockPlannerAssist(), mock: false, ...over });

// ---------- helpers ----------
test('the demo sample passes the shape check and malformed answers do not', () => {
  assert.ok(validPlanAssist(mockPlannerAssist()));
  for (const bad of [null, [], {}, { summary: 'x' }, { ...mockPlannerAssist(), tips: 'no' }, { ...mockPlannerAssist(), capacity: { dailyMinutes: 'x' } },
    { ...mockPlannerAssist(), schedule: [{ date: 'd', capacityMinutes: 1, allocatedMinutes: 1, items: [{ title: 1, minutes: 1 }] }] },
    { ...mockPlannerAssist(), warnings: { overdueCount: 0, atRiskTasks: null, unscheduledTasks: [] } }, { ...mockPlannerAssist(), limitations: [1] }]) assert.equal(validPlanAssist(bad), false);
  assert.ok(validPlanAssist({ ...mockPlannerAssist(), nextTask: null, prioritizedTasks: [], tips: [] }));
});

test('AI is claimed only for a real answer with aiGenerated:true and a known source', () => {
  assert.equal(assistSource(mockPlannerAssist()).kind, 'demo');
  assert.equal(assistSource(real({ aiGenerated: true, source: 'groq' })).kind, 'groq');
  assert.match(assistSource(real({ aiGenerated: true, source: 'gemini' })).pill, /GOOGLE GEMINI/);
  for (const r of [real(), real({ aiGenerated: true, source: 'evil' }), real({ aiGenerated: 'true', source: 'groq' }), real({ aiGenerated: false, source: 'groq' }), null]) assert.equal(assistSource(r).kind, 'rule');
  assert.match(assistSource(real()).pill, /RULE-BASED/);
});

test('minutes and day labels', () => {
  assert.deepEqual([0, 45, 60, 90, 150].map(mins), ['0 min', '45 min', '1 h', '1 h 30 min', '2 h 30 min']);
  assert.equal(mins(NaN), '—'); assert.equal(mins('5'), '—');
  assert.match(dayLabel('2026-11-16'), /Mon/); assert.equal(dayLabel('garbage'), 'garbage');
  assert.equal(focusLabel('capacity'), 'Capacity'); assert.equal(focusLabel('constructor'), ''); assert.equal(focusLabel('x'), '');
});

test('rule-based result shows coaching, next task, schedule, priority order, limits; provisional estimates are badged', () => {
  const h = assistHtml(real());
  for (const w of ['RULE-BASED', 'Coaching note', 'WHAT TO WORK ON NEXT', 'Suggested schedule', 'Priority order', 'Time check', 'Good to know', 'not saved']) assert.ok(h.includes(w), w);
  assert.doesNotMatch(h, /AI coaching note/);
  assert.ok(h.includes('PROVISIONAL ESTIMATE')); assert.ok(h.includes('FROM SUBTASKS'));
  assert.ok(h.includes('worked out by TAiM, not by AI'));
});

test('AI result is labelled as coaching words only', () => {
  const h = assistHtml(real({ aiGenerated: true, source: 'groq', notice: 'Coaching note written by Groq.' }));
  assert.ok(h.includes('AI coaching note')); assert.ok(h.includes('AI COACHING NOTE · GROQ')); assert.match(h, /calculated by TAiM/);
});

test('warnings: overdue, over capacity, at risk and unscheduled tasks are all visible', () => {
  const r = real({ warnings: { overdueCount: 2, overloaded: true, overloadedDays: ['2026-11-01'], deficitMinutes: 90,
    atRiskTasks: [{ title: 'Risky', subjectName: 'M', message: 'Needs about 600 min' }], unscheduledTasks: [{ title: 'Undated', subjectName: 'M', message: 'It has no deadline, so TAiM did not place it in the schedule or guess a date.' }] } });
  const h = assistHtml(r);
  for (const w of ['2 overdue', 'Over capacity', '1 h 30 min', 'At risk', 'Risky', 'Not scheduled (no usable deadline)', 'Undated', 'guess a date']) assert.ok(h.includes(w), w);
  assert.equal(assistHtml(real()).includes('Over capacity'), false);
});

test('unscheduled tasks stay in the priority list, badged, with no invented date', () => {
  const r = real({ prioritizedTasks: [...mockPlannerAssist().prioritizedTasks, { taskId: 'u', title: 'No date task', subjectName: 'M', deadline: null, importance: 'low', status: 'not_started', remainingMinutes: 30, estimateSource: 'provisional', scheduled: false, reasons: ['No deadline is set'] }] });
  const h = assistHtml(r), li = h.slice(h.indexOf('No date task'));
  assert.ok(li.includes('NOT SCHEDULED')); assert.ok(li.includes('No deadline is set'));
});

test('empty account: friendly empty states, no crash', () => {
  const r = real({ nextTask: null, prioritizedTasks: [], tips: [], schedule: [], summary: 'You have no open tasks.', limitations: undefined });
  assert.ok(validPlanAssist(r)); const h = assistHtml(r);
  assert.ok(h.includes('No open tasks')); assert.ok(h.includes('You have no open tasks.'));
});

test('hostile text anywhere in a response is escaped', () => {
  const m = mockPlannerAssist(), t = { ...m.prioritizedTasks[0], title: XSS, subjectName: XSS, reasons: [XSS] };
  const r = real({ summary: XSS, notice: XSS, tips: [{ focus: 'next', text: XSS }], nextTask: t, prioritizedTasks: [t], limitations: [XSS],
    schedule: [{ ...m.schedule[0], date: XSS, items: [{ ...m.schedule[0].items[0], title: XSS, subjectName: XSS }] }],
    warnings: { overdueCount: 1, overloaded: true, overloadedDays: [XSS], deficitMinutes: 5, atRiskTasks: [{ title: XSS, subjectName: XSS, message: XSS }], unscheduledTasks: [{ title: XSS, subjectName: XSS, message: XSS }] } });
  const h = assistHtml(r);
  assert.doesNotMatch(h, /<img/); assert.ok(h.includes('&lt;img src=x onerror=alert(1)&gt;'));
  assert.doesNotMatch(assistHtml(real({ prioritizedTasks: [{ ...t, importance: '"><script>', estimateSource: '"><script>' }] })), /<script/);
});

test('bar widths are clamped numbers', () => {
  const m = mockPlannerAssist(), d = { ...m.schedule[0], allocatedMinutes: 9999, capacityMinutes: 120 };
  assert.match(assistHtml(real({ schedule: [d] })), /width:100%/);
  assert.match(assistHtml(real({ schedule: [{ ...d, allocatedMinutes: 0, capacityMinutes: 0 }] })), /width:0%/);
});

// ---------- the card against a fake DOM ----------
function setup() {
  const fresh = () => ({ innerHTML: '', textContent: '', className: '', checked: false, inert: false, onclick: null, value: '', classList: { add() {}, remove() {} } });
  const reg = {}; for (const id of ['pa', 'pa-out', 'pa-consent', 'pa-pill', 'pa-gen', 'pa-hours', 'pa-days']) reg['#' + id] = fresh();
  reg['#pa-hours'].value = '2'; reg['#pa-days'].value = '7';
  const el = { querySelector: s => reg[s] ?? null };
  const calls = [], respond = { next: async () => real() };
  api.getPlannerAssist = async b => { calls.push(b); return respond.next(b) };
  wireAssist(el); return { reg, calls, respond };
}

test('card: unticked sends aiConsent:false with numeric hours and days; result is shown as rule-based', async () => {
  const { reg, calls } = setup(); reg['#pa-hours'].value = '0.5'; reg['#pa-days'].value = '14';
  reg['#pa-gen'].onclick(); await tick();
  assert.deepEqual(calls, [{ hoursPerDay: 0.5, horizonDays: 14, aiConsent: false }]);
  assert.match(reg['#pa-pill'].textContent, /RULE-BASED/); assert.equal(reg['#pa-out'].className, 'ins-result'); assert.match(reg['#pa-out'].innerHTML, /Suggested schedule/);
});

test('card: ticked sends true, labels AI, and clears the box afterwards', async () => {
  const { reg, calls, respond } = setup();
  respond.next = async () => real({ aiGenerated: true, source: 'gemini' });
  reg['#pa-consent'].checked = true; reg['#pa-gen'].onclick(); await tick();
  assert.equal(calls[0].aiConsent, true); assert.equal(reg['#pa-consent'].checked, false); assert.match(reg['#pa-pill'].textContent, /GOOGLE GEMINI/);
  reg['#pa-gen'].onclick(); await tick(); assert.equal(calls[1].aiConsent, false);
});

test('card: a second click while pending sends nothing; the card is locked then released', async () => {
  const { reg, calls, respond } = setup(); let release;
  respond.next = () => new Promise(r => { release = () => r(real()) });
  reg['#pa-gen'].onclick(); await tick();
  assert.equal(reg['#pa-out'].textContent, 'Planning…'); assert.equal(reg['#pa'].inert, true);
  reg['#pa-gen'].onclick(); reg['#pa-gen'].onclick(); await tick(); assert.equal(calls.length, 1);
  release(); await tick(); assert.equal(reg['#pa'].inert, false);
  reg['#pa-gen'].onclick(); await tick(); assert.equal(calls.length, 2);
});

test('card: errors show as plain text, the box is cleared, and malformed answers are never half-drawn', async () => {
  const { reg, respond } = setup();
  respond.next = async () => { throw new Error(`Server says ${XSS}`) };
  reg['#pa-consent'].checked = true; reg['#pa-gen'].onclick(); await tick();
  assert.equal(reg['#pa-out'].className, 'state err'); assert.equal(reg['#pa-out'].textContent, `Server says ${XSS}`); assert.equal(reg['#pa-out'].innerHTML, ''); assert.equal(reg['#pa-consent'].checked, false);
  respond.next = async () => { throw {} }; reg['#pa-gen'].onclick(); await tick(); assert.equal(reg['#pa-out'].textContent, 'The plan could not be generated.');
  for (const bad of [null, {}, { ...mockPlannerAssist(), capacity: null }]) { respond.next = async () => bad; reg['#pa-out'].innerHTML = ''; reg['#pa-gen'].onclick(); await tick();
    assert.match(reg['#pa-out'].textContent, /unexpected answer/); assert.equal(reg['#pa-out'].innerHTML, ''); }
});

test('card: wiring tolerates a page without the card', () => { assert.doesNotThrow(() => wireAssist({ querySelector: () => null })); });

// ---------- mock contract and wiring ----------
test('mock v2 route: same consent contract as the server, answers a labelled demo sample', () => {
  const db = seedV2(), ctx = { todayIso: '2026-11-16' };
  for (const bad of ['yes', 1, null]) assert.throws(() => mockV2Request(db, 'POST', '/ai/planner-assist', { aiConsent: bad }, ctx), e => e instanceof MockHttpError && e.status === 422);
  assert.throws(() => mockV2Request(db, 'POST', '/ai/planner-assist', [], ctx), e => e instanceof MockHttpError && e.status === 400);
  const r = mockV2Request(db, 'POST', '/ai/planner-assist', { hoursPerDay: 2, horizonDays: 7, aiConsent: false }, ctx);
  assert.equal(r.mock, true); assert.equal(r.aiGenerated, false); assert.ok(validPlanAssist(r)); assert.match(assistHtml(r), /DEMO SAMPLE/);
});

test('wiring: client method, planner page card, no direct fetch, read-only, earlier phases intact', () => {
  assert.match(src('js/api/client.js'), /getPlannerAssist: b => req\('POST', '\/ai\/planner-assist', b\)/);
  assert.match(src('js/api/client.js'), /getInsights: b => req\('POST', '\/ai\/insights', b\)/);
  const p = src('js/pages/planner.js');
  assert.match(p, /\$\{ASSIST_CARD\}/); assert.match(p, /wireAssist\(el\)/); assert.match(p, /api\.planTask\(/);
  for (const f of ['js/components/plannerAssist.js', 'js/plannerAssist.js']) { assert.doesNotMatch(src(f), /\bfetch\s*\(/); assert.doesNotMatch(src(f), /createTask|updateTask|deleteTask|addSubtasks|localStorage/); }
  assert.match(ASSIST_CARD, /id="pa-consent"/); assert.doesNotMatch(ASSIST_CARD, /checked/);
  assert.match(ASSIST_CARD, /Task titles, subject names, your name, email, account identifiers, and calendar dates are never sent/);
});
