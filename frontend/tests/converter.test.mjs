// Run from the project root:  node --test frontend/tests/
// Tests the DORMANT mock-database v2 code (converter, validator, bootstrap, request engine) and the new ui.js helpers.
// No browser, no network, no packages: storage and "today" are faked. It never touches real localStorage.
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import {
  seed, KEYS, convertLegacyDb, validateV2Db, seedV2, bootstrapMockV2, startV2WithDemoData, mockV2Request, MockHttpError
} from '../js/api/mockData.js';
import { isCompleted, isDone, categoryLabel, importancePill, topOpenTask, importanceLabel } from '../js/ui.js';

const legacy = () => structuredClone(seed);
const task = over => ({ id: 'x1', title: 'T', course: 'Math', category: 'Assignment', priority: 'High', deadline: '2026-11-10', progress: 10, ...over });
const withTasks = (...tasks) => ({ ...legacy(), tasks });
const errorsOf = db => { const r = convertLegacyDb(db); assert.equal(r.ok, false, 'expected the conversion to be rejected'); return r.errors };

class FakeStorage {
  constructor(init = {}) { this.m = new Map(Object.entries(init)); this.log = []; this.failSet = new Set(); this.corrupt = new Set() }
  getItem(k) { return this.m.has(k) ? this.m.get(k) : null }
  setItem(k, v) { this.log.push(['set', k]); if (this.failSet.has(k)) throw new Error('QuotaExceededError'); this.m.set(k, this.corrupt.has(k) ? v + 'X' : String(v)) }
  removeItem(k) { this.log.push(['remove', k]); this.m.delete(k) }
  keys() { return [...this.m.keys()].sort() }
  writes() { return this.log.filter(([op]) => op === 'set' || op === 'remove') }
}
const RAW = JSON.stringify(seed);

