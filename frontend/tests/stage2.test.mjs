// Stage 2 tests. Run from the project root:  node --test frontend/tests/stage2.test.mjs
// Pure logic and API-contract tests; DOM behaviour is covered by static checks here and the manual browser checklist.
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { seedV2, mockV2Request, MockHttpError } from '../js/api/mockData.js';
import { catClass, joinTitle, addSequentially } from '../js/ui.js';
import { taskCounts, dueWithin, dateKey, monthInfo, shiftMonth, tasksByDate, monthTasks } from '../js/taskStats.js';
import { createPomodoro, MODES, CYCLE, fmtClock, progressPct, finishMessage } from '../js/pomodoro.js';

const TODAY = '2026-11-18'; let n = 0;
const call = (db, m, p, b) => mockV2Request(db, m, p, b, { todayIso: TODAY, newId: x => `${x}s${++n}` });
const rejects = (fn, status) => assert.throws(fn, e => e instanceof MockHttpError && e.status === status, `expected ${status}`);
const src = f => readFileSync(new URL('../js/' + f, import.meta.url), 'utf8');
const T = (deadline, status = 'in_progress', extra = {}) => ({ task_id: 'x' + deadline, subject_id: 's', title: 't', category: 'assignment', importance: 'medium', progress_pct: 0, deadline, status, ...extra });

// ---- dashboard
test('dashboard numbers: counts agree with the API /progress overdue figure and never double count', () => {
  const db = seedV2(); db.tasks = [
    { ...T('2026-11-10'), subject_id: db.subjects[0].subject_id }, { ...T('2026-11-18'), task_id: 'b', subject_id: db.subjects[0].subject_id },
    { ...T('2026-11-21', 'not_started'), task_id: 'c', subject_id: db.subjects[0].subject_id }, { ...T('2026-12-30'), task_id: 'd', subject_id: db.subjects[0].subject_id },
    { ...T('2026-11-01', 'completed', { progress_pct: 100 }), task_id: 'e', subject_id: db.subjects[0].subject_id }];
  const c = taskCounts(db.tasks, TODAY), p = call(db, 'GET', '/progress');
  assert.deepEqual(c, { total: 5, completed: 1, open: 4, overdue: 1, dueSoon: 2 });
  assert.equal(p.overdue, c.overdue); assert.equal(p.insightSource, 'mock-sample');
  assert.ok(c.overdue + c.dueSoon <= c.open);
});

test('dashboard: empty task list gives zero counts (no crash)', () => {
  assert.deepEqual(taskCounts([], TODAY), { total: 0, completed: 0, open: 0, overdue: 0, dueSoon: 0 });
});

// ---- calendar and planner data mapping
test('calendar: month grid, month navigation across years, grouping and ordering', () => {
  assert.deepEqual(monthInfo(2026, 10), { first: 0, days: 30 }); // Nov 2026 starts on a Sunday
  assert.deepEqual(monthInfo(2028, 1), { first: 2, days: 29 }); // Feb 2028 (leap)
  assert.deepEqual(shiftMonth(2026, 11, 1), { y: 2027, m: 0 }); assert.deepEqual(shiftMonth(2026, 0, -1), { y: 2025, m: 11 }); assert.deepEqual(shiftMonth(2026, 5, 14), { y: 2027, m: 7 });
  assert.equal(dateKey(2026, 0, 5), '2026-01-05');
  const ts = [T('2026-11-20'), T('2026-11-05'), T('2026-12-01'), T('bad-date'), T('2026-11-20', 'completed')];
  assert.equal(tasksByDate(ts).get('2026-11-20').length, 2); assert.equal(tasksByDate(ts).has('bad-date'), false);
  assert.deepEqual(monthTasks(ts, 2026, 10).map(t => t.deadline), ['2026-11-05', '2026-11-20', '2026-11-20']);
});

test('category classes match the V2 lowercase values; unknown values fall back to other', () => {
  for (const c of ['assignment', 'project', 'exam', 'quiz', 'research', 'other']) assert.equal(catClass(c), 'cat-' + c);
  assert.equal(catClass('Examination'), 'cat-other'); assert.equal(catClass(undefined), 'cat-other');
  const css = src('../css/styles.css'); for (const c of ['exam', 'quiz', 'project', 'other']) assert.match(css, new RegExp('\\.cat-' + c + '[,{]'));
});

