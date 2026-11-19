// Phase 4.1 Stage 2 tests: AI consent, editable suggestions, Groq/Gemini/template labelling. Run from the project root:
//   node --test frontend/tests/aiplanner.test.mjs
// Pure logic and API-contract tests against the same mock engine the api client uses. Page wiring is checked statically (like the other
// test files); the browser behaviour is on the manual checklist. Nothing here calls the network, Firebase or Gemini.
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { seedV2, mockV2Request, MockHttpError, MAX_SUBTASKS } from '../js/api/mockData.js';
import { guard } from '../js/ui.js';
import { newRow, rowsFromPlan, moveRow, removeRow, addRow, selectedIndexes, validateRows, rowsAsSteps, planSource, planStepsToSubtasks,
  subtaskCapacity, addingReopens, MAX_STEP_TITLE, MAX_STEP_MINUTES, MAX_EDITOR_ROWS } from '../js/taskStats.js';

const src = f => readFileSync(new URL('../' + f, import.meta.url), 'utf8');
let n = 0; const ctx = { todayIso: '2026-11-16', newId: p => `${p}a${++n}` };
const call = (db, m, p, b) => mockV2Request(db, m, p, b, ctx);
const rejects = (fn, status, re) => assert.throws(fn, e => e instanceof MockHttpError && e.status === status && (!re || re.test(e.message)), `expected ${status}`);
const fresh = () => { const db = seedV2(); db.tasks = []; db.subjects = []; call(db, 'POST', '/subjects', { subject_name: 'Programming' }); return db };
const addTask = (db, over = {}) => call(db, 'POST', '/tasks', { title: 'Programming Activity 05', category: 'assignment', importance: 'high', deadline: '2026-11-20', subject_id: db.subjects[0].subject_id, ...over });
const PLAN = { mock: false, aiGenerated: true, source: 'gemini', notice: 'AI-generated suggestions (Google Gemini). Review each step before adding it as a subtask.',
  subtasks: [{ title: 'Outline the paper', dueDate: '2026-11-17', minutes: 30 }, { title: 'Collect three sources', dueDate: '2026-11-18', minutes: 60 }, { title: 'Write the draft', dueDate: '2026-11-19', minutes: 120 }] };
const titles = rows => rows.map(r => r.title);

// ---------- consent contract (mock engine = same rule as backend PLAN_RULES) ----------
test('consent: the mock plan endpoint accepts only a real boolean aiConsent and defaults to no consent', () => {
  const db = fresh(), body = { title: 'Paper', requirements: '', deadline: '2026-11-26', hoursPerDay: 1 };
  assert.match(call(db, 'POST', '/ai/plan', body).notice, /consent box was not ticked/);
  assert.match(call(db, 'POST', '/ai/plan', { ...body, aiConsent: false }).notice, /consent box was not ticked/);
  const yes = call(db, 'POST', '/ai/plan', { ...body, aiConsent: true });
  assert.doesNotMatch(yes.notice, /consent/); assert.match(yes.notice, /No AI model was used/);
  for (const bad of ['true', 1, 'yes', null, [], {}, 'false']) rejects(() => call(db, 'POST', '/ai/plan', { ...body, aiConsent: bad }), 422, /aiConsent/);
});

test('consent: the browser demo never claims AI, with or without consent, and keeps the response shape', () => {
  const db = fresh();
  for (const aiConsent of [true, false, undefined]) {
    const r = call(db, 'POST', '/ai/plan', { title: 'Paper', deadline: '2026-11-26', ...(aiConsent === undefined ? {} : { aiConsent }) });
    assert.equal(r.mock, true); assert.equal(r.aiGenerated, false); assert.notEqual(r.source, 'gemini'); assert.equal(planSource(r).kind, 'demo');
    assert.deepEqual(Object.keys(r.subtasks[0]), ['title', 'dueDate', 'minutes']);
  }
});

