// MOCK DATA ONLY. Shapes here mirror the backend contract in README.md.
export const seed={
 user:{id:'u1',name:'Student',email:'student@example.com',program:'BS Computer Science'},
 tasks:[
  {id:'t1',title:'Programming Activity 05',course:'Computer Programming',category:'Assignment',deadline:'2026-11-01',priority:'High',progress:65},
  {id:'t2',title:'Research Paper: Artificial Intelligence',course:'Research Methods',category:'Research',deadline:'2026-11-03',priority:'High',progress:20},
  {id:'t3',title:'Database Design Project',course:'Database Systems',category:'Project',deadline:'2026-11-06',priority:'Medium',progress:45},
  {id:'t4',title:'Operating Systems Quiz',course:'Operating Systems',category:'Examination',deadline:'2026-11-08',priority:'Medium',progress:0},
  {id:'t5',title:'UI/UX Reflection',course:'Human Computer Interaction',category:'Assignment',deadline:'2026-11-10',priority:'Low',progress:80}],
 settings:{name:'Student',program:'BS Computer Science',leadDays:2,sessionMinutes:45,weeklySummary:true},
 reminderPrefs:{deadline:true,dailySummary:true,progressCheckin:false,quietHours:true},
 history:{completed:12,completionRate:76,onTimeRate:84,weeklyChange:8,weeklyProductivity:[4,6,5,8,5,3,2],weeklyCompletion:[2,4,5,7],
  insight:'Your recorded activity shows research tasks have been delayed more often than assignments this month. Try splitting research work into shorter sessions and setting an earlier personal target date.'}
};

// ===================================================================================================================
// MOCK DATABASE V2 (Phase 3, Batch 3.1). DORMANT: nothing below runs while MOCK_V2 is false in client.js.
// It mirrors the Phase 1 backend contract (subjects, tasks with status + progress_pct, settings, reminder prefs).
// Everything here is pure: storage and "today" are passed in, so it can be tested in Node without a browser.
// This file never touches localStorage by itself. Only bootstrapMockV2 / startV2WithDemoData write, and only to the
// storage object they are given.
// ===================================================================================================================
export const KEYS = { legacy: 'taim_mock_db', v2: 'taim_mock_db_v2', backupPrefix: 'taim_mock_db_backup_v1_' };
// These lists mirror backend/validation.py. The server stays the authority; mock mode only imitates it.
export const CATEGORIES = ['assignment', 'project', 'exam', 'quiz', 'research', 'other'];
export const IMPORTANCE = ['low', 'medium', 'high'];
export const STATUSES = ['not_started', 'in_progress', 'completed'];
export const LEAD_DAYS = [1, 2, 3, 5, 7];
export const SESSION_MINUTES = [25, 45, 60, 90];
export const MAX_SUBTASKS = 20;
export const SUBTASK_STATUSES = ['not_started', 'completed'];
// Parent progress from subtasks: whole numbers, rounded half up with integer maths. MUST match backend/store.py.
export const percentDone = (done, total) => total ? Math.floor((done * 100 + Math.floor(total / 2)) / total) : 0;
export const REMINDER_DEFAULTS = { deadline: true, dailySummary: true, progressCheckin: false, quietHours: true };
export const UNCATEGORIZED = 'Uncategorized';
const CATEGORY_MAP = { Assignment: 'assignment', Research: 'research', Project: 'project', Examination: 'exam' };
const PRIORITY_MAP = { High: 'high', Medium: 'medium', Low: 'low' };

export class MockHttpError extends Error {
  constructor(status, detail, errors) { super(detail); this.status = status; this.errors = errors }
}

// ---- small helpers ----
const ID_RE = /^[A-Za-z0-9_-]{1,128}$/;
const DATE_RE = /^[0-9]{4}-[0-9]{2}-[0-9]{2}$/;
const isObj = v => v !== null && typeof v === 'object' && !Array.isArray(v);
const isInt = v => typeof v === 'number' && Number.isInteger(v);
const isNum = v => typeof v === 'number' && Number.isFinite(v);
export const isRealDate = s => {
  if (typeof s !== 'string' || !DATE_RE.test(s)) return false;
  const [y, m, d] = s.split('-').map(Number), t = new Date(Date.UTC(2000, 0, 1)); t.setUTCFullYear(y, m - 1, d);
  return t.getUTCFullYear() === y && t.getUTCMonth() === m - 1 && t.getUTCDate() === d;
};
const collapse = s => s.split(/\s+/).filter(Boolean).join(' ');
export const normalizeName = s => collapse(s).normalize('NFC').toLowerCase(); // same idea as the backend's casefold
const dayNumber = iso => { const [y, m, d] = iso.split('-').map(Number); return Date.UTC(y, m - 1, d) / 864e5 };
const addDaysIso = (iso, k) => { const t = new Date((dayNumber(iso) + k) * 864e5); return t.toISOString().slice(0, 10) };
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const shortDate = iso => `${MONTHS[+iso.slice(5, 7) - 1]} ${+iso.slice(8, 10)}`;
const dueWords = n => n < 0 ? 'overdue' : n === 0 ? 'due today' : n === 1 ? 'due tomorrow' : `due in ${n} days`;

// ---- Validation of a stored V2 database. Returns a list of problems (field paths only, never values). ----
const TASK_KEYS = ['task_id', 'subject_id', 'title', 'deadline', 'importance', 'category', 'progress_pct', 'status'];
const SUBTASK_KEYS = ['subtask_id', 'title', 'estimated_minutes', 'status'];
const HISTORY_KEYS = ['completed', 'completionRate', 'onTimeRate', 'weeklyChange', 'weeklyProductivity', 'weeklyCompletion', 'insight'];
const sameKeys = (o, keys) => Object.keys(o).length === keys.length && keys.every(k => Object.hasOwn(o, k));