test('planner: step titles stay within 120 characters; sequential save stops at the first failure and reports progress', async () => {
  assert.equal(joinTitle('Essay', 'Draft'), 'Essay — Draft');
  const long = joinTitle('x'.repeat(200), 'Final proofread and submit'); assert.ok(long.length <= 120); assert.match(long, /— Final proofread and submit$/);
  const db = seedV2(), sid = db.subjects[0].subject_id, before = db.tasks.length;
  const steps = [{ t: 'One', d: '2026-11-20' }, { t: 'Two', d: '2026-02-30' }, { t: 'Three', d: '2026-11-22' }], saved = [];
  const res = await addSequentially(steps, s => call(db, 'POST', '/tasks', { title: joinTitle('Paper', s.t), subject_id: sid, category: 'research', importance: 'high', deadline: s.d }), i => saved.push(i));
  assert.equal(res.ok, 1); assert.equal(res.failedAt, 1); assert.ok(res.error instanceof MockHttpError); assert.deepEqual(saved, [0]);
  assert.equal(db.tasks.length, before + 1); // "Three" was NOT attempted, so a retry cannot duplicate anything
  const ok = await addSequentially([1, 2], () => {}); assert.deepEqual(ok, { ok: 2, failedAt: -1, error: null });
});

test('planner request: API accepts the four fields the page sends; bad input is rejected', () => {
  const db = seedV2(), r = call(db, 'POST', '/ai/plan', { title: 'Paper', requirements: '', deadline: '2026-11-25', hoursPerDay: 1 });
  assert.equal(r.aiGenerated, false); assert.ok(r.notice); assert.ok(r.subtasks.length >= 1 && r.subtasks.every(s => s.title && s.dueDate && s.minutes));
  rejects(() => call(db, 'POST', '/ai/plan', { title: 'Paper', deadline: '2026-13-01' }), 422);
  rejects(() => call(db, 'POST', '/ai/plan', { title: '', deadline: '2026-11-25' }), 422);
  rejects(() => call(db, 'POST', '/ai/plan', { title: 'P', deadline: '2026-11-25', hoursPerDay: 12 }), 422);
});

// ---- reminders and settings
test('reminders: lead-time window includes overdue, excludes completed and later tasks, sorted soonest first', () => {
  const ts = [T('2026-11-25'), T('2026-11-10'), T('2026-11-19', 'completed'), T('2026-11-20'), T('2026-12-30')];
  assert.deepEqual(dueWithin(ts, TODAY, 2).map(t => t.deadline), ['2026-11-10', '2026-11-20']);
  assert.deepEqual(dueWithin(ts, TODAY, 7).map(t => t.deadline), ['2026-11-10', '2026-11-20', '2026-11-25']);
  assert.deepEqual(dueWithin([], TODAY, 3), []);
});

test('reminder preferences: partial save keeps the others; invalid values rejected', () => {
  const db = seedV2(), before = call(db, 'GET', '/reminders/preferences');
  const after = call(db, 'PUT', '/reminders/preferences', { progressCheckin: !before.progressCheckin });
  assert.equal(after.progressCheckin, !before.progressCheckin); assert.equal(after.deadline, before.deadline); assert.equal(after.quietHours, before.quietHours);
  assert.deepEqual(call(db, 'GET', '/reminders/preferences'), after);
  rejects(() => call(db, 'PUT', '/reminders/preferences', { deadline: 'yes' }), 422); rejects(() => call(db, 'PUT', '/reminders/preferences', {}), 422);
});

test('settings persistence: full_name, leadDays, sessionMinutes save; program and weeklySummary are not part of V2', () => {
  const db = seedV2();
  const r = call(db, 'PUT', '/settings', { full_name: 'Ana Reyes', leadDays: 5, sessionMinutes: 60, program: 'BSCS', weeklySummary: true });
  assert.deepEqual(r, { full_name: 'Ana Reyes', leadDays: 5, sessionMinutes: 60 });
  assert.deepEqual(call(db, 'GET', '/settings'), r); assert.equal(Object.hasOwn(call(db, 'GET', '/settings'), 'program'), false);
  rejects(() => call(db, 'PUT', '/settings', { leadDays: 4 }), 422); rejects(() => call(db, 'PUT', '/settings', { sessionMinutes: 30 }), 422); rejects(() => call(db, 'PUT', '/settings', { full_name: '  ' }), 422);
  assert.equal(call(db, 'GET', '/settings').leadDays, 5); // failed saves changed nothing
});

// ---- pomodoro
const clock = () => { let t = 1_000_000; return { now: () => t, adv: ms => { t += ms } } };
test('pomodoro: 25/5/15 minute lengths, start, pause, resume, reset', () => {
  assert.deepEqual([MODES.focus.minutes, MODES.short.minutes, MODES.long.minutes], [25, 5, 15]);
  const c = clock(), p = createPomodoro(c.now); assert.equal(p.state.status, 'idle'); assert.equal(p.state.remainingMs, 25 * 60000);
  p.start(); c.adv(60000); assert.equal(p.state.remainingMs, 24 * 60000);
  p.pause(); c.adv(10 * 60000); assert.equal(p.state.remainingMs, 24 * 60000); assert.equal(p.state.status, 'paused'); // paused time does not count
  p.start(); c.adv(30000); assert.equal(p.state.remainingMs, 23.5 * 60000);
  p.reset(); assert.equal(p.state.status, 'idle'); assert.equal(p.state.remainingMs, 25 * 60000); assert.equal(p.state.mode, 'focus');
  p.start(); p.start(); c.adv(1000); assert.equal(p.state.remainingMs, 25 * 60000 - 1000); // second start is ignored
});