// ---------------------------------------------------------------- guard: Batch 3.1 must stay dormant
test('client.js ships with MOCK_V2 = false and no top-level activation', () => {
  const src = readFileSync(new URL('../js/api/client.js', import.meta.url), 'utf8');
  assert.match(src, /^const MOCK_V2 = false;/m);
  assert.equal((src.match(/bootstrapMockV2\(/g) || []).length, 1, 'bootstrapMockV2 must only be called inside mockV2()');
  assert.ok(src.indexOf('bootstrapMockV2(') > src.indexOf('async function mockV2'));
});

test('the legacy seed export is unchanged', () => {
  assert.deepEqual(seed.tasks.map(t => t.id), ['t1', 't2', 't3', 't4', 't5']);
  assert.equal(seed.tasks[0].priority, 'High'); assert.equal(seed.tasks[3].category, 'Examination');
  assert.equal(seed.settings.weeklySummary, true); assert.equal(seed.settings.program, 'BS Computer Science');
});

// ---------------------------------------------------------------- conversion: the verified legacy shape
test('converts the current legacy seed', () => {
  const r = convertLegacyDb(legacy());
  assert.equal(r.ok, true); assert.deepEqual(validateV2Db(r.db), []);
  assert.equal(r.db.tasks.length, 5); assert.equal(r.db.subjects.length, 5); assert.equal(r.db.schema_version, 2);
  const byId = Object.fromEntries(r.db.tasks.map(t => [t.task_id, t]));
  assert.equal(byId.t4.category, 'exam'); assert.equal(byId.t4.status, 'not_started'); assert.equal(byId.t4.importance, 'medium');
  assert.equal(byId.t1.status, 'in_progress'); assert.equal(byId.t1.progress_pct, 65); assert.equal(byId.t1.importance, 'high');
  assert.equal(byId.t2.category, 'research'); assert.equal(byId.t3.category, 'project');
  assert.equal(r.db.subjects.find(s => s.subject_id === byId.t1.subject_id).subject_name, 'Computer Programming');
  assert.equal(r.db.settings.full_name, 'Student'); assert.deepEqual(Object.keys(r.db.settings), ['full_name', 'leadDays', 'sessionMinutes']);
  assert.deepEqual(Object.keys(r.db.user), ['id', 'name', 'email']);
  assert.deepEqual(r.report.droppedFields, ['user.program', 'settings.program', 'settings.weeklySummary']);
  assert.equal(r.db.history.completed, 12);
});
test('seedV2 returns a valid, independent object each time', () => {
  const a = seedV2(), b = seedV2(); assert.deepEqual(validateV2Db(a), []); a.tasks.pop(); assert.equal(b.tasks.length, 5);
});
test('the conversion never modifies its input', () => {
  const input = legacy(), snapshot = structuredClone(input);
  const deepFreeze = o => { Object.values(o).forEach(v => v && typeof v === 'object' && deepFreeze(v)); return Object.freeze(o) };
  assert.equal(convertLegacyDb(deepFreeze(input)).ok, true); assert.deepEqual(input, snapshot);
});
test('progress maps to status: 0, 1-99, 100', () => {
  const r = convertLegacyDb(withTasks(task({ id: 'a', progress: 0 }), task({ id: 'b', progress: 50 }), task({ id: 'c', progress: 100 }), task({ id: 'd', progress: 1 }), task({ id: 'e', progress: 99 })));
  assert.deepEqual(r.db.tasks.map(t => t.status), ['not_started', 'in_progress', 'completed', 'in_progress', 'in_progress']);
  assert.deepEqual(r.db.tasks.map(t => t.progress_pct), [0, 50, 100, 1, 99]);
});
test('empty, blank, missing or null course becomes the Uncategorized subject', () => {
  const r = convertLegacyDb(withTasks(task({ id: 'a', course: '' }), task({ id: 'b', course: '   ' }), task({ id: 'c', course: undefined }), task({ id: 'd', course: null })));
  assert.equal(r.ok, true); assert.deepEqual(r.db.subjects.map(s => s.subject_name), ['Uncategorized']); assert.equal(r.report.uncategorizedTasks, 4);
});
test('courses differing only in case or spacing share one subject (first spelling kept)', () => {
  const r = convertLegacyDb(withTasks(task({ id: 'a', course: 'Database  Systems' }), task({ id: 'b', course: ' database systems ' }), task({ id: 'c', course: 'DATABASE SYSTEMS' }), task({ id: 'd', course: 'Networks' })));
  assert.equal(r.db.subjects.length, 2); assert.equal(r.db.subjects[0].subject_name, 'Database Systems');
  assert.equal(new Set(r.db.tasks.slice(0, 3).map(t => t.subject_id)).size, 1); assert.deepEqual(validateV2Db(r.db), []);
});
test('duplicate and invalid legacy ids: every record is kept and ids end up unique', () => {
  const r = convertLegacyDb(withTasks(task({ id: 'dup' }), task({ id: 'dup' }), task({ id: 't_1' }), task({ id: 'bad id!' }), task({ id: 5 }), task({ id: undefined })));
  assert.equal(r.ok, true); assert.equal(r.db.tasks.length, 6);
  const ids = r.db.tasks.map(t => t.task_id); assert.equal(new Set(ids).size, 6);
  assert.equal(ids[0], 'dup'); assert.equal(ids[2], 't_1'); assert.equal(r.report.idsReassigned, 4);
  ids.forEach(i => assert.match(i, /^[A-Za-z0-9_-]{1,128}$/));
});
test('title is trimmed; empty, blank or over-long titles are rejected', () => {
  assert.equal(convertLegacyDb(withTasks(task({ title: '  Hello  ' }))).db.tasks[0].title, 'Hello');
  assert.equal(convertLegacyDb(withTasks(task({ title: 'x'.repeat(120) }))).ok, true);
  for (const title of ['', '   ', 'x'.repeat(121), 5, null, undefined]) assert.equal(convertLegacyDb(withTasks(task({ title }))).ok, false);
});
test('invalid category, priority, deadline, progress or course are rejected without echoing values', () => {
  const secret = 'SECRET-TITLE';
  const bad = [{ category: 'assignment' }, { category: 'Quiz' }, { priority: 'high' }, { priority: 'Urgent' }, { deadline: '2026-02-30' }, { deadline: '11/10/2026' }, { deadline: undefined },
    { progress: 101 }, { progress: -1 }, { progress: 5.5 }, { progress: '50' }, { progress: NaN }, { progress: null }, { course: 7 }, { course: 'c'.repeat(101) }, { extra: 1 }];
  for (const over of bad) {
    const errs = errorsOf(withTasks(task({ title: secret, ...over }))); assert.ok(errs.length >= 1, JSON.stringify(over));
    assert.ok(!JSON.stringify(errs).includes(secret) && !JSON.stringify(errs).includes('Math'), 'errors must not contain task text');
  }
});
test('a task missing a required field is rejected', () => {
  for (const key of ['title', 'category', 'priority', 'deadline', 'progress']) { const t = task(); delete t[key]; assert.equal(convertLegacyDb(withTasks(t)).ok, false, key) }
});
test('unsupported structures are rejected safely', () => {
  for (const bad of [null, undefined, 5, 'text', [], {}, { tasks: 'x' }, { tasks: {} }, { tasks: [null] }, { tasks: [5] }, { ...legacy(), subjects: [] }, { ...legacy(), version: 2 },
    { tasks: [{ task_id: 'a', subject_id: 's', title: 'T', deadline: '2026-11-10', importance: 'low', category: 'exam', progress_pct: 0, status: 'not_started' }] }]) {
    assert.equal(convertLegacyDb(bad).ok, false, JSON.stringify(bad)?.slice(0, 40));
  }
});
test('settings: bad lead days, session minutes, name or extra fields are rejected; empty name falls back', () => {
  for (const settings of [{ ...seed.settings, leadDays: 4 }, { ...seed.settings, sessionMinutes: 30 }, { ...seed.settings, name: 5 }, { ...seed.settings, name: 'n'.repeat(81) }, { ...seed.settings, theme: 'dark' }, { ...seed.settings, weeklySummary: 'yes' }, 'x'])
    assert.equal(convertLegacyDb({ ...legacy(), settings }).ok, false);
  assert.equal(convertLegacyDb({ ...legacy(), settings: { ...seed.settings, name: '  ' } }).db.settings.full_name, 'Student');
  assert.equal(convertLegacyDb({ ...legacy(), settings: { ...seed.settings, name: '  Ana  ' } }).db.settings.full_name, 'Ana');
  const d = legacy(); delete d.settings; const r = convertLegacyDb(d); assert.equal(r.ok, true); assert.deepEqual(r.report.defaulted, ['settings']); assert.equal(r.db.settings.leadDays, 2);
});
test('reminder preferences: non-boolean or unknown rejected; missing keys defaulted', () => {
  assert.equal(convertLegacyDb({ ...legacy(), reminderPrefs: { deadline: 'yes' } }).ok, false);
  assert.equal(convertLegacyDb({ ...legacy(), reminderPrefs: { sms: true } }).ok, false);
  const r = convertLegacyDb({ ...legacy(), reminderPrefs: { deadline: false } });
  assert.deepEqual(r.db.reminderPrefs, { deadline: false, dailySummary: true, progressCheckin: false, quietHours: true });
});
test('history and user: malformed rejected; missing defaulted', () => {
  assert.equal(convertLegacyDb({ ...legacy(), history: { completed: 1 } }).ok, false);
  assert.equal(convertLegacyDb({ ...legacy(), history: { ...seed.history, weeklyProductivity: [1, 2] } }).ok, false);
  assert.equal(convertLegacyDb({ ...legacy(), user: { id: 1, name: 'x', email: 'e' } }).ok, false);
  const d = legacy(); delete d.history; delete d.user; const r = convertLegacyDb(d); assert.equal(r.ok, true); assert.deepEqual(r.report.defaulted.sort(), ['history', 'user']);
});
test('an empty task list converts to an empty, valid database', () => {
  const r = convertLegacyDb(withTasks()); assert.equal(r.ok, true); assert.equal(r.db.tasks.length, 0); assert.equal(r.db.subjects.length, 0);
});

// ---------------------------------------------------------------- validator: the backend's real status/progress rules
const v2task = over => ({ task_id: 'a', subject_id: 'sub_1', title: 'T', deadline: '2026-11-10', importance: 'low', category: 'exam', progress_pct: 0, status: 'not_started', ...over });
const dbWith = (...tasks) => { const d = seedV2(); d.tasks = tasks; d.subjects = [{ subject_id: 'sub_1', subject_name: 'Math' }]; return d };
test('validator accepts every status/progress combination the API can produce', () => {
  for (const t of [v2task(), v2task({ progress_pct: 50 }) /* not_started edited */, v2task({ status: 'in_progress', progress_pct: 0 }),
    v2task({ status: 'in_progress', progress_pct: 100 }) /* reopened */, v2task({ status: 'completed', progress_pct: 100 })])
    assert.deepEqual(validateV2Db(dbWith(t)), [], JSON.stringify(t));
});
test('validator rejects what the API can never produce', () => {
  for (const t of [v2task({ status: 'completed', progress_pct: 99 }), v2task({ status: 'done' }), v2task({ progress_pct: true }), v2task({ progress_pct: 50.5 }), v2task({ progress_pct: '5' }),
    v2task({ progress_pct: 101 }), v2task({ subject_id: 'nope' }), v2task({ importance: 'High' }), v2task({ category: 'Exam' }), v2task({ deadline: '2026-13-01' }), v2task({ title: ' padded ' }), v2task({ extra: 1 })])
    assert.notDeepEqual(validateV2Db(dbWith(t)), [], JSON.stringify(t));
});
test('validator rejects duplicate ids, duplicate subject names, wrong schema and non-objects', () => {
  assert.notDeepEqual(validateV2Db(dbWith(v2task(), v2task())), []);
  const d = dbWith(); d.subjects.push({ subject_id: 'sub_2', subject_name: ' MATH ' }); assert.notDeepEqual(validateV2Db(d), []);
  const e = seedV2(); e.schema_version = 1; assert.notDeepEqual(validateV2Db(e), []);
  for (const x of [null, [], 'x', 1]) assert.notDeepEqual(validateV2Db(x), []);
  const f = seedV2(); f.settings.leadDays = 4; assert.notDeepEqual(validateV2Db(f), []);
});

// ---------------------------------------------------------------- bootstrap: backup, conversion, recovery
test('nothing at all stored: only the v2 key is written (no backup)', () => {
  const s = new FakeStorage(), r = bootstrapMockV2(s, 1000); assert.equal(r.ok, true); assert.equal(r.source, 'seed'); assert.deepEqual(s.keys(), [KEYS.v2]);
});
test('legacy data: verified backup, v2 written, legacy key byte-identical and never written', () => {
  const s = new FakeStorage({ [KEYS.legacy]: RAW }), r = bootstrapMockV2(s, 1000);
  assert.equal(r.ok, true); assert.equal(r.source, 'converted'); assert.equal(r.backupKey, KEYS.backupPrefix + '1000');
  assert.deepEqual(s.keys(), [KEYS.legacy, r.backupKey, KEYS.v2].sort());
  assert.equal(s.getItem(KEYS.legacy), RAW); assert.equal(s.getItem(r.backupKey), RAW);
  assert.deepEqual(JSON.parse(s.getItem(KEYS.v2)), r.db); assert.deepEqual(validateV2Db(r.db), []);
  assert.ok(!s.log.some(([, k]) => k === KEYS.legacy), 'the legacy key must not be written or removed');
  assert.ok(s.log.findIndex(([, k]) => k === r.backupKey) < s.log.findIndex(([, k]) => k === KEYS.v2), 'backup must come before the v2 write');
});
test('running it again is a no-op: no new keys, no writes', () => {
  const s = new FakeStorage({ [KEYS.legacy]: RAW }); bootstrapMockV2(s, 1000); const before = s.keys(), n = s.log.length;
  const r = bootstrapMockV2(s, 2000); assert.equal(r.ok, true); assert.equal(r.source, 'v2'); assert.deepEqual(s.keys(), before); assert.equal(s.log.length, n);
});
test('a valid v2 key wins over legacy data and nothing is written', () => {
  const s = new FakeStorage({ [KEYS.legacy]: RAW, [KEYS.v2]: JSON.stringify(seedV2()) }), r = bootstrapMockV2(s, 5);
  assert.equal(r.ok, true); assert.equal(r.source, 'v2'); assert.equal(s.writes().length, 0);
});
test('a damaged v2 key is reported and left exactly as it was (no writes at all)', () => {
  for (const raw of ['{not json', '{"schema_version":2}', 'null']) {
    const s = new FakeStorage({ [KEYS.legacy]: RAW, [KEYS.v2]: raw }), r = bootstrapMockV2(s, 5);
    assert.equal(r.ok, false); assert.equal(r.code, 'V2_INVALID'); assert.equal(s.getItem(KEYS.v2), raw); assert.equal(s.writes().length, 0);
  }
});
test('backup write fails: nothing converted, no v2 key, legacy untouched', () => {
  const s = new FakeStorage({ [KEYS.legacy]: RAW }); s.failSet.add(KEYS.backupPrefix + '1000');
  const r = bootstrapMockV2(s, 1000); assert.equal(r.ok, false); assert.equal(r.code, 'BACKUP_FAILED');
  assert.deepEqual(s.keys(), [KEYS.legacy]); assert.equal(s.getItem(KEYS.legacy), RAW);
});
test('backup does not read back identically: aborted, bad backup removed, no v2 key', () => {
  const s = new FakeStorage({ [KEYS.legacy]: RAW }); s.corrupt.add(KEYS.backupPrefix + '1000');
  const r = bootstrapMockV2(s, 1000); assert.equal(r.ok, false); assert.equal(r.code, 'BACKUP_FAILED'); assert.deepEqual(s.keys(), [KEYS.legacy]);
});
test('unreadable legacy JSON: backup kept, no v2 key, legacy untouched, clear message', () => {
  const s = new FakeStorage({ [KEYS.legacy]: '{broken' }), r = bootstrapMockV2(s, 1000);
  assert.equal(r.ok, false); assert.equal(r.code, 'LEGACY_UNREADABLE'); assert.equal(s.getItem(r.backupKey), '{broken'); assert.equal(s.getItem(KEYS.legacy), '{broken');
  assert.ok(!s.keys().includes(KEYS.v2)); assert.match(r.message, /not changed/); assert.ok(r.message.includes(r.backupKey));
});
test('unsupported legacy structure: backup kept, error list returned, no v2 key', () => {
  const bad = JSON.stringify({ ...legacy(), tasks: [task({ category: 'Seminar' })] }), s = new FakeStorage({ [KEYS.legacy]: bad }), r = bootstrapMockV2(s, 1000);
  assert.equal(r.ok, false); assert.equal(r.code, 'LEGACY_UNSUPPORTED'); assert.ok(r.errors.length > 0);
  assert.equal(s.getItem(r.backupKey), bad); assert.equal(s.getItem(KEYS.legacy), bad); assert.ok(!s.keys().includes(KEYS.v2));
});
test('v2 write fails (storage full): reported, no v2 key left, legacy and backup intact', () => {
  const s = new FakeStorage({ [KEYS.legacy]: RAW }); s.failSet.add(KEYS.v2);
  const r = bootstrapMockV2(s, 1000); assert.equal(r.ok, false); assert.equal(r.code, 'WRITE_FAILED');
  assert.ok(!s.keys().includes(KEYS.v2)); assert.equal(s.getItem(KEYS.legacy), RAW); assert.equal(s.getItem(r.backupKey), RAW);
});
test('v2 write read-back mismatch: the bad v2 key is removed', () => {
  const s = new FakeStorage({ [KEYS.legacy]: RAW }); s.corrupt.add(KEYS.v2);
  assert.equal(bootstrapMockV2(s, 1000).ok, false); assert.ok(!s.keys().includes(KEYS.v2));
});
test('a backup key is never overwritten: a second backup at the same instant gets a new key', () => {
  const s = new FakeStorage({ [KEYS.legacy]: RAW, [KEYS.backupPrefix + '1000']: 'EARLIER BACKUP' }), r = bootstrapMockV2(s, 1000);
  assert.equal(r.ok, true); assert.equal(s.getItem(KEYS.backupPrefix + '1000'), 'EARLIER BACKUP'); assert.equal(r.backupKey, KEYS.backupPrefix + '1000_2'); assert.equal(s.getItem(r.backupKey), RAW);
});
test('storage that throws on read: reported, nothing written', () => {
  const s = new FakeStorage(); s.getItem = () => { throw new Error('denied') };
  const r = bootstrapMockV2(s, 1); assert.equal(r.ok, false); assert.equal(r.code, 'STORAGE_UNAVAILABLE'); assert.equal(s.writes().length, 0);
});
test('startV2WithDemoData writes only a fresh v2 and refuses when one exists', () => {
  const s = new FakeStorage({ [KEYS.legacy]: '{broken' }), r = startV2WithDemoData(s);
  assert.equal(r.ok, true); assert.deepEqual(s.keys(), [KEYS.legacy, KEYS.v2].sort()); assert.equal(s.getItem(KEYS.legacy), '{broken');
  const again = startV2WithDemoData(s); assert.equal(again.ok, false); assert.equal(again.code, 'V2_EXISTS');
});

// ---------------------------------------------------------------- mock engine: imitates the Phase 1 API
const NOW = { todayIso: '2026-11-16' };
let counter = 0; const ctx = { ...NOW, newId: p => `${p}${++counter}` };
const call = (db, method, path, body) => mockV2Request(db, method, path, body, ctx);
const rejects = (fn, status, pattern) => assert.throws(fn, e => e instanceof MockHttpError && e.status === status && (!pattern || pattern.test(e.message)), `expected ${status}`);
const fresh = () => { const db = seedV2(); db.tasks = []; db.subjects = []; return db };
const NEW_TASK = { title: 'Essay', subject_id: '', category: 'assignment', deadline: '2026-11-20', importance: 'high' };
const TASK_FIELDS = ['task_id', 'subject_id', 'title', 'deadline', 'importance', 'category', 'progress_pct', 'status'];

test('engine subjects: create, list sorted, rename, delete; duplicates 422; in-use delete 409; missing 404', () => {
  const db = fresh(), b = call(db, 'POST', '/subjects', { subject_name: '  Biology ' }), a = call(db, 'POST', '/subjects', { subject_name: 'Algebra' });
  assert.deepEqual(Object.keys(b), ['subject_id', 'subject_name']); assert.equal(b.subject_name, 'Biology');
  assert.deepEqual(call(db, 'GET', '/subjects').map(s => s.subject_name), ['Algebra', 'Biology']);
  rejects(() => call(db, 'POST', '/subjects', { subject_name: 'algebra ' }), 422, /already have a subject/);
  rejects(() => call(db, 'POST', '/subjects', { subject_name: '' }), 422); rejects(() => call(db, 'POST', '/subjects', {}), 422, /subject_name: is required/);
  rejects(() => call(db, 'POST', '/subjects', 'x'), 400);
  assert.equal(call(db, 'PATCH', `/subjects/${a.subject_id}`, { subject_name: 'Algebra II' }).subject_name, 'Algebra II');
  call(db, 'PATCH', `/subjects/${a.subject_id}`, { subject_name: 'ALGEBRA II' }); // renaming to its own name (different case) is allowed
  rejects(() => call(db, 'PATCH', `/subjects/${a.subject_id}`, { subject_name: 'biology' }), 422, /already have/);
  rejects(() => call(db, 'PATCH', `/subjects/${a.subject_id}`, {}), 422, /send at least one/);
  rejects(() => call(db, 'PATCH', '/subjects/missing', { subject_name: 'Z' }), 404); rejects(() => call(db, 'PATCH', '/subjects/bad id', { subject_name: 'Z' }), 404);
  call(db, 'POST', '/tasks', { ...NEW_TASK, subject_id: a.subject_id });
  rejects(() => call(db, 'DELETE', `/subjects/${a.subject_id}`), 409, /still has tasks/);
  assert.equal(call(db, 'DELETE', `/subjects/${b.subject_id}`), null); rejects(() => call(db, 'DELETE', `/subjects/${b.subject_id}`), 404);
  assert.deepEqual(validateV2Db(db), []);
});
test('engine task create: exact public fields, server-owned status/progress, subject must exist', () => {
  const db = fresh(), s = call(db, 'POST', '/subjects', { subject_name: 'Math' }), t = call(db, 'POST', '/tasks', { ...NEW_TASK, subject_id: s.subject_id });
  assert.deepEqual(Object.keys(t), TASK_FIELDS); assert.equal(t.status, 'not_started'); assert.equal(t.progress_pct, 0);
  rejects(() => call(db, 'POST', '/tasks', { ...NEW_TASK, subject_id: s.subject_id, status: 'completed' }), 422, /status: is set by the server/);
  rejects(() => call(db, 'POST', '/tasks', { ...NEW_TASK, subject_id: s.subject_id, progress_pct: 50 }), 422, /progress_pct: is set by the server/);
  rejects(() => call(db, 'POST', '/tasks', { ...NEW_TASK, subject_id: 'nope' }), 422, /must be one of your subjects/);
  for (const bad of [{ title: '' }, { title: 'x'.repeat(121) }, { category: 'Exam' }, { importance: 'urgent' }, { deadline: '2026-02-30' }, { deadline: undefined }]) rejects(() => call(db, 'POST', '/tasks', { ...NEW_TASK, subject_id: s.subject_id, ...bad }), 422);
  assert.equal(db.tasks.length, 1); assert.deepEqual(validateV2Db(db), []);
});
test('engine task update: progress edits never change status; completed cannot drop below 100; PATCH cannot set status', () => {
  const db = fresh(), s = call(db, 'POST', '/subjects', { subject_name: 'Math' }), t = call(db, 'POST', '/tasks', { ...NEW_TASK, subject_id: s.subject_id }), url = `/tasks/${t.task_id}`;
  let r = call(db, 'PATCH', url, { progress_pct: 40 }); assert.equal(r.progress_pct, 40); assert.equal(r.status, 'not_started'); assert.deepEqual(validateV2Db(db), []);
  assert.equal(call(db, 'PATCH', url, { title: ' New ', importance: 'low' }).title, 'New');
  rejects(() => call(db, 'PATCH', url, { status: 'completed' }), 422, /cannot be changed here/);
  rejects(() => call(db, 'PATCH', url, { progress_pct: 101 }), 422); rejects(() => call(db, 'PATCH', url, {}), 422, /send at least one/);
  rejects(() => call(db, 'PATCH', url, { subject_id: 'nope' }), 422, /one of your subjects/); rejects(() => call(db, 'PATCH', '/tasks/missing', { title: 'x' }), 404);
  call(db, 'POST', url + '/complete'); rejects(() => call(db, 'PATCH', url, { progress_pct: 99 }), 422, /stays at 100%/);
  assert.equal(call(db, 'PATCH', url, { progress_pct: 100, title: 'Still ok' }).status, 'completed');
});
test('engine transitions: start / complete / reopen, including reopened = in_progress at 100%', () => {
  const db = fresh(), s = call(db, 'POST', '/subjects', { subject_name: 'Math' }), t = call(db, 'POST', '/tasks', { ...NEW_TASK, subject_id: s.subject_id }), url = `/tasks/${t.task_id}`;
  rejects(() => call(db, 'POST', url + '/reopen'), 409, /Only a completed task/);
  assert.equal(call(db, 'POST', url + '/start').status, 'in_progress'); assert.equal(call(db, 'POST', url + '/start').status, 'in_progress');
  const done = call(db, 'POST', url + '/complete'); assert.equal(done.status, 'completed'); assert.equal(done.progress_pct, 100);
  assert.equal(call(db, 'POST', url + '/complete').progress_pct, 100); rejects(() => call(db, 'POST', url + '/start'), 409, /Use reopen/);
  const re = call(db, 'POST', url + '/reopen'); assert.equal(re.status, 'in_progress'); assert.equal(re.progress_pct, 100);
  assert.deepEqual(validateV2Db(db), [], 'a reopened task (in_progress at 100%) must be valid');
  assert.equal(call(db, 'PATCH', url, { progress_pct: 60 }).progress_pct, 60); // allowed again after reopen
  rejects(() => call(db, 'POST', '/tasks/missing/complete'), 404); rejects(() => call(db, 'POST', url + '/finish'), 404);
  assert.equal(call(db, 'DELETE', url), null); rejects(() => call(db, 'DELETE', url), 404); assert.equal(call(db, 'GET', '/tasks').length, 0);
});
test('engine: a rejected request never changes the database', () => {
  const db = seedV2(), before = structuredClone(db), id = db.tasks[0].task_id;
  const bad = [['POST', '/subjects', { subject_name: '' }], ['POST', '/tasks', { title: 'x' }], ['PATCH', `/tasks/${id}`, { title: 'ok', progress_pct: 500 }], ['PATCH', `/tasks/${id}`, { title: 'ok', status: 'completed' }],
    ['DELETE', `/subjects/${db.tasks[0].subject_id}`], ['POST', `/tasks/${id}/reopen`], ['PUT', '/settings', { full_name: 'ok', leadDays: 4 }], ['PUT', '/reminders/preferences', { deadline: false, quietHours: 'no' }], ['GET', '/nope']];
  for (const [m, p, b] of bad) assert.throws(() => call(db, m, p, b), MockHttpError);
  assert.deepEqual(db, before);
});
test('engine settings and reminder preferences use the backend field names and rules', () => {
  const db = seedV2(); assert.deepEqual(call(db, 'GET', '/settings'), { full_name: 'Student', leadDays: 2, sessionMinutes: 45 });
  assert.deepEqual(call(db, 'PUT', '/settings', { full_name: ' Ana ', leadDays: 5 }), { full_name: 'Ana', leadDays: 5, sessionMinutes: 45 });
  call(db, 'PUT', '/settings', { program: 'ignored', weeklySummary: true, sessionMinutes: 60 }); assert.equal(call(db, 'GET', '/settings').sessionMinutes, 60); assert.ok(!('program' in db.settings));
  rejects(() => call(db, 'PUT', '/settings', {}), 422); rejects(() => call(db, 'PUT', '/settings', { sessionMinutes: 30 }), 422); rejects(() => call(db, 'PUT', '/settings', { full_name: '' }), 422);
  assert.equal(call(db, 'PUT', '/reminders/preferences', { deadline: false }).deadline, false); assert.equal(call(db, 'GET', '/reminders/preferences').dailySummary, true);
  assert.deepEqual(validateV2Db(db), []);
});
test('engine progress: contract keys, counts from status, overdue uses the given today', () => {
  const db = fresh(), s = call(db, 'POST', '/subjects', { subject_name: 'Math' });
  const mk = (deadline) => call(db, 'POST', '/tasks', { ...NEW_TASK, subject_id: s.subject_id, deadline });
  const late = mk('2026-11-01'), ok = mk('2026-12-01'), done = mk('2026-11-02'); call(db, 'POST', `/tasks/${done.task_id}/complete`);
  const p = call(db, 'GET', '/progress');
  assert.deepEqual(Object.keys(p).sort(), ['completed', 'completionRate', 'insight', 'insightSource', 'onTimeRate', 'overdue', 'weeklyChange', 'weeklyCompletion', 'weeklyProductivity'].sort());
  assert.equal(p.overdue, 1); assert.equal(p.completed, 12 + 1); assert.equal(p.weeklyProductivity.length, 7); assert.equal(p.weeklyCompletion.length, 4); assert.equal(p.insightSource, 'mock-sample');
  assert.ok(late && ok);
});
test('engine AI endpoints: labelled mock, validated, and shaped like the backend', () => {
  const db = seedV2(), plan = call(db, 'POST', '/ai/plan', { title: 'Paper', requirements: '', deadline: '2026-11-26', hoursPerDay: '1' });
  assert.equal(plan.mock, true); assert.equal(plan.aiGenerated, false); assert.equal(plan.subtasks.length, 5); assert.equal(plan.subtasks[4].dueDate, '2026-11-26'); assert.ok(plan.notice);
  assert.deepEqual(Object.keys(plan.subtasks[0]), ['title', 'dueDate', 'minutes']);
  rejects(() => call(db, 'POST', '/ai/plan', { title: 'Paper', deadline: '2026-11-26', hoursPerDay: 9 }), 422, /hoursPerDay/); rejects(() => call(db, 'POST', '/ai/plan', { deadline: '2026-11-26' }), 422, /title: is required/);
  assert.match(call(db, 'POST', '/ai/chat', { message: 'What should I work on first?' }).reply, /start with "Research Paper: Artificial Intelligence"/);
  assert.match(call(db, 'POST', '/ai/chat', { message: 'what is due soon' }).reply, /^Upcoming: /); rejects(() => call(db, 'POST', '/ai/chat', { message: '  ' }), 422);
  assert.equal(call(fresh(), 'POST', '/ai/chat', { message: 'priorities?' }).reply, 'You have no open tasks.');
});
test('engine auth (mock only) and unknown routes', () => {
  const db = seedV2(); rejects(() => call(db, 'POST', '/auth/login', { email: 'a@b.c', password: '123' }), 401);
  assert.equal(call(db, 'POST', '/auth/login', { email: 'a@b.c', password: '123456' }).token, 'mock-token');
  rejects(() => call(db, 'POST', '/auth/register', { name: 'A', email: 'a@b.c', password: '1' }), 422);
  const r = call(db, 'POST', '/auth/register', { name: ' Ana ', email: 'a@b.c', password: '123456', program: 'ignored' }); assert.deepEqual(r.user, { id: 'u1', name: 'Ana', email: 'a@b.c' });
  assert.equal(db.settings.full_name, 'Ana'); assert.deepEqual(validateV2Db(db), []);
  rejects(() => call(db, 'GET', '/unknown'), 404); rejects(() => call(db, 'DELETE', '/tasks'), 405);
});

// ---------------------------------------------------------------- ui.js helpers added in this batch (legacy helpers untouched)
test('ui helpers: status decides "done", labels, pill and top pick', () => {
  assert.equal(isCompleted({ status: 'completed' }), true); assert.equal(isCompleted({ status: 'in_progress', progress_pct: 100 }), false); assert.equal(isCompleted(undefined), false);
  assert.equal(isDone({ progress: 100 }), true); assert.equal(isDone({ progress: 99 }), false); // legacy helper behaves as before
  assert.equal(categoryLabel('exam'), 'Exam'); assert.equal(categoryLabel('weird'), 'weird'); assert.equal(importanceLabel('low'), 'Low');
  assert.equal(importancePill('high'), '<span class="pill high">High</span>'); assert.equal(importancePill('"><img>'), '<span class="pill medium">Medium</span>');
  const ts = [{ task_id: 'a', importance: 'low', progress_pct: 0, deadline: '2026-11-03', status: 'not_started' }, { task_id: 'b', importance: 'high', progress_pct: 50, deadline: '2026-11-09', status: 'in_progress' },
    { task_id: 'c', importance: 'high', progress_pct: 10, deadline: '2026-11-20', status: 'not_started' }, { task_id: 'd', importance: 'high', progress_pct: 0, deadline: '2026-11-01', status: 'completed' }];
  assert.equal(topOpenTask(ts).task_id, 'c'); assert.equal(topOpenTask(ts.filter(t => t.importance !== 'high')).task_id, 'a');
  assert.equal(topOpenTask([ts[3]]), undefined); assert.equal(topOpenTask([]), undefined);
});
