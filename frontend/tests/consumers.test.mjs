// Stage 1 consumer tests. Run from the project root:  node --test frontend/tests/consumers.test.mjs
// No browser, no network. Pages that need a DOM are covered by static checks here plus the manual browser checklist.
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, readdirSync } from 'node:fs';
import { seedV2, mockV2Request, MockHttpError } from '../js/api/mockData.js';
import { statusPill, statusLabel, subjectName, cleanName, guard } from '../js/ui.js';
import { isOverdue, isDueSoon, taskCounts, daysBetween } from '../js/taskStats.js';

let n = 0; const ctx = { todayIso: '2026-11-18', newId: p => `${p}c${++n}` };
const call = (db, m, p, b) => mockV2Request(db, m, p, b, ctx);
const fresh = () => { const db = seedV2(); db.tasks = []; db.subjects = []; return db };
const rejects = (fn, status) => assert.throws(fn, e => e instanceof MockHttpError && e.status === status, `expected ${status}`);
const src = f => readFileSync(new URL('../js/' + f, import.meta.url), 'utf8');

test('first-use flow: no subjects, new subject + task exactly as the task modal sends them', () => {
  const db = fresh(); assert.deepEqual(call(db, 'GET', '/subjects'), []);
  const s = call(db, 'POST', '/subjects', { subject_name: cleanName('  Mathematics   ') });
  assert.equal(s.subject_name, 'Mathematics');
  const body = { title: cleanName('  Problem   set 1 '), category: 'assignment', importance: 'medium', deadline: '2026-11-20', subject_id: s.subject_id };
  const t = call(db, 'POST', '/tasks', body);
  assert.equal(t.status, 'not_started'); assert.equal(t.progress_pct, 0); assert.equal(t.title, 'Problem set 1');
});

test('modal create payload must not carry status or progress_pct (server rejects them)', () => {
  const db = fresh(); const s = call(db, 'POST', '/subjects', { subject_name: 'Physics' });
  const base = { title: 'Lab', category: 'exam', importance: 'high', deadline: '2026-11-25', subject_id: s.subject_id };
  rejects(() => call(db, 'POST', '/tasks', { ...base, progress_pct: 0 }), 422);
  rejects(() => call(db, 'POST', '/tasks', { ...base, status: 'not_started' }), 422);
  assert.ok(call(db, 'POST', '/tasks', base).task_id);
});

test('creating a task with a missing subject, bad category or bad date fails with 422 and saves nothing', () => {
  const db = fresh(); const s = call(db, 'POST', '/subjects', { subject_name: 'Art' });
  const ok = { title: 'T', category: 'quiz', importance: 'low', deadline: '2026-12-01', subject_id: s.subject_id };
  rejects(() => call(db, 'POST', '/tasks', { ...ok, subject_id: 'sub_missing' }), 422);
  rejects(() => call(db, 'POST', '/tasks', { ...ok, category: 'Assignment' }), 422); // legacy capitalised value
  rejects(() => call(db, 'POST', '/tasks', { ...ok, deadline: '2026-02-30' }), 422);
  rejects(() => call(db, 'POST', '/tasks', { ...ok, title: '   ' }), 422);
  assert.equal(call(db, 'GET', '/tasks').length, 0);
});

test('edit payload: completed task keeps 100% (progress omitted when slider is locked); open task can change progress without changing status', () => {
  const db = fresh(); const s = call(db, 'POST', '/subjects', { subject_name: 'Bio' });
  const t = call(db, 'POST', '/tasks', { title: 'R', category: 'research', importance: 'medium', deadline: '2026-12-05', subject_id: s.subject_id });
  const p = call(db, 'PATCH', '/tasks/' + t.task_id, { title: 'R2', progress_pct: 40 });
  assert.equal(p.progress_pct, 40); assert.equal(p.status, 'not_started'); // progress never decides status
  call(db, 'POST', `/tasks/${t.task_id}/complete`);
  const edited = call(db, 'PATCH', '/tasks/' + t.task_id, { title: 'R3', deadline: '2026-12-06' }); // no progress_pct, as the modal sends
  assert.equal(edited.progress_pct, 100); assert.equal(edited.status, 'completed');
  rejects(() => call(db, 'PATCH', '/tasks/' + t.task_id, { progress_pct: 50 }), 422);
});