function historyProblems(h, label) {
  if (!isObj(h)) return [`${label}: must be an object.`];
  const p = [];
  if (!sameKeys(h, HISTORY_KEYS)) p.push(`${label}: must have exactly these fields: ${HISTORY_KEYS.join(', ')}.`);
  for (const k of ['completed', 'completionRate', 'onTimeRate', 'weeklyChange']) if (!isNum(h[k])) p.push(`${label}.${k}: must be a number.`);
  for (const [k, n] of [['weeklyProductivity', 7], ['weeklyCompletion', 4]]) if (!Array.isArray(h[k]) || h[k].length !== n || !h[k].every(isNum)) p.push(`${label}.${k}: must be ${n} numbers.`);
  if (typeof h.insight !== 'string') p.push(`${label}.insight: must be text.`);
  return p;
}

function subtaskProblems(t, at) {
  const p = [], items = t.subtasks;
  if (!Array.isArray(items) || items.length > MAX_SUBTASKS) return [`${at}.subtasks: must be a list of at most ${MAX_SUBTASKS}.`];
  const ids = new Set();
  items.forEach((s, i) => {
    const sat = `${at}.subtasks[${i}]`;
    if (!isObj(s) || !sameKeys(s, SUBTASK_KEYS)) return p.push(`${sat}: must have exactly these fields: ${SUBTASK_KEYS.join(', ')}.`);
    if (typeof s.subtask_id !== 'string' || !ID_RE.test(s.subtask_id)) p.push(`${sat}.subtask_id: not a valid id.`);
    else if (ids.has(s.subtask_id)) p.push(`${sat}.subtask_id: duplicate id.`); else ids.add(s.subtask_id);
    if (typeof s.title !== 'string' || !s.title.trim() || s.title.length > 120 || s.title !== s.title.trim()) p.push(`${sat}.title: must be 1-120 characters of trimmed text.`);
    if (!Number.isSafeInteger(s.estimated_minutes) || s.estimated_minutes < 1) p.push(`${sat}.estimated_minutes: must be a whole number of minutes, at least 1 (at most ${Number.MAX_SAFE_INTEGER}).`);
    if (!SUBTASK_STATUSES.includes(s.status)) p.push(`${sat}.status: not an allowed value.`);
  });
  // While subtasks exist they alone decide the parent's progress and status.
  if (!p.length && items.length) {
    const done = items.filter(s => s.status === 'completed').length;
    if (typeof t.progress_pct !== 'number' || t.progress_pct !== percentDone(done, items.length)) p.push(`${at}.progress_pct: does not match its subtasks.`);
    const okStatus = done === items.length ? ['completed'] : done ? ['in_progress'] : ['not_started', 'in_progress'];
    if (!okStatus.includes(t.status)) p.push(`${at}.status: does not match its subtasks.`);
  }
  return p;
}

export function validateV2Db(db) {
  if (!isObj(db)) return ['database: must be an object.'];
  const p = [], keys = ['schema_version', 'user', 'settings', 'reminderPrefs', 'subjects', 'tasks', 'history'];
  if (!sameKeys(db, keys)) p.push(`database: must have exactly these fields: ${keys.join(', ')}.`);
  if (db.schema_version !== 2) p.push('schema_version: must be 2.');
  if (!isObj(db.user) || !sameKeys(db.user, ['id', 'name', 'email']) || !['id', 'name', 'email'].every(k => typeof db.user[k] === 'string')) p.push('user: must be {id, name, email} as text.');
  const s = db.settings;
  if (!isObj(s) || !sameKeys(s, ['full_name', 'leadDays', 'sessionMinutes'])) p.push('settings: must be {full_name, leadDays, sessionMinutes}.');
  else {
    if (typeof s.full_name !== 'string' || !s.full_name.trim() || s.full_name.length > 80 || s.full_name !== s.full_name.trim()) p.push('settings.full_name: must be 1-80 characters of trimmed text.');
    if (!LEAD_DAYS.includes(s.leadDays)) p.push('settings.leadDays: not an allowed value.');
    if (!SESSION_MINUTES.includes(s.sessionMinutes)) p.push('settings.sessionMinutes: not an allowed value.');
  }
  const r = db.reminderPrefs;
  if (!isObj(r) || !sameKeys(r, Object.keys(REMINDER_DEFAULTS)) || !Object.values(r).every(v => typeof v === 'boolean')) p.push('reminderPrefs: must be the four true/false preferences.');
  p.push(...historyProblems(db.history, 'history'));

  const subjectIds = new Set(), names = new Set();
  if (!Array.isArray(db.subjects)) p.push('subjects: must be a list.');
  else db.subjects.forEach((x, i) => {
    const at = `subjects[${i}]`;
    if (!isObj(x) || !sameKeys(x, ['subject_id', 'subject_name'])) return p.push(`${at}: must be {subject_id, subject_name}.`);
    if (typeof x.subject_id !== 'string' || !ID_RE.test(x.subject_id)) p.push(`${at}.subject_id: not a valid id.`);
    else if (subjectIds.has(x.subject_id)) p.push(`${at}.subject_id: duplicate id.`); else subjectIds.add(x.subject_id);
    if (typeof x.subject_name !== 'string' || !x.subject_name.trim() || x.subject_name.length > 100 || x.subject_name !== collapse(x.subject_name)) p.push(`${at}.subject_name: must be 1-100 characters of clean text.`);
    else if (names.has(normalizeName(x.subject_name))) p.push(`${at}.subject_name: duplicate name.`); else names.add(normalizeName(x.subject_name));
  });
  const taskIds = new Set();
  if (!Array.isArray(db.tasks)) p.push('tasks: must be a list.');
  else db.tasks.forEach((t, i) => {
    const at = `tasks[${i}]`;
    // `subtasks` is optional: tasks saved before subtasks existed have no such field.
    const keys = isObj(t) && Object.hasOwn(t, 'subtasks') ? [...TASK_KEYS, 'subtasks'] : TASK_KEYS;
    if (!isObj(t) || !sameKeys(t, keys)) return p.push(`${at}: must have exactly these fields: ${TASK_KEYS.join(', ')} (and optionally subtasks).`);
    if (typeof t.task_id !== 'string' || !ID_RE.test(t.task_id)) p.push(`${at}.task_id: not a valid id.`);
    else if (taskIds.has(t.task_id)) p.push(`${at}.task_id: duplicate id.`); else taskIds.add(t.task_id);
    if (!subjectIds.has(t.subject_id)) p.push(`${at}.subject_id: does not match any subject.`);
    if (typeof t.title !== 'string' || !t.title.trim() || t.title.length > 120 || t.title !== t.title.trim()) p.push(`${at}.title: must be 1-120 characters of trimmed text.`);
    if (!isRealDate(t.deadline)) p.push(`${at}.deadline: not a real YYYY-MM-DD date.`);
    if (!IMPORTANCE.includes(t.importance)) p.push(`${at}.importance: not an allowed value.`);
    if (!CATEGORIES.includes(t.category)) p.push(`${at}.category: not an allowed value.`);
    if (!isInt(t.progress_pct) || t.progress_pct < 0 || t.progress_pct > 100) p.push(`${at}.progress_pct: must be a whole number 0-100.`);
    if (!STATUSES.includes(t.status)) p.push(`${at}.status: not an allowed value.`);
    // The only coupling the backend enforces: a completed task is at 100%. Reopened tasks (in_progress at 100) and
    // not_started tasks with progress are legitimate, because editing progress never changes status.
    else if (t.status === 'completed' && t.progress_pct !== 100) p.push(`${at}: a completed task must be at 100%.`);
    if (Object.hasOwn(t, 'subtasks')) p.push(...subtaskProblems(t, at));
  });
  return p;
}

