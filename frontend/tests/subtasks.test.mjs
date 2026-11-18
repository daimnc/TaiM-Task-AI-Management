// Stage A subtask tests (mock engine). Run from the project root:  node --test frontend/tests/subtasks.test.mjs
// Same rules and the same cases as backend/tests/test_subtasks.py, so the mock and the real API cannot drift apart.
import test from 'node:test';
import assert from 'node:assert/strict';
import { seedV2, convertLegacyDb, seed, validateV2Db, bootstrapMockV2, mockV2Request, MockHttpError, KEYS, percentDone, MAX_SUBTASKS } from '../js/api/mockData.js';

let n = 0; const ctx = { todayIso: '2026-11-16', newId: p => `${p}s${++n}` };
const call = (db, m, p, b) => mockV2Request(db, m, p, b, ctx);
const fresh = () => { const db = seedV2(); db.tasks = []; db.subjects = []; call(db, 'POST', '/subjects', { subject_name: 'Programming' }); return db };
const rejects = (fn, status, re) => assert.throws(fn, e => e instanceof MockHttpError && e.status === status && (!re || re.test(e.message)), `expected ${status}`);
const STEPS = ['Research the topic', 'Write the program', 'Test and debug'];
const addTask = (db, over = {}) => call(db, 'POST', '/tasks', { title: 'Programming Activity 05', category: 'assignment', importance: 'high', deadline: '2026-11-20', subject_id: db.subjects[0].subject_id, ...over });
const addSubs = (db, id, titles = STEPS) => call(db, 'POST', `/tasks/${id}/subtasks`, { subtasks: titles.map(title => ({ title, estimated_minutes: 30 })) });
const parentWith = (db, titles = STEPS, over = {}) => addSubs(db, addTask(db, over).task_id, titles);
const sub = (db, id, action, sid) => action === 'delete' ? call(db, 'DELETE', `/tasks/${id}/subtasks/${sid}`) : call(db, 'POST', `/tasks/${id}/subtasks/${sid}/${action}`);
const ids = p => p.subtasks.map(s => s.subtask_id);
const get = (db, id) => call(db, 'GET', '/tasks').find(t => t.task_id === id);
const snap = db => JSON.stringify(db);

test('add: steps are attached to the parent with the exact shape and are not separate tasks', () => {
  const db = fresh(), p = parentWith(db);
  assert.deepEqual(Object.keys(p).slice(-1), ['subtasks']);
  assert.deepEqual(p.subtasks.map(s => s.title), STEPS);
  for (const s of p.subtasks) { assert.deepEqual(Object.keys(s), ['subtask_id', 'title', 'estimated_minutes', 'status']); assert.equal(s.status, 'not_started'); assert.equal(s.estimated_minutes, 30) }
  assert.equal(new Set(ids(p)).size, 3); assert.equal(p.progress_pct, 0); assert.equal(p.status, 'not_started');
  assert.equal(call(db, 'GET', '/tasks').length, 1);
  assert.deepEqual(validateV2Db(db), []);
});

test('add: estimated_minutes defaults to 30; unknown fields such as a due date are ignored and not stored', () => {
  const db = fresh(), t = addTask(db);
  const p = call(db, 'POST', `/tasks/${t.task_id}/subtasks`, { subtasks: [{ title: 'A', dueDate: '2026-11-18', due_date: '2026-11-18', x: 1 }] });
  assert.equal(p.subtasks[0].estimated_minutes, 30);
  assert.deepEqual(Object.keys(db.tasks[0].subtasks[0]), ['subtask_id', 'title', 'estimated_minutes', 'status']);
});

test('add: new subtasks are appended and never replace existing ones', () => {
  const db = fresh(), p = parentWith(db), first = ids(p);
  sub(db, p.task_id, 'complete', first[0]);
  const again = addSubs(db, p.task_id, ['Four', 'Five']);
  assert.deepEqual(ids(again).slice(0, 3), first); assert.deepEqual(again.subtasks.map(s => s.title), [...STEPS, 'Four', 'Five']);
  assert.equal(again.subtasks[0].status, 'completed'); assert.equal(again.progress_pct, 20);
});