test('consent: the page sends nothing before the box is ticked, sends aiConsent: true only after it, and clears the box after every request', () => {
  const p = src('js/pages/planner.js'), gate = p.indexOf('if(!E.aiConsent.checked)'), call1 = p.indexOf('api.planTask(');
  assert.ok(gate > 0 && call1 > gate, 'the consent check comes before the request');
  assert.match(p.slice(gate, call1), /return\}/); assert.match(p.slice(gate, call1), /later\(\(\)=>E\.aiConsent\.focus\(\)\)/); // focus is set after the lock is released // the unchecked branch returns before any request
  assert.equal((p.match(/api\.planTask\(/g) || []).length, 1, 'one place sends plan requests');
  assert.equal((p.match(/aiConsent:true/g) || []).length, 1); assert.doesNotMatch(p, /aiConsent:(?!true)/); // never false, never a variable
  assert.match(p, /finally\{E\.aiConsent\.checked=false\}/); assert.match(p, /E\.aiConsent\.checked=false;consentErr\.hidden=true;drawCur\(\)/); // cleared after each request and on parent change
  assert.match(p, /name="aiConsent"/); assert.doesNotMatch(p, /name="aiConsent"[^>]*(checked|required)/); // unchecked by default
});

test('consent text names every field that may be sent, both providers, and the template fallback', () => {
  const p = src('js/pages/planner.js'), box = p.slice(p.indexOf('class="consent"'), p.indexOf('id="gen"'));
  for (const w of [/task title/, /requirements/, /deadline/, /available hours per day/, /Google Gemini|Groq/, /built-in template/, /not set up|unavailable|configured|available/, /tick it again/]) assert.match(box, w);
  assert.doesNotMatch(box, /email|password|\buid\b|name and/i); // it must not promise or imply anything else is sent
});

test('the generate request has exactly the five API fields', () => {
  const p = src('js/pages/planner.js'), m = p.match(/api\.planTask\(\{([^}]*)\}\)/);
  assert.deepEqual(m[1].split(',').map(x => x.split(':')[0]), ['title', 'requirements', 'deadline', 'hoursPerDay', 'aiConsent']);
});

// ---------- Groq/Gemini versus template labelling ----------
test('labels: only genuine Groq or Gemini responses are shown as AI; the server template and anything doubtful are shown as a template', () => {
  assert.equal(planSource(PLAN).kind, 'gemini'); assert.match(planSource(PLAN).pill, /GOOGLE GEMINI/);
  const groq = { ...PLAN, source: 'groq', notice: 'AI-generated suggestions (Groq).' };
  assert.equal(planSource(groq).kind, 'groq'); assert.match(planSource(groq).pill, /GROQ/);
  const tpl = { mock: true, aiGenerated: false, source: 'deterministic-fallback', notice: 'x' };
  assert.equal(planSource(tpl).kind, 'template'); assert.match(planSource(tpl).pill, /TEMPLATE PLAN · NO AI MODEL USED/); assert.match(planSource(tpl).heading, /Not generated by an AI model/);
  for (const odd of [{ ...PLAN, aiGenerated: false }, { ...PLAN, source: 'deterministic-fallback' }, { ...PLAN, source: 'other' }, { ...PLAN, mock: true }, { ...PLAN, aiGenerated: 'true' },
    { source: 'gemini' }, { source: 'groq' }, { aiGenerated: true }, {}, null, undefined, 'gemini']) assert.notEqual(planSource(odd).kind, 'gemini', JSON.stringify(odd));
  assert.doesNotMatch(planSource(tpl).pill + planSource(tpl).heading, /gemini|AI-generated/i);
});

test('labels: the page shows the pill and heading from planSource and the backend notice, escaped, and never hard-codes an AI claim', () => {
  const p = src('js/pages/planner.js');
  assert.match(p, /\$\('#src',el\)\.textContent=s\.pill/); assert.match(p, /esc\(s\.heading\)/); assert.match(p, /\$\{r\.notice\?`<p class="hint">\$\{esc\(r\.notice\)\}<\/p>`:''\}/);
  assert.doesNotMatch(p, /AI-GENERATED|Gemini generated|Suggested by/); // those texts live only in planSource
  assert.match(src('js/taskStats.js'), /r\.aiGenerated===true&&r\.mock!==true&&r\.source==='gemini'/);
  assert.match(src('js/taskStats.js'), /r\.aiGenerated===true&&r\.mock!==true&&r\.source==='groq'/);
});

