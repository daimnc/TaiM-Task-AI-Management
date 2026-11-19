// ALL data access goes through `api`. UI never calls fetch or touches mock data directly.
import { CONFIG } from '../config.js';
import { seed, KEYS, bootstrapMockV2, mockV2Request, mockInsights, MockHttpError } from './mockData.js';
import { iso, addDays, daysUntil, dueText, fmtDate, topPick, sortByDue, today } from '../ui.js';
export class ApiError extends Error { constructor(m, status) { super(m); this.status = status } }
// ---- Firebase (real mode only; never loaded when USE_MOCK is true) ----
let fbLoad = null, fbUser = null, readyP = null; const subs = new Set();
const loadFirebase = () => fbLoad ||= import('./firebaseAuth.js').catch(e => { fbLoad = null; console.error(e); throw new ApiError('Could not load Firebase. Check your internet connection and the config in js/firebase.js.') });
const startAuth = () => readyP ||= CONFIG.USE_MOCK ? Promise.resolve() : loadFirebase().then(m => new Promise(res => m.onChange(u => { fbUser = u; if (!u) try { localStorage.removeItem(CONFIG.USER_KEY) } catch { } res(); subs.forEach(f => f(u)) }, () => res()))).catch(() => { });
const signedIn = r => { fbUser = r.raw; return { token: r.token, user: r.user } };
const saved = () => { try { return JSON.parse(localStorage.getItem(CONFIG.USER_KEY)) } catch { return null } };
// Single place that drops the in-memory Firebase user together with the stored profile, so they can never disagree.
const wipe = () => { fbUser = null; localStorage.removeItem(CONFIG.TOKEN_KEY); localStorage.removeItem(CONFIG.USER_KEY) };
// Real mode only: always drops the in-memory Firebase user, even if localStorage is unavailable and removeItem throws.
const wipeReal = () => { fbUser = null; try { wipe() } catch { } };
export const auth = {
  // Mock: stored token. Real: `token` is only a non-secret "signed in" marker for the router; the real ID token comes from getToken().
  get token() { if (!CONFIG.USE_MOCK) return fbUser ? 'firebase-session' : null; try { return localStorage.getItem(CONFIG.TOKEN_KEY) } catch { return null } },
  get user() {
    if (CONFIG.USE_MOCK) return saved(); if (!fbUser) return null;
    const d = { id: fbUser.uid, name: fbUser.displayName || (fbUser.email || '').split('@')[0] || 'Student', email: fbUser.email || '', program: '' }, s = saved(); return s && s.id === d.id ? { ...d, ...s } : d
  },
  set(token, user) { if (CONFIG.USE_MOCK) localStorage.setItem(CONFIG.TOKEN_KEY, token); localStorage.setItem(CONFIG.USER_KEY, JSON.stringify(user)) },
  // Also ends the Firebase session in real mode (fire-and-forget) so memory and Firebase stay in sync.
  clear() {
    if (CONFIG.USE_MOCK) { wipe(); return }
    wipeReal(); // memory is cleaned first and unconditionally, so a failing step below can never leave a stale fbUser
    if (fbLoad) fbLoad.then(m => m.logout()).catch(() => { fbUser = null })
  },
  // Resolves once Firebase has restored (or failed to restore) the session. Immediate in mock mode.
  ready: () => startAuth(),
  onChange: f => { subs.add(f); return () => subs.delete(f) },
  async getToken() { if (CONFIG.USE_MOCK) return this.token; return (await loadFirebase()).getIdToken() },
  async signOut() {
    if (CONFIG.USE_MOCK) { auth.clear(); return }
    // finally: even if Firebase's signOut fails, this tab must not keep believing the user is signed in.
    try { await (await loadFirebase()).logout() } finally { wipeReal() }
  }
};

async function real(method, path, body) {
  const tok = await auth.getToken();
  const r = await fetch(CONFIG.API_BASE + path, { method, headers: { 'Content-Type': 'application/json', ...(tok ? { Authorization: 'Bearer ' + tok } : {}) }, body: body ? JSON.stringify(body) : undefined });
  if (!r.ok) { throw new ApiError((await r.json().catch(() => ({}))).detail || r.statusText, r.status) }
  return r.status === 204 ? null : r.json();
}