// ---- Converter: legacy mock database (taim_mock_db) -> V2. Pure. Supports ONLY the one verified legacy shape. ----
const LEGACY_TOP = ['user', 'tasks', 'settings', 'reminderPrefs', 'history'];
const LEGACY_TASK = ['id', 'title', 'course', 'category', 'priority', 'deadline', 'progress'];
const LEGACY_SETTINGS = ['name', 'program', 'leadDays', 'sessionMinutes', 'weeklySummary'];
const LEGACY_USER = ['id', 'name', 'email', 'program'];
const DEFAULT_USER = { id: 'u1', name: 'Student', email: 'student@example.com' };

export function convertLegacyDb(legacy) {
  const errors = [], err = m => errors.push(m);
  if (!isObj(legacy)) return { ok: false, errors: ['database: not a recognised legacy mock database (expected an object).'] };
  for (const k of Object.keys(legacy)) if (!LEGACY_TOP.includes(k)) err(`database: unsupported field "${k}".`);
  if (!Array.isArray(legacy.tasks)) err('tasks: expected a list.');
  const report = { taskCount: 0, subjectCount: 0, idsReassigned: 0, uncategorizedTasks: 0, droppedFields: [], defaulted: [] };

  // user
  let user = { ...DEFAULT_USER };
  if (legacy.user === undefined) report.defaulted.push('user');
  else if (!isObj(legacy.user)) err('user: expected an object.');
  else {
    for (const k of Object.keys(legacy.user)) if (!LEGACY_USER.includes(k)) err(`user: unsupported field "${k}".`);
    for (const k of Object.keys(legacy.user)) if (typeof legacy.user[k] !== 'string') err(`user.${k}: expected text.`);
    if (Object.hasOwn(legacy.user, 'program')) report.droppedFields.push('user.program');
    user = { id: String(legacy.user.id ?? DEFAULT_USER.id), name: String(legacy.user.name ?? DEFAULT_USER.name), email: String(legacy.user.email ?? DEFAULT_USER.email) };
  }
  // settings (name -> full_name; program and weeklySummary have no home in V2)
  let settings = { full_name: '', leadDays: 2, sessionMinutes: 45 };
  if (legacy.settings === undefined) report.defaulted.push('settings');
  else if (!isObj(legacy.settings)) err('settings: expected an object.');
  else {
    const s = legacy.settings;
    for (const k of Object.keys(s)) if (!LEGACY_SETTINGS.includes(k)) err(`settings: unsupported field "${k}".`);
    if (s.name !== undefined) { if (typeof s.name !== 'string') err('settings.name: expected text.'); else if (s.name.trim().length > 80) err('settings.name: longer than 80 characters.'); else settings.full_name = s.name.trim() }
    if (s.leadDays !== undefined) { if (!LEAD_DAYS.includes(s.leadDays)) err('settings.leadDays: not an allowed value.'); else settings.leadDays = s.leadDays }
    if (s.sessionMinutes !== undefined) { if (!SESSION_MINUTES.includes(s.sessionMinutes)) err('settings.sessionMinutes: not an allowed value.'); else settings.sessionMinutes = s.sessionMinutes }
    if (Object.hasOwn(s, 'program')) { if (typeof s.program !== 'string') err('settings.program: expected text.'); report.droppedFields.push('settings.program') }
    if (Object.hasOwn(s, 'weeklySummary')) { if (typeof s.weeklySummary !== 'boolean') err('settings.weeklySummary: expected true/false.'); report.droppedFields.push('settings.weeklySummary') }
  }
  if (!settings.full_name) settings.full_name = user.name.trim().slice(0, 80) || 'Student';
  // reminder preferences
  const reminderPrefs = { ...REMINDER_DEFAULTS };
  if (legacy.reminderPrefs === undefined) report.defaulted.push('reminderPrefs');
  else if (!isObj(legacy.reminderPrefs)) err('reminderPrefs: expected an object.');
  else for (const [k, v] of Object.entries(legacy.reminderPrefs)) {
    if (!Object.hasOwn(REMINDER_DEFAULTS, k)) err(`reminderPrefs: unsupported field "${k}".`);
    else if (typeof v !== 'boolean') err(`reminderPrefs.${k}: expected true/false.`);
    else reminderPrefs[k] = v;
  }
  // history (static sample figures used only by mock mode)
  let history;
  if (legacy.history === undefined) { report.defaulted.push('history'); history = structuredClone(seed.history) }
  else { const hp = historyProblems(legacy.history, 'history'); hp.forEach(err); history = isObj(legacy.history) ? structuredClone(legacy.history) : undefined }

  // tasks and subjects
  const tasks = [], subjects = [], bySubject = new Map(), pending = [];
  if (Array.isArray(legacy.tasks)) legacy.tasks.forEach((t, i) => {
    const at = `tasks[${i}]`;
    if (!isObj(t)) return err(`${at}: expected an object.`);
    for (const k of Object.keys(t)) if (!LEGACY_TASK.includes(k)) err(`${at}: unsupported field "${k}".`);
    const out = { task_id: '', subject_id: '', title: '', deadline: '', importance: '', category: '', progress_pct: 0, status: '' };
    if (typeof t.title !== 'string') err(`${at}.title: expected text.`);
    else if (!t.title.trim()) err(`${at}.title: empty.`);
    else if (t.title.trim().length > 120) err(`${at}.title: longer than 120 characters.`);
    else out.title = t.title.trim();
    if (typeof t.category === 'string' && Object.hasOwn(CATEGORY_MAP, t.category)) out.category = CATEGORY_MAP[t.category]; else err(`${at}.category: not a recognised legacy value.`);
    if (typeof t.priority === 'string' && Object.hasOwn(PRIORITY_MAP, t.priority)) out.importance = PRIORITY_MAP[t.priority]; else err(`${at}.priority: not a recognised legacy value.`);
    if (isRealDate(t.deadline)) out.deadline = t.deadline; else err(`${at}.deadline: not a real YYYY-MM-DD date.`);
    if (isInt(t.progress) && t.progress >= 0 && t.progress <= 100) {
      out.progress_pct = t.progress; out.status = t.progress === 0 ? 'not_started' : t.progress === 100 ? 'completed' : 'in_progress';
    } else err(`${at}.progress: must be a whole number 0-100.`);
    let course = '';
    if (t.course !== undefined && t.course !== null) { if (typeof t.course !== 'string') err(`${at}.course: expected text.`); else course = collapse(t.course) }
    if (course.length > 100) err(`${at}.course: longer than 100 characters.`);
    if (!course) { course = UNCATEGORIZED; report.uncategorizedTasks++ }
    const key = normalizeName(course);
    if (!bySubject.has(key)) { const s = { subject_id: `sub_${subjects.length + 1}`, subject_name: course }; bySubject.set(key, s); subjects.push(s) }
    out.subject_id = bySubject.get(key).subject_id;
    pending.push({ out, id: t.id });
    tasks.push(out);
  });
  // ids: keep a legacy id when it is valid and not yet used, otherwise generate a new one that cannot collide
  const used = new Set();
  pending.forEach(({ out, id }) => { if (typeof id === 'string' && ID_RE.test(id) && !used.has(id)) { out.task_id = id; used.add(id) } });
  const taken = new Set([...used, ...pending.map(x => x.id).filter(x => typeof x === 'string')]); let n = 0;
  pending.forEach(({ out }) => { if (!out.task_id) { do n++; while (taken.has(`t_${n}`)); out.task_id = `t_${n}`; taken.add(out.task_id); report.idsReassigned++ } });

  if (errors.length) return { ok: false, errors };
  const db = { schema_version: 2, user, settings, reminderPrefs, subjects, tasks, history };
  if (tasks.length !== legacy.tasks.length) return { ok: false, errors: ['tasks: the converted count does not match the original.'] };
  const problems = validateV2Db(db);
  if (problems.length) return { ok: false, errors: problems };
  report.taskCount = tasks.length; report.subjectCount = subjects.length;
  return { ok: true, db, report };
}