test('add: the whole batch is validated first, every problem is reported, nothing is saved', () => {
  const db = fresh(), t = addTask(db), before = snap(db);
  const bad = { subtasks: [{ title: 'Fine' }, { title: '  ' }, { title: 'x'.repeat(121) }, { title: 'ok', estimated_minutes: 0 }, 'nope', { title: 'ok', status: 'completed', subtask_id: 'mine' }] };
  try { call(db, 'POST', `/tasks/${t.task_id}/subtasks`, bad); assert.fail('should reject') }
  catch (e) { assert.ok(e instanceof MockHttpError); assert.equal(e.status, 422); assert.deepEqual(Object.keys(e.errors).sort(), ['subtasks[1].title', 'subtasks[2].title', 'subtasks[3].estimated_minutes', 'subtasks[4]', 'subtasks[5].status', 'subtasks[5].subtask_id'].sort()) }
  assert.equal(snap(db), before);
});

test('add: bad batch shapes and minutes are 422 and change nothing', () => {
  const db = fresh(), t = addTask(db), before = snap(db), url = `/tasks/${t.task_id}/subtasks`;
  for (const b of [{}, { subtasks: [] }, { subtasks: 'x' }, { subtasks: { title: 'a' } }, { subtasks: [{}] }]) rejects(() => call(db, 'POST', url, b), 422);
  for (const m of [0, -5, 1.5, '30', true, null, Number.MAX_SAFE_INTEGER + 1, 1e300]) rejects(() => call(db, 'POST', url, { subtasks: [{ title: 'a', estimated_minutes: m }] }), 422);
  rejects(() => call(db, 'POST', url, 'not an object'), 400);
  assert.equal(snap(db), before);
});

test('add: the limit of 20 counts existing subtasks and saves nothing when exceeded', () => {
  const db = fresh(), p = parentWith(db, Array.from({ length: 18 }, (_, i) => `S${i}`)), before = snap(db);
  rejects(() => addSubs(db, p.task_id, ['a', 'b', 'c']), 422, /at most 20/); assert.equal(snap(db), before);
  assert.equal(addSubs(db, p.task_id, ['a', 'b']).subtasks.length, MAX_SUBTASKS);
  rejects(() => addSubs(db, p.task_id, Array.from({ length: 21 }, (_, i) => `T${i}`)), 422);
});

test('progress: 0/33/67/100 for three subtasks, parent completes and reopens through its subtasks', () => {
  const db = fresh(), p = parentWith(db), seen = [];
  for (const sid of ids(p)) { const b = sub(db, p.task_id, 'complete', sid); seen.push([b.progress_pct, b.status]) }
  assert.deepEqual(seen, [[33, 'in_progress'], [67, 'in_progress'], [100, 'completed']]);
  const re = sub(db, p.task_id, 'reopen', ids(p)[2]); assert.deepEqual([re.progress_pct, re.status], [67, 'in_progress']);
  sub(db, p.task_id, 'reopen', ids(p)[0]); sub(db, p.task_id, 'reopen', ids(p)[1]);
  const z = get(db, p.task_id); assert.deepEqual([z.progress_pct, z.status], [0, 'in_progress']); // not back to not_started
  assert.deepEqual(validateV2Db(db), []);
});

test('progress: the Progress page counts the auto-completed parent once; reopening removes it', () => {
  const db = fresh(), p = parentWith(db); ids(p).forEach(sid => sub(db, p.task_id, 'complete', sid));
  const open = () => call(db, 'GET', '/progress').completed - db.history.completed;
  assert.equal(open(), 1); sub(db, p.task_id, 'reopen', ids(p)[0]); assert.equal(open(), 0);
});

