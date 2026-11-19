// Phase 4.2: runs the REAL Progress page code against a tiny hand-made fake DOM (no browser, no jsdom, no network).
//   node --test frontend/tests/insights.page.test.mjs
import test from 'node:test';
import assert from 'node:assert/strict';
import { api } from '../js/api/client.js';
import page from '../js/pages/progress.js';
import { mockInsights } from '../js/api/mockData.js';

const PROGRESS = { completionRate: 50, onTimeRate: 75, completed: 3, overdue: 1, weeklyChange: 0, weeklyProductivity: [0, 0, 0, 0, 0, 0, 0],
  weeklyCompletion: [0, 1, 1, 1], insight: 'Summary text.', insightSource: 'rule-based' };
const tick = () => new Promise(r => setTimeout(r, 0));
const XSS = '<img src=x onerror=alert(1)>';

function setup({ progress = PROGRESS } = {}) {
  const reg = {};
  const fresh = () => ({ innerHTML: '', textContent: '', className: '', checked: false, inert: false, onclick: null,
    classList: { add() {}, remove() {} } });
  const el = {
    _h: '', get innerHTML() { return this._h },
    set innerHTML(v) { this._h = v; if (String(v).includes('id="ins"')) for (const id of ['ins', 'ins-out', 'ins-consent', 'ins-pill', 'ins-gen']) reg['#' + id] = fresh() },
    querySelector: sel => reg[sel] ?? null,
  };
  const calls = [];
  api.getProgress = async () => progress;
  const respond = { next: async () => ({ ...mockInsights(), mock: false, aiGenerated: false, source: 'rule-based' }) };
  api.getInsights = async b => { calls.push(b); return respond.next(b) };
  page.render(el);
  return { el, reg, calls, respond };
}

test('the page keeps its original content and adds the AI card with the box unticked', async () => {
  const { el, reg } = setup(); await tick();
  for (const w of ['Weekly Completion Trend', 'Productivity Insight', 'AI Insights', 'Generate insights']) assert.ok(el.innerHTML.includes(w), w);
  assert.equal(reg['#ins-consent'].checked, false);
  assert.equal(typeof reg['#ins-gen'].onclick, 'function');
});

test('unticked: request carries aiConsent:false and the result is shown as rule-based', async () => {
  const { reg, calls } = setup(); await tick();
  reg['#ins-gen'].onclick(); await tick();
  assert.deepEqual(calls, [{ aiConsent: false }]);
  assert.match(reg['#ins-pill'].textContent, /RULE-BASED/);
  assert.match(reg['#ins-out'].innerHTML, /Calculated facts/); assert.doesNotMatch(reg['#ins-out'].innerHTML, /AI interpretation/);
  assert.equal(reg['#ins-out'].className, 'ins-result');
});

test('ticked: request carries aiConsent:true, an AI result is labelled, and the box is cleared afterwards', async () => {
  const { reg, calls, respond } = setup(); await tick();
  respond.next = async () => ({ ...mockInsights(), mock: false, aiGenerated: true, source: 'gemini', notice: 'AI-generated interpretation by Google Gemini.' });
  reg['#ins-consent'].checked = true;
  reg['#ins-gen'].onclick(); await tick();
  assert.deepEqual(calls, [{ aiConsent: true }]);
  assert.equal(reg['#ins-consent'].checked, false);
  assert.match(reg['#ins-pill'].textContent, /AI-GENERATED · GOOGLE GEMINI/); assert.match(reg['#ins-out'].innerHTML, /AI interpretation/);
  reg['#ins-gen'].onclick(); await tick();                       // second request needs its own tick
  assert.deepEqual(calls[1], { aiConsent: false });
});

test('while a request is pending a second click sends nothing, and the card is locked then released', async () => {
  const { reg, calls, respond } = setup(); await tick();
  let release; respond.next = () => new Promise(r => { release = () => r({ ...mockInsights(), mock: false, aiGenerated: false, source: 'rule-based' }) });
  reg['#ins-gen'].onclick(); await tick();
  assert.equal(reg['#ins-out'].textContent, 'Generating insights…'); assert.equal(reg['#ins'].inert, true);
  reg['#ins-gen'].onclick(); reg['#ins-gen'].onclick(); await tick();
  assert.equal(calls.length, 1);
  release(); await tick();
  assert.equal(reg['#ins'].inert, false); assert.equal(calls.length, 1);
  reg['#ins-gen'].onclick(); await tick(); assert.equal(calls.length, 2);
});

test('errors: the server message is shown as plain text, the box is cleared and the button works again', async () => {
  const { reg, calls, respond } = setup(); await tick();
  respond.next = async () => { throw new Error(`Server says ${XSS}`) };
  reg['#ins-consent'].checked = true; reg['#ins-gen'].onclick(); await tick();
  assert.equal(reg['#ins-out'].className, 'state err'); assert.equal(reg['#ins-out'].textContent, `Server says ${XSS}`); // textContent, so it is not parsed as HTML
  assert.equal(reg['#ins-out'].innerHTML, ''); assert.equal(reg['#ins-consent'].checked, false);
  assert.match(reg['#ins-pill'].textContent, /NOT GENERATED/); assert.equal(reg['#ins'].inert, false);
  respond.next = async () => { throw {} };
  reg['#ins-gen'].onclick(); await tick();
  assert.equal(reg['#ins-out'].textContent, 'Insights could not be generated.'); assert.equal(calls.length, 2);
});

test('a malformed response is an error, never half-drawn', async () => {
  const { reg, respond } = setup(); await tick();
  for (const bad of [null, {}, { summary: 'x' }, { ...mockInsights(), facts: null }]) {
    respond.next = async () => bad;
    reg['#ins-out'].innerHTML = ''; reg['#ins-gen'].onclick(); await tick();
    assert.equal(reg['#ins-out'].className, 'state err'); assert.match(reg['#ins-out'].textContent, /unexpected answer/); assert.equal(reg['#ins-out'].innerHTML, '');
  }
});

test('hostile text in a response is escaped on the page', async () => {
  const { reg, respond } = setup(); await tick();
  respond.next = async () => { const r = mockInsights(); r.summary = XSS; r.insights[0].text = XSS; r.notice = XSS; r.facts.workload.subjects[0].name = XSS; return { ...r, mock: false, source: 'rule-based' } };
  reg['#ins-gen'].onclick(); await tick();
  assert.doesNotMatch(reg['#ins-out'].innerHTML, /<img/); assert.ok(reg['#ins-out'].innerHTML.includes('&lt;img src=x onerror=alert(1)&gt;'));
});

test('the existing progress card still escapes its own text', async () => {
  const { el } = setup({ progress: { ...PROGRESS, insight: XSS } }); await tick();
  assert.doesNotMatch(el.innerHTML, /<img/); assert.ok(el.innerHTML.includes('&lt;img'));
});