// A fresh V2 demo database (the legacy demo data, converted). Always a new object.
export function seedV2() {
  const r = convertLegacyDb(seed);
  if (!r.ok) throw new Error('The built-in demo data failed validation.');
  return r.db;
}

// ---- Bootstrap: decide what to load, converting (with a verified backup first) when needed. ----
// `storage` is anything with getItem/setItem/removeItem (localStorage in the browser, a Map-backed fake in tests).
// Rules: the legacy key is NEVER written or deleted. An existing V2 key is never overwritten or deleted. The only
// keys removed are ones created during THIS call that failed verification.
const failure = (code, message, extra = {}) => ({ ok: false, code, message, ...extra });
const quietRemove = (storage, key) => { try { storage.removeItem(key) } catch { } };
const KEEP = 'Your original demo data was not changed.';

function writeV2(storage, db, extra) {
  const text = JSON.stringify(db);
  try {
    storage.setItem(KEYS.v2, text);
    if (storage.getItem(KEYS.v2) !== text) throw new Error('verify');
  } catch {
    quietRemove(storage, KEYS.v2); // the key did not exist before this call
    return failure('WRITE_FAILED', `The converted data could not be saved (browser storage may be full). ${KEEP}`, extra);
  }
  return { ok: true, db, ...extra };
}