test('progress: completing twice is a no-op; reopening a not-completed subtask is 409', () => {
  const db = fresh(), p = parentWith(db), sid = ids(p)[0];
  const a = sub(db, p.task_id, 'complete', sid), b = sub(db, p.task_id, 'complete', sid);
  assert.deepEqual(a, b); rejects(() => sub(db, p.task_id, 'reopen', ids(p)[1]), 409); assert.equal(get(db, p.task_id).progress_pct, 33);
});

test('progress: rounding is half up with whole numbers, same table as the backend', () => {
  for (const [count, done, expected] of [[6, 1, 17], [6, 5, 83], [8, 1, 13], [8, 3, 38], [7, 3, 43], [20, 19, 95]]) {
    const db = fresh(), p = parentWith(db, Array.from({ length: count }, (_, i) => `S${i}`)); let b = p;
    for (const sid of ids(p).slice(0, done)) b = sub(db, p.task_id, 'complete', sid);
    assert.equal(b.progress_pct, expected, `${done}/${count}`); assert.equal(b.status, 'in_progress');
  }
  assert.equal(percentDone(0, 0), 0); assert.equal(percentDone(1, 3), 33); assert.equal(percentDone(2, 3), 67); assert.equal(percentDone(3, 3), 100);
});

test('status: Start is still allowed; a started parent stays started at 0%', () => {
  const db = fresh(), p = parentWith(db);
  assert.equal(call(db, 'POST', `/tasks/${p.task_id}/start`).status, 'in_progress');
  sub(db, p.task_id, 'complete', ids(p)[0]); sub(db, p.task_id, 'reopen', ids(p)[0]); assert.equal(get(db, p.task_id).status, 'in_progress');
});

test('status: parent Done and Reopen are refused (409) while subtasks exist, and nothing changes', () => {
  const db = fresh(), p = parentWith(db); let before = snap(db);
  for (const a of ['complete', 'reopen']) rejects(() => call(db, 'POST', `/tasks/${p.task_id}/${a}`), 409);
  assert.equal(snap(db), before); ids(p).forEach(sid => sub(db, p.task_id, 'complete', sid)); before = snap(db);
  for (const a of ['complete', 'reopen']) rejects(() => call(db, 'POST', `/tasks/${p.task_id}/${a}`), 409);
  assert.equal(snap(db), before);
});

test('edit: manual progress is refused with subtasks, other edits keep the subtasks', () => {
  const db = fresh(), p = parentWith(db), url = `/tasks/${p.task_id}`;
  rejects(() => call(db, 'PATCH', url, { progress_pct: 50 }), 422, /progress_pct/);
  rejects(() => call(db, 'PATCH', url, { title: 'Renamed', status: 'completed' }), 422);
  const r = call(db, 'PATCH', url, { title: 'Renamed', subtasks: [] }); assert.equal(r.title, 'Renamed'); assert.equal(r.subtasks.length, 3);
});

test('compatibility: tasks without subtasks keep the manual rules exactly', () => {
  const db = fresh(), t = addTask(db), url = `/tasks/${t.task_id}`;
  assert.equal(call(db, 'PATCH', url, { progress_pct: 40 }).status, 'not_started');
  const d = call(db, 'POST', `${url}/complete`); assert.deepEqual([d.status, d.progress_pct], ['completed', 100]);
  const r = call(db, 'POST', `${url}/reopen`); assert.deepEqual([r.status, r.progress_pct, r.subtasks], ['in_progress', 100, []]);
  assert.equal('subtasks' in db.tasks[0], false); // a task is never given the field until it gets a subtask
});

test('add to a completed task reopens it; adding replaces manual progress with the calculated value', () => {
  const db = fresh(), a = addTask(db), b = addTask(db, { title: 'B' });
  call(db, 'POST', `/tasks/${a.task_id}/complete`);
  const x = addSubs(db, a.task_id, ['One', 'Two']); assert.deepEqual([x.status, x.progress_pct], ['in_progress', 0]);
  call(db, 'PATCH', `/tasks/${b.task_id}`, { progress_pct: 65 }); assert.equal(addSubs(db, b.task_id, ['One', 'Two']).progress_pct, 0);
});