// ---------- editor rows ----------
test('rows: built from the plan with minutes as text; dates are dropped; bad input cannot flood or crash the page', () => {
  const rows = rowsFromPlan(PLAN.subtasks);
  assert.deepEqual(titles(rows), ['Outline the paper', 'Collect three sources', 'Write the draft']); assert.deepEqual(rows.map(r => r.minutes), ['30', '60', '120']);
  assert.ok(rows.every(r => r.selected === true && !('dueDate' in r))); assert.equal(new Set(rows.map(r => r.key)).size, 3);
  assert.deepEqual(rowsFromPlan(null), []); assert.deepEqual(rowsFromPlan('x'), []); assert.deepEqual(rowsFromPlan([null, 5, { title: 'ok', minutes: 'abc' }]).map(r => [r.title, r.minutes]), [['ok', '']]);
  assert.equal(rowsFromPlan(Array.from({ length: 50 }, (_, i) => ({ title: 't' + i, minutes: 5 }))).length, MAX_EDITOR_ROWS);
});

test('rows: reorder moves one step and does not mutate the original; the ends and bad indexes are no-ops', () => {
  const r = rowsFromPlan(PLAN.subtasks), before = titles(r);
  assert.deepEqual(titles(moveRow(r, 1, -1)), ['Collect three sources', 'Outline the paper', 'Write the draft']);
  assert.deepEqual(titles(moveRow(r, 0, 1)), ['Collect three sources', 'Outline the paper', 'Write the draft']);
  assert.deepEqual(titles(moveRow(r, 2, 1)), before); assert.deepEqual(titles(moveRow(r, 0, -1)), before); assert.deepEqual(titles(moveRow(r, 9, -1)), before); assert.deepEqual(titles(moveRow(r, -1, 1)), before);
  assert.deepEqual(titles(r), before);
  const moved = moveRow(r, 2, -1); assert.deepEqual(moved.map(x => x.key), [r[0].key, r[2].key, r[1].key]); // rows keep their own identity and state
});

test('rows: remove and add a manual step; the manual step starts ticked and blank, and the editor is capped', () => {
  const r = rowsFromPlan(PLAN.subtasks);
  assert.deepEqual(titles(removeRow(r, 1)), ['Outline the paper', 'Write the draft']); assert.deepEqual(titles(removeRow(r, 7)), titles(r)); assert.equal(r.length, 3);
  const a = addRow(r); assert.equal(a.length, 4); assert.deepEqual([a[3].title, a[3].minutes, a[3].selected], ['', '30', true]); assert.equal(r.length, 3);
  let big = r; for (let i = 0; i < 40; i++) big = addRow(big); assert.equal(big.length, MAX_EDITOR_ROWS);
});

test('rows: selection picks exactly the ticked steps, in the order shown', () => {
  let r = rowsFromPlan(PLAN.subtasks); r[1].selected = false;
  assert.deepEqual(selectedIndexes(r), [0, 2]);
  r = moveRow(r, 2, -1); // now: Outline, Write, Collect(unticked)
  assert.deepEqual(planStepsToSubtasks(rowsAsSteps(r), selectedIndexes(r)).map(i => i.title), ['Outline the paper', 'Write the draft']);
  r.forEach(x => { x.selected = false }); assert.deepEqual(selectedIndexes(r), []); assert.deepEqual(planStepsToSubtasks(rowsAsSteps(r), selectedIndexes(r)), []);
});

// ---------- validation ----------
test('validation: title and minutes rules, reported per row; unticked rows are never checked', () => {
  const r = rowsFromPlan(PLAN.subtasks); assert.deepEqual(validateRows(r), { errors: {}, count: 3, ok: true });
  r[0].title = '   '; r[1].minutes = '0'; r[2].minutes = '12.5';
  const v = validateRows(r); assert.equal(v.ok, false); assert.equal(v.count, 3);
  assert.deepEqual(Object.keys(v.errors[r[0].key]), ['title']); assert.deepEqual(Object.keys(v.errors[r[1].key]), ['minutes']); assert.deepEqual(Object.keys(v.errors[r[2].key]), ['minutes']);
  r[0].selected = r[1].selected = r[2].selected = false; assert.deepEqual(validateRows(r), { errors: {}, count: 0, ok: false }); // nothing ticked is not ok
  r[0].selected = true; r[0].title = 'x'.repeat(MAX_STEP_TITLE + 1); assert.match(validateRows(r).errors[r[0].key].title, /at most 120/);
  r[0].title = 'x'.repeat(MAX_STEP_TITLE); assert.equal(validateRows(r).ok, true);
});