export function bootstrapMockV2(storage, now = Date.now()) {
  let rawV2, rawLegacy;
  try { rawV2 = storage.getItem(KEYS.v2); rawLegacy = storage.getItem(KEYS.legacy) }
  catch { return failure('STORAGE_UNAVAILABLE', 'Browser storage is not available, so demo data cannot be loaded.') }

  if (rawV2 !== null) { // already activated: validate and use it. No writes of any kind.
    let db; try { db = JSON.parse(rawV2) } catch { db = undefined }
    return db !== undefined && validateV2Db(db).length === 0
      ? { ok: true, db, source: 'v2' }
      : failure('V2_INVALID', `The saved V2 demo data (${KEYS.v2}) is damaged. It was left untouched. ${KEEP}`);
  }
  if (rawLegacy === null) return writeV2(storage, seedV2(), { source: 'seed' }); // nothing to convert or back up

  // 1. verified backup of the raw legacy text, under a key that does not exist yet
  let backupKey = KEYS.backupPrefix + now;
  try {
    for (let i = 2; storage.getItem(backupKey) !== null; i++) backupKey = `${KEYS.backupPrefix}${now}_${i}`;
    storage.setItem(backupKey, rawLegacy);
    if (storage.getItem(backupKey) !== rawLegacy) throw new Error('verify');
  } catch {
    quietRemove(storage, backupKey);
    return failure('BACKUP_FAILED', `A backup could not be created, so nothing was converted. ${KEEP}`);
  }
  // 2. parse and convert in memory only
  let legacy; try { legacy = JSON.parse(rawLegacy) } catch { legacy = undefined }
  if (legacy === undefined) return failure('LEGACY_UNREADABLE', `The saved demo data could not be read. ${KEEP} A backup copy is stored under ${backupKey}.`, { backupKey });
  const result = convertLegacyDb(legacy);
  if (!result.ok) return failure('LEGACY_UNSUPPORTED', `The saved demo data is not in a supported format. ${KEEP} A backup copy is stored under ${backupKey}.`, { backupKey, errors: result.errors });
  // 3. write the validated V2 database once
  return writeV2(storage, result.db, { source: 'converted', backupKey, report: result.report });
}

// Recovery: start V2 from the built-in demo data. Refuses if a V2 key already exists. Never touches the legacy key.
export function startV2WithDemoData(storage) {
  try { if (storage.getItem(KEYS.v2) !== null) return failure('V2_EXISTS', 'V2 demo data already exists and was not replaced.') }
  catch { return failure('STORAGE_UNAVAILABLE', 'Browser storage is not available.') }
  return writeV2(storage, seedV2(), { source: 'seed' });
}