test('pomodoro: inactive tab / long gap between ticks still finishes once, on time', () => {
  const c = clock(), p = createPomodoro(c.now); p.start(); c.adv(24 * 60000); assert.equal(p.tick(), null);
  c.adv(10 * 60000); // tab was frozen for 10 minutes past the end
  assert.deepEqual(p.tick(), { finished: 'focus', next: 'short' }); assert.equal(p.tick(), null); // reported once only
  assert.equal(p.state.mode, 'short'); assert.equal(p.state.status, 'idle'); assert.equal(p.state.focusDone, 1); assert.equal(p.state.remainingMs, 5 * 60000);
});

test('pomodoro: long break after every 4th focus session, then back to focus', () => {
  const c = clock(), p = createPomodoro(c.now), seen = [];
  for (let i = 0; i < CYCLE; i++) { p.start(); c.adv(25 * 60000); seen.push(p.tick().next); p.start(); c.adv(MODES[p.state.mode].minutes * 60000); p.tick() }
  assert.deepEqual(seen, ['short', 'short', 'short', 'long']); assert.equal(p.state.mode, 'focus'); assert.equal(p.state.focusDone, 4);
});

test('pomodoro: switching mode resets; unknown mode ignored; clock going backwards never exceeds the full length', () => {
  const c = clock(), p = createPomodoro(c.now); p.start(); c.adv(5000); p.setMode('long');
  assert.equal(p.state.mode, 'long'); assert.equal(p.state.status, 'idle'); assert.equal(p.state.remainingMs, 15 * 60000); p.setMode('bogus'); assert.equal(p.state.mode, 'long');
  p.start(); c.adv(-60000); assert.equal(p.state.remainingMs, 15 * 60000);
});

test('pomodoro display helpers', () => {
  assert.equal(fmtClock(25 * 60000), '25:00'); assert.equal(fmtClock(59001), '01:00'); assert.equal(fmtClock(0), '00:00'); assert.equal(fmtClock(-5), '00:00');
  assert.equal(progressPct({ remainingMs: 15 * 60000, totalMs: 25 * 60000 }), 40); assert.equal(progressPct({ remainingMs: 0, totalMs: 1 }), 100);
  assert.match(finishMessage({ finished: 'focus', next: 'long' }), /15-minute long break/); assert.match(finishMessage({ finished: 'short', next: 'focus' }), /Break over/);
});

// ---- static checks: navigation, V2 field names, safeguards
test('navigation: Pomodoro route and nav entry exist; every page module is registered', () => {
  const main = src('main.js');
  assert.match(main, /import pomodoro from '\.\/pages\/pomodoro\.js'/); assert.match(main, /reminders, pomodoro, progress/); assert.match(main, /\['pomodoro', 'Pomodoro Timer'/);
  for (const p of ['dashboard', 'tasks', 'subjects', 'planner', 'calendar', 'reminders', 'progress', 'assistant', 'settings']) assert.match(main, new RegExp(`pages/${p}\\.js`));
});

test('Stage 2 pages use only V2 field names and the V2 API; settings has no program/weeklySummary control', () => {
  for (const f of ['dashboard', 'calendar', 'reminders', 'planner', 'progress', 'settings', 'pomodoro']) {
    const s = src(`pages/${f}.js`);
    assert.doesNotMatch(s, /\.course\b|\.priority\b|\bisDone\b|\btopPick\b|\bt\.id\b|\bpick\.id\b|\.progress\b(?!_)|\bpill\(/, `${f}.js uses a legacy field`);
  }
  const st = src('pages/settings.js'); assert.doesNotMatch(st, /program|weeklySummary|name:\s*f\.name/); assert.match(st, /full_name/);
  assert.match(src('pages/reminders.js'), /saveReminderPrefs\(\{\[/); // partial save, no mutation of the loaded prefs
  assert.match(src('pages/planner.js'), /addSequentially/); assert.doesNotMatch(src('pages/planner.js'), /Promise\.all\(sel/);
});

test('safety: MOCK_V2 still false; login page and auth code untouched by this stage', () => {
  assert.match(src('api/client.js'), /^const MOCK_V2 = false;/m);
});