// ---- Mock backend (in-memory + localStorage). Remove once the Python API exists. ----
const KEY = 'taim_mock_db'; let db;
const getDb = () => { if (!db) { try { db = JSON.parse(localStorage.getItem(KEY)) } catch { } db ||= structuredClone(seed) } return db };
const save = () => { try { localStorage.setItem(KEY, JSON.stringify(db)) } catch { } };
async function mock(method, path, body) {
  await new Promise(r => setTimeout(r, 250)); const d = getDb();
  const m = path.match(/^\/tasks(?:\/(\w+))?$/);
  if (m) {
    const id = m[1];
    if (method === 'GET') return d.tasks;
    if (method === 'POST') { const t = { ...body, id: 't' + Date.now() + Math.random().toString(36).slice(2, 5) }; d.tasks.push(t); save(); return t }
    const i = d.tasks.findIndex(t => t.id === id); if (i < 0) throw new ApiError('Task not found', 404);
    if (method === 'PATCH') { d.tasks[i] = { ...d.tasks[i], ...body }; save(); return d.tasks[i] }
    if (method === 'DELETE') { d.tasks.splice(i, 1); save(); return null }
  }
  switch (method + ' ' + path) {
    case 'POST /auth/login': if (!body.email || (body.password || '').length < 6) throw new ApiError('Invalid email or password (demo: 6+ characters).', 401); return { token: 'mock-token', user: { ...d.user, email: body.email } };
    case 'POST /auth/register': if ((body.password || '').length < 6) throw new ApiError('Password must be at least 6 characters.', 422); d.user = { ...d.user, name: body.name, email: body.email, program: body.program || '' }; d.settings = { ...d.settings, name: body.name, program: body.program || '' }; save(); return { token: 'mock-token', user: d.user };
    case 'GET /settings': return d.settings;
    case 'PUT /settings': d.settings = { ...d.settings, ...body }; save(); return d.settings;
    case 'GET /reminders/preferences': return d.reminderPrefs;
    case 'PUT /reminders/preferences': d.reminderPrefs = { ...d.reminderPrefs, ...body }; save(); return d.reminderPrefs;
    case 'GET /progress': { const h = d.history, act = d.tasks.filter(t => t.progress < 100); return { completionRate: h.completionRate, onTimeRate: h.onTimeRate, completed: h.completed + d.tasks.length - act.length, overdue: act.filter(t => daysUntil(t.deadline) < 0).length, weeklyChange: h.weeklyChange, weeklyProductivity: h.weeklyProductivity, weeklyCompletion: h.weeklyCompletion, insight: h.insight } }
    case 'POST /ai/plan': {
      const steps = ['Define scope and outline', 'Gather and review sources', 'Draft main sections', 'Revise and add citations', 'Final proofread and submit'], n = steps.length, span = Math.max(daysUntil(body.deadline), 1), mins = Math.round((+body.hoursPerDay || 1) * 30);
      return { mock: true, subtasks: steps.map((title, i) => ({ title, dueDate: iso(addDays(Math.round(span * (i + 1) / n))), minutes: mins })) }
    }
    case 'POST /ai/insights': return mockInsights();
    case 'POST /ai/chat': {
      const q = (body.message || '').toLowerCase(); let reply; const open = d.tasks.filter(t => t.progress < 100);
      if (/first|priorit|start/.test(q)) { const t = topPick(d.tasks); reply = t ? `Based on your recorded tasks, start with "${t.title}" (${t.progress}% done, ${dueText(t.deadline).toLowerCase()}). Try a 25-minute session.` : 'You have no open tasks.' }
      else if (/due|deadline|soon/.test(q)) reply = open.length ? 'Upcoming: ' + sortByDue(open).slice(0, 3).map(t => `${t.title} (${fmtDate(t.deadline)})`).join('; ') + '.' : 'Nothing is due.';
      else reply = 'I can help with prioritizing tasks and deadlines. Try asking "What should I work on first?"';
      return { mock: true, reply }
    }
  }
  throw new ApiError('Not found: ' + method + ' ' + path, 404);
}
// ---- Mock database v2 (Phase 3). DORMANT: keep MOCK_V2 = false until every page uses the v2 data shapes (Batch 3.2). ----
// While false, mockV2 is never called, so no taim_mock_db_v2 or backup key is ever created and the legacy mock above is used.
// When true (mock mode only), the first request loads/converts the data via bootstrapMockV2 (see mockData.js).
const MOCK_V2 = false; let v2db = null;