// ---- Mock V2 request engine: imitates the Phase 1 API (same paths, field names, status codes, error text). ----
// Used only by mock mode. Real mode talks to the real backend. Every handler validates BEFORE it changes anything,
// so a rejected request never leaves the database half-changed.
const publicSubtask = s => ({ subtask_id: s.subtask_id, title: s.title, estimated_minutes: s.estimated_minutes, status: s.status });
const publicTask = t => ({ task_id: t.task_id, subject_id: t.subject_id, title: t.title, deadline: t.deadline, importance: t.importance, category: t.category, progress_pct: t.progress_pct, status: t.status, subtasks: (Array.isArray(t.subtasks) ? t.subtasks : []).map(publicSubtask) });
const hasSubtasks = t => Array.isArray(t.subtasks) && t.subtasks.length > 0;
const publicSubject = s => ({ subject_id: s.subject_id, subject_name: s.subject_name });
const fail = errors => {
  if (Object.keys(errors).length) throw new MockHttpError(422, Object.entries(errors).map(([f, m]) => `${f}: ${m}`).join('; '), errors);
};
const readObj = body => { if (!isObj(body)) throw new MockHttpError(400, 'Request body must be a JSON object.'); return body };
const rule = {
  text: (max, allowEmpty = false) => v => {
    if (typeof v !== 'string') throw new Error('must be text.'); v = v.trim();
    if (!v && !allowEmpty) throw new Error('must not be empty.'); if (v.length > max) throw new Error(`must be ${max} characters or fewer.`); return v;
  },
  oneOf: allowed => v => { if (typeof v === 'boolean' || !allowed.includes(v)) throw new Error('must be one of: ' + allowed.join(', ') + '.'); return v },
  id: v => { if (typeof v !== 'string' || !ID_RE.test(v)) throw new Error('must be a valid id.'); return v },
  date: v => { if (!isRealDate(v)) throw new Error('must be a real date in YYYY-MM-DD format.'); return v },
  bool: v => { if (typeof v !== 'boolean') throw new Error('must be true or false.'); return v },
  progress: v => { if (!isInt(v) || v < 0 || v > 100) throw new Error('must be a whole number from 0 to 100.'); return v },
  hours: v => {
    if (typeof v === 'boolean') throw new Error('must be a number of hours.');
    if (typeof v === 'string') { if (!v.trim() || Number.isNaN(Number(v))) throw new Error('must be a number of hours.'); v = Number(v) }
    else if (typeof v !== 'number') throw new Error('must be a number of hours.');
    if (!(v >= 0.25 && v <= 8)) throw new Error('must be between 0.25 and 8 hours.'); return v;
  }
};
const SUBJECT_RULES = { subject_name: [rule.text(100), true] };
const TASK_RULES = { title: [rule.text(120), true], subject_id: [rule.id, true], category: [rule.oneOf(CATEGORIES), true], deadline: [rule.date, true], importance: [rule.oneOf(IMPORTANCE), true] };
const TASK_UPDATE_RULES = { ...TASK_RULES, progress_pct: [rule.progress, false] };
const CREATE_FORBIDDEN = { status: 'is set by the server: new tasks start as not_started.', progress_pct: 'is set by the server: new tasks start at 0.' };
const UPDATE_FORBIDDEN = { status: 'cannot be changed here. Use the start, complete or reopen actions.' };
const MINUTES_RULE = v => { if (typeof v !== 'number' || !Number.isSafeInteger(v) || v < 1) throw new Error(`must be a whole number of minutes, at least 1 (at most ${Number.MAX_SAFE_INTEGER}).`); return v };
const SUBTASK_RULES = { title: [rule.text(120), true], estimated_minutes: [MINUTES_RULE, false, 30] };
const SUBTASK_FORBIDDEN = { subtask_id: 'is set by the server.', status: 'is set by the server: new subtasks start as not_started.' };
const SETTINGS_RULES = { full_name: [rule.text(80), false], leadDays: [rule.oneOf(LEAD_DAYS), false], sessionMinutes: [rule.oneOf(SESSION_MINUTES), false] };
const REMINDER_RULES = Object.fromEntries(Object.keys(REMINDER_DEFAULTS).map(k => [k, [rule.bool, false]]));
const PLAN_RULES = { title: [rule.text(120), true], requirements: [rule.text(2000, true), false, ''], deadline: [rule.date, true], hoursPerDay: [rule.hours, false, 1], aiConsent: [rule.bool, false, false] };
const CHAT_RULES = { message: [rule.text(1000), true] };

function validateBody(body, rules, partial = false) {
  const clean = {}, errors = {};
  for (const [name, [check, required, fallback]] of Object.entries(rules)) {
    if (Object.hasOwn(body, name)) { try { clean[name] = check(body[name]) } catch (e) { errors[name] = e.message } }
    else if (!partial) { if (required) errors[name] = 'is required.'; else clean[name] = fallback }
  }
  if (partial && !Object.keys(clean).length && !Object.keys(errors).length) errors.body = 'send at least one of: ' + Object.keys(rules).join(', ') + '.';
  fail(errors); return clean;
}
const rejectFields = (body, forbidden) => fail(Object.fromEntries(Object.entries(forbidden).filter(([k]) => Object.hasOwn(body, k))));
const notFound = what => new MockHttpError(404, `${what} not found.`);
const dupName = () => new MockHttpError(422, 'subject_name: you already have a subject with that name.', { subject_name: 'you already have a subject with that name.' });
const mustOwnSubject = (db, id) => { if (!db.subjects.some(s => s.subject_id === id)) throw new MockHttpError(422, 'subject_id: must be one of your subjects.', { subject_id: 'must be one of your subjects.' }) };
const nameTaken = (db, name, exceptId) => db.subjects.some(s => s.subject_id !== exceptId && normalizeName(s.subject_name) === normalizeName(name));
// Validates a whole {subtasks:[...]} request BEFORE anything is saved; every problem is reported at once.
function validateSubtaskBatch(body) {
  const items = body.subtasks;
  if (!Array.isArray(items) || !items.length) fail({ subtasks: 'must be a non-empty list.' });
  if (items.length > MAX_SUBTASKS) fail({ subtasks: `at most ${MAX_SUBTASKS} subtasks can be added at once.` });
  const clean = [], errors = {};
  items.forEach((item, i) => {
    const at = `subtasks[${i}]`;
    if (!isObj(item)) { errors[at] = 'must be an object.'; return }
    for (const [k, m] of Object.entries(SUBTASK_FORBIDDEN)) if (Object.hasOwn(item, k)) errors[`${at}.${k}`] = m;
    const f = {};
    for (const [name, [check, required, fallback]] of Object.entries(SUBTASK_RULES)) {
      if (Object.hasOwn(item, name)) { try { f[name] = check(item[name]) } catch (e) { errors[`${at}.${name}`] = e.message } }
      else if (required) errors[`${at}.${name}`] = 'is required.'; else f[name] = fallback;
    }
    clean.push(f);
  });
  fail(errors); return clean;
}
// Parent progress/status from its subtasks (mirrors backend/store.py _recalculate_from_subtasks). No subtasks: untouched.
function recalcFromSubtasks(t) {
  if (!hasSubtasks(t)) return;
  const total = t.subtasks.length, done = t.subtasks.filter(s => s.status === 'completed').length, prev = t.status;
  t.progress_pct = percentDone(done, total);
  if (done === total) t.status = 'completed'; else if (prev === 'completed' || done > 0) t.status = 'in_progress';
}
const subtaskNotFound = () => new MockHttpError(404, 'Subtask not found.');
const findSubtask = (t, id) => { const s = ID_RE.test(id) && Array.isArray(t.subtasks) ? t.subtasks.find(x => x.subtask_id === id) : undefined; if (!s) throw subtaskNotFound(); return s };
function makeId(db, prefix, ctx) {
  const used = new Set([...db.subjects.map(s => s.subject_id), ...db.tasks.map(t => t.task_id), ...db.tasks.flatMap(t => (t.subtasks || []).map(s => s.subtask_id))]);
  for (let i = 0; i < 1000; i++) { const id = ctx.newId ? ctx.newId(prefix) : prefix + Math.random().toString(36).slice(2, 10); if (!used.has(id) && ID_RE.test(id)) return id }
  throw new Error('could not create a unique id');
}
const findTask = (db, id) => ID_RE.test(id) ? db.tasks.find(t => t.task_id === id) : undefined;
const findSubject = (db, id) => ID_RE.test(id) ? db.subjects.find(s => s.subject_id === id) : undefined;
const settingsView = db => ({ full_name: db.settings.full_name, leadDays: db.settings.leadDays, sessionMinutes: db.settings.sessionMinutes });
const topOpen = open => {
  const high = open.filter(t => t.importance === 'high').sort((a, b) => a.progress_pct - b.progress_pct || a.deadline.localeCompare(b.deadline))[0];
  return high || [...open].sort((a, b) => a.deadline.localeCompare(b.deadline))[0];
};
const MOCK_LABEL = { mock: true, aiGenerated: false, source: 'mock-client' };