test('delete subtask: parent is recalculated; deleting the last one returns to manual rules', () => {
  const db = fresh(), p = parentWith(db), t = p.task_id, i = ids(p);
  sub(db, t, 'complete', i[0]);
  let b = sub(db, t, 'delete', i[1]); assert.deepEqual([b.subtasks.length, b.progress_pct, b.status], [2, 50, 'in_progress']);
  b = sub(db, t, 'delete', i[2]); assert.deepEqual([b.progress_pct, b.status], [100, 'completed']);
  const one = parentWith(db, ['Only']); b = sub(db, one.task_id, 'delete', ids(one)[0]);
  assert.deepEqual([b.subtasks, b.progress_pct, b.status], [[], 0, 'not_started']);
  assert.equal(call(db, 'POST', `/tasks/${one.task_id}/complete`).status, 'completed');
  assert.deepEqual(validateV2Db(db), []);
});

test('delete parent: embedded subtasks go with it; subject delete rule unchanged', () => {
  const db = fresh(), p = parentWith(db), keep = parentWith(db, STEPS, { title: 'Keep' });
  rejects(() => call(db, 'DELETE', `/subjects/${db.subjects[0].subject_id}`), 409);
  assert.equal(call(db, 'DELETE', `/tasks/${p.task_id}`), null);
  assert.deepEqual(call(db, 'GET', '/tasks').map(t => t.task_id), [keep.task_id]);
  assert.ok(!snap(db).includes(ids(p)[0])); rejects(() => sub(db, p.task_id, 'delete', ids(p)[0]), 404);
});

test('not found: missing task, missing or malformed subtask, and a subtask id from another task', () => {
  const db = fresh(), p = parentWith(db), q = parentWith(db, STEPS, { title: 'Second' });
  rejects(() => addSubs(db, 'nope'), 404, /Task not found/);
  for (const sid of ['nope', 'a b', 'x'.repeat(200)]) for (const a of ['complete', 'reopen', 'delete']) rejects(() => sub(db, p.task_id, a, sid), 404);
  rejects(() => sub(db, q.task_id, 'complete', ids(p)[0]), 404, /Subtask not found/);
  rejects(() => call(db, 'PUT', `/tasks/${p.task_id}/subtasks`, {}), 405);
});

test('compatibility: databases saved before subtasks existed still validate and load', () => {
  const old = seedV2(); assert.deepEqual(validateV2Db(old), []);
  assert.ok(old.tasks.every(t => !('subtasks' in t))); // converter and seed output are unchanged
  assert.ok(convertLegacyDb(seed).db.tasks.every(t => !('subtasks' in t)));
  const store = new Map([[KEYS.v2, JSON.stringify(old)]]), storage = { getItem: k => store.has(k) ? store.get(k) : null, setItem: (k, v) => store.set(k, v), removeItem: k => store.delete(k) };
  const r = bootstrapMockV2(storage); assert.equal(r.ok, true); assert.equal(r.source, 'v2'); assert.equal(store.size, 1); // loaded with no writes
  assert.ok(call(old, 'GET', '/tasks').every(t => Array.isArray(t.subtasks) && t.subtasks.length === 0));
  const t = call(old, 'POST', `/tasks/${old.tasks[0].task_id}/subtasks`, { subtasks: [{ title: 'New' }] }); assert.equal(t.subtasks.length, 1);
});