async function mockV2(method, path, body) {
  await new Promise(r => setTimeout(r, 250));

  if (!v2db) {
    const r = bootstrapMockV2(localStorage);
    if (!r.ok) throw new ApiError(r.message, 500);
    v2db = r.db;
  }

  try {
    if (method === 'GET') {
      return mockV2Request(v2db, method, path, body, {
        todayIso: iso(today())
      });
    }

    // Apply mutations to a copy first.
    const nextDb = JSON.parse(JSON.stringify(v2db));

    const out = mockV2Request(nextDb, method, path, body, {
      todayIso: iso(today())
    });

    // Save successfully before accepting the new in-memory state.
    localStorage.setItem(KEYS.v2, JSON.stringify(nextDb));
    v2db = nextDb;

    return out;
  } catch (e) {
    throw e instanceof MockHttpError
      ? new ApiError(e.message, e.status)
      : e;
  }
}
const req = (m, p, b) => (CONFIG.USE_MOCK ? (MOCK_V2 ? mockV2 : mock) : real)(m, p, b);
export const api = {
  login: b => CONFIG.USE_MOCK ? req('POST', '/auth/login', b) : loadFirebase().then(m => m.login(b.email, b.password)).then(signedIn),
  register: b => CONFIG.USE_MOCK ? req('POST', '/auth/register', b) : loadFirebase().then(m => m.register(b)).then(signedIn),
  googleLogin: () => CONFIG.USE_MOCK ? Promise.reject(new ApiError('Google sign-in requires Firebase (USE_MOCK=false).')) : loadFirebase().then(m => m.google()).then(signedIn),
  getTasks: () => req('GET', '/tasks'), createTask: b => req('POST', '/tasks', b), updateTask: (id, b) => req('PATCH', '/tasks/' + id, b), deleteTask: id => req('DELETE', '/tasks/' + id),
  getProgress: () => req('GET', '/progress'),
  getSettings: () => req('GET', '/settings'), saveSettings: b => req('PUT', '/settings', b),
  getReminderPrefs: () => req('GET', '/reminders/preferences'), saveReminderPrefs: b => req('PUT', '/reminders/preferences', b),
  planTask: b => req('POST', '/ai/plan', b), askAssistant: b => req('POST', '/ai/chat', b),
  getInsights: b => req('POST', '/ai/insights', b), // Phase 4.2: body is {aiConsent: true|false}; answers rule-based text unless consent was given and AI is available
  // Phase 1 API (subjects, task actions). With the legacy mock they answer 404.
  getSubjects: () => req('GET', '/subjects'), createSubject: b => req('POST', '/subjects', b),
  renameSubject: (id, b) => req('PATCH', '/subjects/' + encodeURIComponent(id), b), deleteSubject: id => req('DELETE', '/subjects/' + encodeURIComponent(id)),
  startTask: id => req('POST', '/tasks/' + encodeURIComponent(id) + '/start'), completeTask: id => req('POST', '/tasks/' + encodeURIComponent(id) + '/complete'), reopenTask: id => req('POST', '/tasks/' + encodeURIComponent(id) + '/reopen'),
  // Subtasks (Stage B). Every call answers with the updated PARENT task. With the legacy mock they answer 404.
  addSubtasks: (id, b) => req('POST', '/tasks/' + encodeURIComponent(id) + '/subtasks', b),
  completeSubtask: (id, sid) => req('POST', '/tasks/' + encodeURIComponent(id) + '/subtasks/' + encodeURIComponent(sid) + '/complete'),
  reopenSubtask: (id, sid) => req('POST', '/tasks/' + encodeURIComponent(id) + '/subtasks/' + encodeURIComponent(sid) + '/reopen'),
  deleteSubtask: (id, sid) => req('DELETE', '/tasks/' + encodeURIComponent(id) + '/subtasks/' + encodeURIComponent(sid))
};