test('validation: minutes must be whole numbers from 1 up to the cap; odd text is rejected', () => {
  const one = m => { const r = [newRow('Step', m)]; return validateRows(r).ok };
  for (const good of ['1', '30', ' 45 ', '5400', String(MAX_STEP_MINUTES)]) assert.equal(one(good), true, good);
  for (const bad of ['', ' ', '0', '-5', '1.5', '1e3', 'abc', '30min', '0x10', String(MAX_STEP_MINUTES + 1), '٣٠']) assert.equal(one(bad), false, JSON.stringify(bad));
  assert.equal(validateRows([newRow('  Spaced   out  ', '10')]).ok, true);
  assert.equal(validateRows([newRow('x '.repeat(70), '10')]).ok, false); // cleaned length counts (139 characters)
});

test('validation: what passes the editor is accepted by the API, and a request is built only from valid ticked rows', () => {
  const db = fresh(), t = addTask(db), r = rowsFromPlan(PLAN.subtasks);
  r[0].title = '  Outline   the paper v2 '; r[1].selected = false; r.push(newRow('Manual step', '15'));
  assert.equal(validateRows(r).ok, true);
  const items = planStepsToSubtasks(rowsAsSteps(r), selectedIndexes(r));
  assert.deepEqual(items, [{ title: 'Outline the paper v2', estimated_minutes: 30 }, { title: 'Write the draft', estimated_minutes: 120 }, { title: 'Manual step', estimated_minutes: 15 }]);
  assert.deepEqual(call(db, 'POST', `/tasks/${t.task_id}/subtasks`, { subtasks: items }).subtasks.map(s => s.title), items.map(i => i.title));
});

// ---------- existing safeguards still hold with edited suggestions ----------
test('safeguards: edited steps are appended to the chosen parent only; existing subtasks and their completion states are kept; no parent task is created', () => {
  const db = fresh(), a = addTask(db, { title: 'A' }), b = addTask(db, { title: 'B' });
  const first = call(db, 'POST', `/tasks/${a.task_id}/subtasks`, { subtasks: [{ title: 'Old one', estimated_minutes: 20 }, { title: 'Old two', estimated_minutes: 20 }] });
  call(db, 'POST', `/tasks/${a.task_id}/subtasks/${first.subtasks[0].subtask_id}/complete`);
  const bBefore = JSON.stringify(call(db, 'GET', '/tasks').find(t => t.task_id === b.task_id)), rows = moveRow(addRow(rowsFromPlan(PLAN.subtasks)), 2, -1); rows[3].title = 'My own step';
  const u = call(db, 'POST', `/tasks/${a.task_id}/subtasks`, { subtasks: planStepsToSubtasks(rowsAsSteps(rows), selectedIndexes(rows)) });
  assert.deepEqual(u.subtasks.map(s => s.title), ['Old one', 'Old two', 'Outline the paper', 'Write the draft', 'Collect three sources', 'My own step']);
  assert.deepEqual(u.subtasks.map(s => s.status), ['completed', 'not_started', 'not_started', 'not_started', 'not_started', 'not_started']);
  assert.equal(u.subtasks[0].subtask_id, first.subtasks[0].subtask_id);
  const all = call(db, 'GET', '/tasks'); assert.equal(all.length, 2); assert.equal(JSON.stringify(all.find(t => t.task_id === b.task_id)), bBefore);
});