test('validateV2Db: rejects subtask data that disagrees with itself', () => {
  const ok = () => { const db = fresh(); parentWith(db); return db };
  assert.deepEqual(validateV2Db(ok()), []);
  const cases = [d => { d.tasks[0].progress_pct = 50 }, d => { d.tasks[0].status = 'completed' }, d => { d.tasks[0].subtasks[0].status = 'in_progress' },
    d => { d.tasks[0].subtasks[1].subtask_id = d.tasks[0].subtasks[0].subtask_id }, d => { d.tasks[0].subtasks[0].title = '' }, d => { d.tasks[0].subtasks[0].extra = 1 },
    d => { d.tasks[0].subtasks = 'x' }, d => { d.tasks[0].subtasks = Array.from({ length: 21 }, (_, i) => ({ subtask_id: `a${i}`, title: 't', estimated_minutes: 5, status: 'not_started' })) }];
  for (const [i, c] of cases.entries()) { const d = ok(); c(d); assert.ok(validateV2Db(d).length > 0, `case ${i}`) }
});

test('safety: the V2 backend gate and mock flags are not touched by the engine file', async () => {
  const { readFileSync } = await import('node:fs'), src = readFileSync(new URL('../js/api/mockData.js', import.meta.url), 'utf8');
  assert.doesNotMatch(src, /MOCK_V2\s*=|TAIM_ENABLE_V2|localStorage\./);
});

// ---- Stage A corrections: no workload cap on minutes, safe-integer guard, shared parity table, recalculation ----
test('minutes: large values and the 30-minute default are saved, returned and valid; the safe-integer limit is the only cap', () => {
  const db = fresh(), id = addTask(db).task_id;
  const p = call(db, 'POST', `/tasks/${id}/subtasks`, { subtasks: [1441, 2160, 100000, Number.MAX_SAFE_INTEGER, undefined].map(m => ({ title: `m${m}`, ...(m === undefined ? {} : { estimated_minutes: m }) })) });
  assert.deepEqual(p.subtasks.map(s => s.estimated_minutes), [1441, 2160, 100000, Number.MAX_SAFE_INTEGER, 30]);
  assert.deepEqual(get(db, id).subtasks.map(s => s.estimated_minutes), [1441, 2160, 100000, Number.MAX_SAFE_INTEGER, 30]);
  assert.deepEqual(validateV2Db(db), []);
  const before = snap(db);
  rejects(() => call(db, 'POST', `/tasks/${id}/subtasks`, { subtasks: [{ title: 'x', estimated_minutes: Number.MAX_SAFE_INTEGER + 1 }] }), 422, /minutes/);
  assert.equal(snap(db), before);
});