test('status buttons: start, done, reopen follow the V2 rules; reopened task is in_progress at 100%', () => {
  const db = fresh(); const s = call(db, 'POST', '/subjects', { subject_name: 'Eng' });
  const t = call(db, 'POST', '/tasks', { title: 'E', category: 'project', importance: 'high', deadline: '2026-12-09', subject_id: s.subject_id }), id = t.task_id;
  rejects(() => call(db, 'POST', `/tasks/${id}/reopen`), 409);
  assert.equal(call(db, 'POST', `/tasks/${id}/start`).status, 'in_progress');
  const d = call(db, 'POST', `/tasks/${id}/complete`); assert.equal(d.status, 'completed'); assert.equal(d.progress_pct, 100);
  rejects(() => call(db, 'POST', `/tasks/${id}/start`), 409);
  const r = call(db, 'POST', `/tasks/${id}/reopen`); assert.equal(r.status, 'in_progress'); assert.equal(r.progress_pct, 100);
  assert.equal(call(db, 'POST', `/tasks/${id}/complete`).status, 'completed');
});

test('subjects page rules: duplicate (case/space) rejected, rename to own name ok, delete blocked while tasks exist', () => {
  const db = fresh(); const a = call(db, 'POST', '/subjects', { subject_name: 'Math' }), b = call(db, 'POST', '/subjects', { subject_name: 'Science' });
  rejects(() => call(db, 'POST', '/subjects', { subject_name: '  math ' }), 422);
  rejects(() => call(db, 'PATCH', '/subjects/' + b.subject_id, { subject_name: 'MATH' }), 422);
  assert.equal(call(db, 'PATCH', '/subjects/' + a.subject_id, { subject_name: 'Math' }).subject_name, 'Math');
  call(db, 'POST', '/tasks', { title: 'T', category: 'quiz', importance: 'low', deadline: '2026-12-01', subject_id: a.subject_id });
  rejects(() => call(db, 'DELETE', '/subjects/' + a.subject_id), 409);
  assert.equal(call(db, 'DELETE', '/subjects/' + b.subject_id), null);
  rejects(() => call(db, 'DELETE', '/subjects/nope'), 404);
  assert.deepEqual(call(db, 'GET', '/subjects').map(s => s.subject_name), ['Math']);
});

test('ui helpers: status pill/label, subject lookup, clean names', () => {
  assert.equal(statusLabel('in_progress'), 'In progress');
  assert.match(statusPill('completed'), /st-completed.*Completed/); assert.match(statusPill('weird'), /st-not_started/);
  const subs = [{ subject_id: 'a', subject_name: 'Math' }];
  assert.equal(subjectName(subs, 'a'), 'Math'); assert.equal(subjectName(subs, 'zzz'), 'Unknown subject'); assert.equal(subjectName(undefined, 'a'), 'Unknown subject');
  assert.equal(cleanName('  a   b\t c '), 'a b c'); assert.equal(cleanName(null), '');
});

const T = (deadline, status = 'in_progress') => ({ deadline, status });
const TODAY = '2026-11-18';
test('overdue and due soon use the agreed definitions; completed tasks count in neither', () => {
  assert.equal(isOverdue(T('2026-11-17'), TODAY), true);
  assert.equal(isOverdue(T('2026-11-18'), TODAY), false); // today is not overdue
  assert.equal(isDueSoon(T('2026-11-18'), TODAY), true);  // today is due soon
  assert.equal(isDueSoon(T('2026-11-21'), TODAY), true);  // +3 days is included
  assert.equal(isDueSoon(T('2026-11-22'), TODAY), false); // +4 is not
  assert.equal(isDueSoon(T('2026-11-17'), TODAY), false); // overdue is not due soon
  assert.equal(isOverdue(T('2026-11-01', 'completed'), TODAY), false);
  assert.equal(isDueSoon(T('2026-11-19', 'completed'), TODAY), false);
  assert.equal(isOverdue(T('not-a-date'), TODAY), false); assert.equal(isDueSoon({}, TODAY), false);
});

test('due soon crosses month and leap-year boundaries; daysBetween is exact', () => {
  assert.equal(isDueSoon(T('2026-12-02'), '2026-11-29'), true); assert.equal(isDueSoon(T('2026-12-03'), '2026-11-29'), false);
  assert.equal(isDueSoon(T('2028-03-01'), '2028-02-27'), true); assert.equal(daysBetween('2028-02-27', '2028-03-01'), 3);
  assert.equal(daysBetween('2026-12-31', '2027-01-01'), 1);
});