export function mockV2Request(db, method, path, body, ctx = {}) {
  const today = ctx.todayIso || new Date().toISOString().slice(0, 10);
  const sm = path.match(/^\/tasks\/([^/]+)\/subtasks(?:\/([^/]+)(?:\/(complete|reopen))?)?$/);
  if (sm) {
    const [, taskId, subId, act] = sm;
    if (!subId && method === 'POST') {
      const items = validateSubtaskBatch(readObj(body)), t = findTask(db, taskId); if (!t) throw notFound('Task');
      const existing = Array.isArray(t.subtasks) ? t.subtasks : [];
      if (existing.length + items.length > MAX_SUBTASKS) { const msg = `a task can have at most ${MAX_SUBTASKS} subtasks (it already has ${existing.length}).`; throw new MockHttpError(422, `subtasks: ${msg}`, { subtasks: msg }) }
      t.subtasks = [...existing];
      for (const it of items) t.subtasks.push({ subtask_id: makeId(db, 'st_', ctx), title: it.title, estimated_minutes: it.estimated_minutes, status: 'not_started' });
      recalcFromSubtasks(t); return publicTask(t);
    }
    if (subId && method === 'POST' && act) {
      const t = findTask(db, taskId); if (!t) throw notFound('Task');
      const s = findSubtask(t, subId);
      if (act === 'complete') s.status = 'completed';
      else { if (s.status !== 'completed') throw new MockHttpError(409, 'Only a completed subtask can be reopened.'); s.status = 'not_started' }
      recalcFromSubtasks(t); return publicTask(t);
    }
    if (subId && !act && method === 'DELETE') {
      const t = findTask(db, taskId); if (!t) throw notFound('Task');
      const s = findSubtask(t, subId); t.subtasks.splice(t.subtasks.indexOf(s), 1);
      recalcFromSubtasks(t); return publicTask(t); // deleting the last one leaves progress/status as they were (manual rules again)
    }
    throw new MockHttpError(405, 'Method not allowed.');
  }
  const m = path.match(/^\/(subjects|tasks)(?:\/([^/]+?))?(?:\/(start|complete|reopen))?$/);
  if (m) {
    const [, resource, id, action] = m;
    if (resource === 'subjects' && !action) {
      if (!id && method === 'GET') return [...db.subjects].sort((a, b) => normalizeName(a.subject_name).localeCompare(normalizeName(b.subject_name)) || a.subject_id.localeCompare(b.subject_id)).map(publicSubject);
      if (!id && method === 'POST') {
        const f = validateBody(readObj(body), SUBJECT_RULES); if (nameTaken(db, f.subject_name)) throw dupName();
        const s = { subject_id: makeId(db, 'sub_', ctx), subject_name: f.subject_name }; db.subjects.push(s); return publicSubject(s);
      }
      if (id && method === 'PATCH') {
        const f = validateBody(readObj(body), SUBJECT_RULES, true), s = findSubject(db, id); if (!s) throw notFound('Subject');
        if (nameTaken(db, f.subject_name, id)) throw dupName(); s.subject_name = f.subject_name; return publicSubject(s);
      }
      if (id && method === 'DELETE') {
        const s = findSubject(db, id); if (!s) throw notFound('Subject');
        if (db.tasks.some(t => t.subject_id === id)) { const msg = 'This subject still has tasks. Reassign or delete those tasks before deleting the subject.'; throw new MockHttpError(409, msg, { subject_id: msg }) }
        db.subjects.splice(db.subjects.indexOf(s), 1); return null;
      }
    }
    if (resource === 'tasks') {
      if (!id && !action && method === 'GET') return db.tasks.map(publicTask);
      if (!id && !action && method === 'POST') {
        const b = readObj(body); rejectFields(b, CREATE_FORBIDDEN); const f = validateBody(b, TASK_RULES); mustOwnSubject(db, f.subject_id);
        const t = { task_id: makeId(db, 't_', ctx), subject_id: f.subject_id, title: f.title, deadline: f.deadline, importance: f.importance, category: f.category, progress_pct: 0, status: 'not_started' };
        db.tasks.push(t); return publicTask(t);
      }
      if (id && !action && method === 'PATCH') {
        const b = readObj(body); rejectFields(b, UPDATE_FORBIDDEN); const f = validateBody(b, TASK_UPDATE_RULES, true), t = findTask(db, id); if (!t) throw notFound('Task');
        if (Object.hasOwn(f, 'subject_id')) mustOwnSubject(db, f.subject_id);
        if (Object.hasOwn(f, 'progress_pct') && hasSubtasks(t)) { const msg = 'is calculated from the subtasks of this task and cannot be set directly.'; throw new MockHttpError(422, `progress_pct: ${msg}`, { progress_pct: msg }) }
        if (Object.hasOwn(f, 'progress_pct') && t.status === 'completed' && f.progress_pct < 100) {
          const msg = 'a completed task stays at 100%. Reopen the task before lowering its progress.'; throw new MockHttpError(422, `progress_pct: ${msg}`, { progress_pct: msg });
        }
        Object.assign(t, f); return publicTask(t);
      }
      if (id && !action && method === 'DELETE') { const t = findTask(db, id); if (!t) throw notFound('Task'); db.tasks.splice(db.tasks.indexOf(t), 1); return null }
      if (id && action && method === 'POST') {
        const t = findTask(db, id); if (!t) throw notFound('Task');
        if (action !== 'start' && hasSubtasks(t)) throw new MockHttpError(409, 'This task has subtasks. Complete or reopen its subtasks instead.');
        if (action === 'start') {
          if (t.status === 'completed') throw new MockHttpError(409, 'This task is completed. Use reopen to work on it again.');
          if (t.status === 'not_started') t.status = 'in_progress';
        } else if (action === 'complete') { if (t.status !== 'completed') { t.status = 'completed'; t.progress_pct = 100 } }
        else { if (t.status !== 'completed') throw new MockHttpError(409, 'Only a completed task can be reopened.'); t.status = 'in_progress' } // progress unchanged
        return publicTask(t);
      }
    }
    throw new MockHttpError(405, 'Method not allowed.');
  }
  switch (method + ' ' + path) {
    case 'GET /settings': return settingsView(db);
    case 'PUT /settings': Object.assign(db.settings, validateBody(readObj(body), SETTINGS_RULES, true)); return settingsView(db);
    case 'GET /reminders/preferences': return { ...db.reminderPrefs };
    case 'PUT /reminders/preferences': Object.assign(db.reminderPrefs, validateBody(readObj(body), REMINDER_RULES, true)); return { ...db.reminderPrefs };
    case 'GET /progress': {
      const h = db.history, open = db.tasks.filter(t => t.status !== 'completed');
      return { completionRate: h.completionRate, onTimeRate: h.onTimeRate, completed: h.completed + db.tasks.length - open.length, overdue: open.filter(t => t.deadline < today).length, weeklyChange: h.weeklyChange, weeklyProductivity: [...h.weeklyProductivity], weeklyCompletion: [...h.weeklyCompletion], insight: h.insight, insightSource: 'mock-sample' };
    }
    case 'POST /ai/plan': {
      const f = validateBody(readObj(body), PLAN_RULES), steps = ['Define scope and outline', 'Gather and review sources', 'Draft main sections', 'Revise and add citations', 'Final proofread and submit'];
      const span = Math.max(dayNumber(f.deadline) - dayNumber(today), 1), minutes = Math.round(f.hoursPerDay * 30);
      // Same consent contract as the backend: only a real true counts. The browser demo never calls any AI, so it always answers with the template.
      const notice = 'Browser demo plan: a fixed five-step template. No AI model was used.' + (f.aiConsent === true ? '' : ' AI suggestions were not used because the consent box was not ticked.');
      return { ...MOCK_LABEL, notice, subtasks: steps.map((title, i) => ({ title, dueDate: addDaysIso(today, Math.round(span * (i + 1) / steps.length)), minutes })) };
    }
    case 'POST /ai/chat': {
      const q = validateBody(readObj(body), CHAT_RULES).message.toLowerCase(), open = db.tasks.filter(t => t.status !== 'completed'); let reply;
      if (/first|priorit|start/.test(q)) { const t = topOpen(open); reply = t ? `Based on your recorded tasks, start with "${t.title}" (${t.progress_pct}% done, ${dueWords(dayNumber(t.deadline) - dayNumber(today))}). Try a 25-minute session.` : 'You have no open tasks.' }
      else if (/due|deadline|soon/.test(q)) reply = open.length ? 'Upcoming: ' + [...open].sort((a, b) => a.deadline.localeCompare(b.deadline)).slice(0, 3).map(t => `${t.title} (${shortDate(t.deadline)})`).join('; ') + '.' : 'Nothing is due.';
      else reply = 'I can help with prioritizing tasks and deadlines. Try asking "What should I work on first?"';
      return { ...MOCK_LABEL, notice: 'Browser demo reply based on keywords and your recorded tasks. No AI model was used.', reply };
    }
    case 'POST /auth/login': { const b = readObj(body); if (!b.email || String(b.password || '').length < 6) throw new MockHttpError(401, 'Invalid email or password (demo: 6+ characters).'); return { token: 'mock-token', user: { ...db.user, email: String(b.email) } } }
    case 'POST /auth/register': {
      const b = readObj(body); if (String(b.password || '').length < 6) throw new MockHttpError(422, 'Password must be at least 6 characters.');
      const name = String(b.name ?? '').trim().slice(0, 80) || 'Student'; db.user = { ...db.user, name, email: String(b.email ?? '') }; db.settings.full_name = name;
      return { token: 'mock-token', user: { ...db.user } };
    }
  }
  throw new MockHttpError(404, `Not found: ${method} ${path}`);
}