// SAME TABLE as PARITY_CASES in backend/tests/test_subtasks.py (same names, same data, same expectation).
const S = (id, over = {}) => ({ subtask_id: id, title: 'Step ' + id, estimated_minutes: 30, status: 'not_started', ...over });
const DONE = id => S(id, { status: 'completed' });
const three = (...st) => ['a', 'b', 'c'].map((id, i) => S(id, { status: st[i] ?? 'not_started' }));
const PARITY_CASES = [
  ['empty list, not started', [], 0, 'not_started', true],
  ['three not started', three(), 0, 'not_started', true],
  ['none done but in progress', three(), 0, 'in_progress', true],
  ['one of three done', three('completed'), 33, 'in_progress', true],
  ['two of three done', three('completed', 'completed'), 67, 'in_progress', true],
  ['all done', three('completed', 'completed', 'completed'), 100, 'completed', true],
  ['minutes = 1440', [S('a', { estimated_minutes: 1440 })], 0, 'not_started', true],
  ['minutes = 1441 (was rejected before Stage A)', [S('a', { estimated_minutes: 1441 })], 0, 'not_started', true],
  ['minutes = 100000', [S('a', { estimated_minutes: 100000 })], 0, 'not_started', true],
  ['minutes = max safe integer', [S('a', { estimated_minutes: 9007199254740991 })], 0, 'not_started', true],
  ['minutes = max safe integer + 1', [S('a', { estimated_minutes: 9007199254740992 })], 0, 'not_started', false],
  ['minutes = 0', [S('a', { estimated_minutes: 0 })], 0, 'not_started', false],
  ['minutes = -5', [S('a', { estimated_minutes: -5 })], 0, 'not_started', false],
  ['minutes = 1.5', [S('a', { estimated_minutes: 1.5 })], 0, 'not_started', false],
  ['minutes = "30"', [S('a', { estimated_minutes: '30' })], 0, 'not_started', false],
  ['minutes = true', [S('a', { estimated_minutes: true })], 0, 'not_started', false],
  ['extra key', [S('a', { due: '2026-11-20' })], 0, 'not_started', false],
  ['missing key', [(({ status, ...rest }) => rest)(S('a'))], 0, 'not_started', false],
  ['title with surrounding spaces', [S('a', { title: ' padded ' })], 0, 'not_started', false],
  ['empty title', [S('a', { title: '' })], 0, 'not_started', false],
  ['title of 121 characters', [S('a', { title: 'x'.repeat(121) })], 0, 'not_started', false],
  ['subtask status in_progress', [S('a', { status: 'in_progress' })], 0, 'not_started', false],
  ['duplicate subtask ids', [S('a'), S('a')], 0, 'not_started', false],
  ['progress does not match subtasks', three('completed'), 50, 'in_progress', false],
  ['all done but parent in progress', three('completed', 'completed', 'completed'), 100, 'in_progress', false],
  ['parent completed with one open subtask', three('completed', 'completed'), 67, 'completed', false],
  ['subtasks is not a list', 'garbage', 0, 'not_started', false],
  ['21 subtasks', Array.from({ length: 21 }, (_, i) => S('s' + i)), 0, 'not_started', false],
  ['some done but parent not started', three('completed'), 33, 'not_started', false],
  ['some done but parent not started (two of three)', three('completed', 'completed'), 67, 'not_started', false],
  ['none done but parent completed', three(), 0, 'completed', false],
  ['progress is false instead of 0', three(), false, 'not_started', false],
  ['progress is true while none done', three(), true, 'not_started', false],
];

test(`parity table: ${PARITY_CASES.length} stored-data cases are accepted or rejected exactly like the backend`, () => {
  for (const [name, subtasks, progress, status, accepted] of PARITY_CASES) {
    const db = fresh(); const t = addTask(db); const doc = db.tasks.find(x => x.task_id === t.task_id);
    Object.assign(doc, { subtasks, progress_pct: progress, status });
    const problems = validateV2Db(db);
    if (accepted) assert.deepEqual(problems, [], name); else assert.ok(problems.some(x => x.includes('subtasks')), `${name}: ${problems}`);
  }
});

test('recalculation: after every add / complete / reopen / delete the parent always matches its subtasks (1-6 subtasks, every state)', () => {
  for (let total = 1; total <= 6; total++) for (let mask = 0; mask < 1 << total; mask++) {
    const db = fresh(), p = parentWith(db, Array.from({ length: total }, (_, i) => 'S' + i)), id = p.task_id;
    for (let i = 0; i < total; i++) if (mask & (1 << i)) sub(db, id, 'complete', p.subtasks[i].subtask_id);
    assert.deepEqual(validateV2Db(db), [], `total ${total} mask ${mask}`);
    const t = get(db, id), done = [...Array(total)].filter((_, i) => mask & (1 << i)).length;
    assert.equal(t.progress_pct, percentDone(done, total)); assert.equal(t.status === 'completed', done === total);
  }
  const db = fresh(), p = parentWith(db, ['a', 'b']), id = p.task_id;
  sub(db, id, 'complete', p.subtasks[0].subtask_id); sub(db, id, 'complete', p.subtasks[1].subtask_id);
  assert.equal(get(db, id).status, 'completed'); addSubs(db, id, ['late']);
  assert.deepEqual([get(db, id).status, get(db, id).progress_pct], ['in_progress', 67]); assert.deepEqual(validateV2Db(db), []);
  sub(db, id, 'delete', get(db, id).subtasks[2].subtask_id); assert.equal(get(db, id).status, 'completed'); assert.deepEqual(validateV2Db(db), []);
});