test('taskCounts: reopened 100% task is open; each task lands in at most one of overdue / due soon', () => {
  const tasks = [T('2026-11-10'), T('2026-11-18'), T('2026-11-20', 'not_started'), T('2026-12-30'), T('2026-11-01', 'completed'), { deadline: '2026-11-19', status: 'in_progress', progress_pct: 100 }];
  assert.deepEqual(taskCounts(tasks, TODAY), { total: 6, completed: 1, open: 5, overdue: 1, dueSoon: 3 });
});

test('navigation: Subjects route and sidebar entry exist; pages use V2 ids and actions, not legacy ones', () => {
  const main = src('main.js');
  assert.match(main, /import subjects from '\.\/pages\/subjects\.js'/); assert.match(main, /dashboard, tasks, subjects,/); assert.match(main, /\['subjects', 'Subjects'/);
  const tasks = src('pages/tasks.js'), modal = src('components/taskModal.js');
  for (const s of [tasks, modal, src('pages/subjects.js')]) assert.doesNotMatch(s, /\.course\b|\bpriority\b|isDone|\bt\.id\b|\.progress\b/);
  assert.match(tasks, /api\.startTask/); assert.match(tasks, /api\.completeTask/); assert.match(tasks, /api\.reopenTask/);
  assert.doesNotMatch(tasks, /updateTask/); assert.match(modal, /api\.updateTask\(task\.task_id/);
  const payload = modal.match(/const b=\{[^}]*\}/)[0]; assert.doesNotMatch(payload, /progress_pct|status/); // create payload never carries them
});

test('safety: MOCK_V2 is still false and no V2 switch was added', () => {
  assert.match(src('api/client.js'), /^const MOCK_V2 = false;/m);
});

// ---- Stage A: request lock ----
const area = () => ({ inert: false, classList: { s: new Set(), add(c) { this.s.add(c) }, remove(c) { this.s.delete(c) } } });
const later = () => { let done; const p = new Promise(r => { done = r }); return { p, done } };

test('guard: a second call is ignored while one is pending, and the area is locked meanwhile', async () => {
  const a = area(), gate = later(); let runs = 0;
  const run = guard(async () => { runs++; await gate.p; return 'ok' }, a);
  const first = run(); assert.equal(run.busy, true); assert.equal(a.inert, true); assert.ok(a.classList.s.has('locked'));
  assert.equal(await run(), undefined); assert.equal(runs, 1);
  gate.done(); assert.equal(await first, 'ok'); assert.equal(runs, 1);
});

test('guard: the lock is released after a success', async () => {
  const a = area(); let runs = 0; const run = guard(async () => { runs++ }, a);
  await run(); assert.equal(run.busy, false); assert.equal(a.inert, false); assert.equal(a.classList.s.has('locked'), false);
  await run(); assert.equal(runs, 2);
});

test('guard: the lock is released after an error, which still reaches the caller', async () => {
  const a = area(); let runs = 0; const run = guard(async () => { runs++; throw new Error('boom') }, a);
  await assert.rejects(run(), /boom/); assert.equal(run.busy, false); assert.equal(a.inert, false);
  await assert.rejects(run(), /boom/); assert.equal(runs, 2);
});

test('guard works without an area element', async () => { const run = guard(async x => x * 2); assert.equal(await run(4), 8); assert.equal(run.busy, false) });

test('Tasks, Subjects and Reminders use guard for their unprotected actions', () => {
  for (const f of ['pages/tasks.js', 'pages/subjects.js', 'pages/reminders.js']) assert.match(src(f), /import \{[^}]*\bguard\b[^}]*\} from '\.\.\/ui\.js'/, f);
  assert.match(src('pages/tasks.js'), /const act=guard\(/);
  assert.match(src('pages/subjects.js'), /const remove=guard\(/);
  assert.match(src('pages/reminders.js'), /const save=guard\(/);
});

// ---- Stage B: static checks (pages need a DOM, so their wiring is checked in the source) ----
test('B client: four subtask methods use the right verbs and paths, and encode ids', () => {
  const c = src('api/client.js');
  assert.match(c, /addSubtasks: \(id, b\) => req\('POST', '\/tasks\/' \+ encodeURIComponent\(id\) \+ '\/subtasks', b\)/);
  assert.match(c, /completeSubtask: \(id, sid\) => req\('POST', '\/tasks\/' \+ encodeURIComponent\(id\) \+ '\/subtasks\/' \+ encodeURIComponent\(sid\) \+ '\/complete'\)/);
  assert.match(c, /reopenSubtask: \(id, sid\) => req\('POST', '\/tasks\/' \+ encodeURIComponent\(id\) \+ '\/subtasks\/' \+ encodeURIComponent\(sid\) \+ '\/reopen'\)/);
  assert.match(c, /deleteSubtask: \(id, sid\) => req\('DELETE', '\/tasks\/' \+ encodeURIComponent\(id\) \+ '\/subtasks\/' \+ encodeURIComponent\(sid\)\)/);
});

test('B pages and components never call fetch; they go through the api client', () => {
  for (const dir of ['pages', 'components']) for (const f of readdirSync(new URL('../js/' + dir, import.meta.url)).filter(x => x.endsWith('.js'))) assert.doesNotMatch(src(`${dir}/${f}`), /\bfetch\s*\(/, `${dir}/${f}`);
  assert.match(src('pages/planner.js'), /import \{api\} from '\.\.\/api\/client\.js'/);
});

test('B planner: only appends subtasks to an existing parent; no new tasks or subjects, no category/importance/subject fields, no dates shown', () => {
  const p = src('pages/planner.js');
  assert.match(p, /api\.getTasks\(\)/); assert.match(p, /api\.planTask\(/); assert.match(p, /api\.addSubtasks\(p\.task_id,\{subtasks:items\}\)/);
  assert.doesNotMatch(p, /createTask|createSubject|getSubjects|updateTask|joinTitle|addSequentially|new_subject|subject_id|name="category"|name="importance"/);
  assert.doesNotMatch(p, /dueDate|fmtDate\(s\./); assert.match(p, /q\.get\('task'\)/); // deep link ?task=ID preselects the parent
  assert.match(p, /planStepsToSubtasks/); assert.match(p, /const add=guard\(/); assert.match(p, /const gen=guard\(/);
  assert.match(p, /addingReopens\(p\)&&!confirm\(/); assert.match(p, /subtaskCapacity/); assert.match(p, /add\.disabled=!n\|\|n>cap/);
  assert.match(p, /TEMPLATE PLAN · NO AI MODEL USED/); assert.match(p, /href="#\/tasks"/); // empty state points to My Tasks
});

test('B My Tasks: subtask rows with Complete / Reopen / Delete (confirmed), one lock, local replace; Done and Reopen hidden for parents with subtasks', () => {
  const t = src('pages/tasks.js');
  assert.match(t, /api\.completeSubtask/); assert.match(t, /api\.reopenSubtask/); assert.match(t, /api\.deleteSubtask/);
  assert.match(t, /a==='sub-del'&&confirm\(/); assert.match(t, /const act=guard\(/); assert.equal((t.match(/guard\(/g) || []).length, 1, 'a single lock for every list action');
  assert.match(t, /stateBtns=t=>hasSubtasks\(t\)\?\(t\.status==='not_started'\?btn\('start'[^:]*:''\):t\.status==='completed'/);
  assert.match(t, /tasks=tasks\.map\(x=>x\.task_id===r\.task_id\?r:x\);draw\(\)/); assert.match(t, /Progress is calculated from subtasks/);
  assert.match(t, /OK\.subComplete,true\)/); assert.match(t, /OK\.subReopen,true\)/); assert.match(t, /OK\.subDel,true\)/);
  assert.doesNotMatch(t, /\.course\b|\bpriority\b|isDone|\bt\.id\b|\.progress\b/);
});

test('B task modal: progress slider is disabled for a task with subtasks, with an explanation', () => {
  const m = src('components/taskModal.js');
  assert.match(m, /import \{hasSubtasks\} from '\.\.\/taskStats\.js'/); assert.match(m, /fromSubs=!!task&&hasSubtasks\(task\)/); assert.match(m, /locked=!!task&&\(isCompleted\(task\)\|\|fromSubs\)/);
  assert.match(m, /calculated from this task/); assert.match(m, /if\(fd\.has\('progress_pct'\)\)/); // a disabled input is not in the form data, so it is never sent
});