test('safeguards: the 20-subtask limit still applies (capacity maths and the API), and a rejected add changes nothing', () => {
  const db = fresh(), t = addTask(db), items = k => Array.from({ length: k }, (_, i) => ({ title: 'S' + i, estimated_minutes: 5 }));
  const p = call(db, 'POST', `/tasks/${t.task_id}/subtasks`, { subtasks: items(18) });
  assert.equal(subtaskCapacity(p), 2); assert.equal(MAX_EDITOR_ROWS, MAX_SUBTASKS);
  const before = JSON.stringify(db), rows = [newRow('a', '5'), newRow('b', '5'), newRow('c', '5')];
  rejects(() => call(db, 'POST', `/tasks/${t.task_id}/subtasks`, { subtasks: planStepsToSubtasks(rowsAsSteps(rows), selectedIndexes(rows)) }), 422, /at most 20/); assert.equal(JSON.stringify(db), before);
  rows[2].selected = false; assert.equal(call(db, 'POST', `/tasks/${t.task_id}/subtasks`, { subtasks: planStepsToSubtasks(rowsAsSteps(rows), selectedIndexes(rows)) }).subtasks.length, 20);
});

test('safeguards: adding to a completed parent still warns (and reopens it); the page keeps the confirm, the lock and the capacity gate', () => {
  const db = fresh(), t = addTask(db); call(db, 'POST', `/tasks/${t.task_id}/complete`);
  const done = call(db, 'GET', '/tasks')[0]; assert.equal(addingReopens(done), true); assert.equal(addingReopens({ status: 'in_progress' }), false);
  const u = call(db, 'POST', `/tasks/${t.task_id}/subtasks`, { subtasks: [{ title: 'More', estimated_minutes: 10 }] }); assert.equal(u.status, 'in_progress');
  const p = src('js/pages/planner.js');
  assert.match(p, /addingReopens\(p\)&&!confirm\(/); assert.match(p, /This task is completed\. Adding subtasks will reopen it\./);
  assert.match(p, /const gen=guard\(/); assert.match(p, /const add=guard\(/); assert.equal((p.match(/guard\(/g) || []).length, 2); assert.equal((p.match(/,grid\)/g) || []).length, 2); // both share the one locked area
  assert.match(p, /add\.disabled=!n\|\|n>cap/); assert.match(p, /items\.length>subtaskCapacity\(p\)/);
  assert.match(p, /api\.addSubtasks\(p\.task_id,\{subtasks:items\}\)/); assert.doesNotMatch(p, /createTask|updateTask|createSubject|subject_id|dueDate/);
});

test('safeguards: validation runs before the request, a failed save keeps the edits, and API error messages are shown as before', () => {
  const p = src('js/pages/planner.js'), add = p.slice(p.indexOf('const add=guard('));
  assert.ok(add.indexOf('validateRows(rows)') < add.indexOf('api.addSubtasks('), 'validate first');
  assert.match(add, /if\(!v\.ok\)\{[\s\S]*?return toast\('Fix the highlighted steps first','bad'\)\}/);
  assert.match(add, /catch\(x\)\{toast\(x\.message,'bad'\)\}/); assert.match(add, /rows=null;out\.className='note'/); // rows are dropped only on success
  assert.match(p, /catch\(x\)\{rows=null;out\.className='state err';out\.textContent=x\.message\}/); // generate errors show the API message
  assert.match(p, /No steps were generated\. Try again\./);
});

test('safeguards: the request lock blocks a second call while one is pending, then releases (also after an error)', async () => {
  let release, calls = 0; const run = guard(() => { calls++; return new Promise((_, rej) => { release = rej }) }), first = run().catch(() => {});
  await run(); assert.equal(calls, 1); assert.equal(run.busy, true); release(new Error('x')); await first; assert.equal(run.busy, false); run().catch(() => {}); assert.equal(calls, 2);
});

test('safety: config and API client are untouched in the ways that matter', () => {
  assert.match(src('js/config.js'), /const USE_MOCK = false;/); assert.match(src('js/api/client.js'), /^const MOCK_V2 = false;/m);
  assert.match(src('js/api/client.js'), /planTask: b => req\('POST', '\/ai\/plan', b\)/); assert.doesNotMatch(src('js/pages/planner.js'), /\bfetch\s*\(|GEMINI_API|generativelanguage|apiKey|api_key/);
});
