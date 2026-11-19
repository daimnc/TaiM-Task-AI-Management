// Phase 4.2 tests: AI Insights card. Run from the project root:  node --test frontend/tests/insights.test.mjs
// Pure helpers, the mock API contract, and static wiring checks of the page (browser behaviour is on the manual checklist).
// Nothing here calls the network, Firebase or any AI provider.
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { seedV2, mockV2Request, mockInsights, MockHttpError } from '../js/api/mockData.js';
import { insightSource, validInsights, factSections, factsHtml, insightsHtml, areaLabel, INSIGHT_AREAS } from '../js/insights.js';

const src = f => readFileSync(new URL('../' + f, import.meta.url), 'utf8');
const rejects = (fn, status, re) => assert.throws(fn, e => e instanceof MockHttpError && e.status === status && (!re || re.test(e.message)));
const call = (m, p, b) => mockV2Request(seedV2(), m, p, b, { todayIso: '2026-11-16' });
const clone = o => JSON.parse(JSON.stringify(o));
const ai = (source = 'groq') => ({ ...mockInsights(), mock: false, aiGenerated: true, source, notice: 'AI-generated interpretation.' });
const rule = () => ({ ...mockInsights(), mock: false, aiGenerated: false, source: 'rule-based', notice: '' });
const XSS = '<img src=x onerror=alert(1)>"\'&';

// ---------- what produced the answer ----------
test('source: AI is claimed only for a real response with aiGenerated:true and a known provider', () => {
  assert.equal(insightSource(ai('groq')).kind, 'groq');
  assert.equal(insightSource(ai('gemini')).kind, 'gemini');
  assert.match(insightSource(ai('groq')).pill, /AI-GENERATED · GROQ/);
  assert.match(insightSource(ai('gemini')).pill, /GOOGLE GEMINI/);
  assert.equal(insightSource(ai('ai')).kind, 'ai');
  for (const bad of [{ ...ai(), aiGenerated: 'true' }, { ...ai(), aiGenerated: 1 }, { ...ai('openai') }, { ...ai(), source: undefined }, { ...ai(), aiGenerated: false }, null, undefined, {}, 'x']) {
    assert.equal(insightSource(bad).kind, 'rule', JSON.stringify(bad));
    assert.match(insightSource(bad).pill, /NO AI MODEL USED/);
  }
});

test('source: the browser demo is always a demo, even if it says aiGenerated', () => {
  assert.equal(insightSource(mockInsights()).kind, 'demo');
  assert.equal(insightSource({ ...ai('groq'), mock: true }).kind, 'demo');
  assert.match(insightSource(mockInsights()).heading, /Not calculated from your tasks and not AI-generated/);
});

// ---------- shape check ----------
test('validInsights accepts the real shape and rejects anything incomplete', () => {
  assert.equal(validInsights(mockInsights()), true);
  assert.equal(validInsights(rule()), true);
  const without = k => { const r = clone(mockInsights()); delete r[k]; return r };
  for (const k of ['summary', 'insights', 'suggestions', 'facts']) assert.equal(validInsights(without(k)), false, k);
  for (const bad of [null, undefined, [], 'x', 5, { ...mockInsights(), summary: 5 }, { ...mockInsights(), insights: [{ text: 5 }] },
    { ...mockInsights(), insights: [null] }, { ...mockInsights(), suggestions: ['a'] }, { ...mockInsights(), facts: { completion: {} } },
    { ...mockInsights(), limitations: 'x' }, { ...mockInsights(), limitations: [1] }]) assert.equal(validInsights(bad), false);
  assert.equal(validInsights({ ...mockInsights(), limitations: undefined }), true);
});

// ---------- rendering ----------
test('render: AI and rule-based results are clearly different', () => {
  const a = insightsHtml(ai('groq')), r = insightsHtml(rule()), d = insightsHtml(mockInsights());
  assert.match(a, /AI-GENERATED · GROQ/); assert.match(a, /<h4>AI interpretation<\/h4>/); assert.match(a, /ins-block ai/);
  assert.doesNotMatch(r, /AI interpretation/); assert.match(r, /RULE-BASED · NO AI MODEL USED/); assert.match(r, /Not AI-generated/); assert.match(r, /ins-block plain/);
  assert.doesNotMatch(r, /AI-GENERATED/);
  assert.match(d, /DEMO SAMPLE/); assert.doesNotMatch(d, /AI-GENERATED|AI interpretation/);
});

test('render: calculated facts are a separate block, labelled as not made by AI, and every area and suggestion is shown', () => {
  const html = insightsHtml(ai('gemini')), i = html.indexOf('ins-block ai'), f = html.indexOf('facts-block');
  assert.ok(i > 0 && f > i, 'interpretation first, facts after');
  assert.match(html, /Calculated facts <small class="tag">worked out by TAiM, not by AI<\/small>/);
  for (const label of Object.values(INSIGHT_AREAS)) assert.ok(html.includes(label), label);
  assert.match(html, /<h4>Suggestions<\/h4>/); assert.match(html, /Good to know/); assert.match(html, /not the time you actually spent studying/);
  assert.match(html, /not a diagnosis or judgment/);
  assert.equal(areaLabel('bogus'), ''); assert.equal(areaLabel('__proto__'), ''); assert.equal(areaLabel(undefined), '');
});

test('render: every piece of text is escaped (summary, insights, suggestions, notice, limits, subject names, tags)', () => {
  const r = ai('groq');
  r.summary = XSS; r.notice = XSS; r.insights = [{ area: 'completion', text: XSS }, { area: XSS, text: XSS }];
  r.suggestions = [{ text: XSS, area: XSS }]; r.limitations = [XSS]; r.facts.workload.subjects[0].name = XSS;
  r.source = 'groq';
  const html = insightsHtml(r);
  assert.doesNotMatch(html, /<img/i); assert.doesNotMatch(html, /onerror=alert\(1\)>/);
  assert.ok(html.includes('&lt;img src=x onerror=alert(1)&gt;&quot;&#39;&amp;'));
  assert.doesNotMatch(factsHtml(r.facts), /<img/i);
  // an attacker-chosen source or area can never become a class or a tag
  const odd = { ...ai('groq'), source: '"><script>x</script>' };
  assert.doesNotMatch(insightsHtml(odd), /<script>/);
});

test('render: AI claims never appear without a real AI source, even if the server text says "AI"', () => {
  const r = { ...rule(), notice: 'AI was not used because the consent box was not ticked. Rule-based insights are shown instead.' };
  const html = insightsHtml(r);
  assert.doesNotMatch(html, /AI-GENERATED|AI interpretation/);
  assert.match(html, /AI was not used/);
});

// ---------- facts ----------
test('facts: sections, rows and the "not enough data" state', () => {
  const sections = factSections(mockInsights().facts);
  assert.deepEqual(sections.map(s => s.title), ['Completion', 'Deadlines', 'Workload by subject', 'Patterns']);
  const flat = Object.fromEntries(sections.flatMap(s => s.rows));
  assert.equal(flat['Overdue'], '1'); assert.equal(flat['Completed'], '6 (60%)'); assert.equal(flat['Change from last week'], '-50%');
  assert.equal(flat['Heavy stretch'], 'No'); assert.equal(flat['Not enough data yet'], '3 of 5 completed tasks needed');
  assert.match(flat['Programming'], /2 open \(50%\) · 1 overdue · 1 high importance/);
});

test('facts: full patterns, heavy stretch, change unknown, other subjects, missing deadlines', () => {
  const f = clone(mockInsights().facts);
  Object.assign(f.patterns, { enoughForPatterns: true, onTimeRate: 80, lateSharePct: 20, lastMinuteSharePct: 40, medianDaysBeforeDeadline: 2, weekdayPattern: { weekday: 0, count: 4, sharePct: 50 } });
  Object.assign(f.deadlines, { heavy: true, heavyReason: 'overdue_plus_soon', noValidDeadline: 2 });
  Object.assign(f.completion, { weeklyChangeKnown: false, openSubtasksTotal: 4, openSubtasksDone: 1 });
  f.workload.otherSubjects = { count: 3, openTasks: 5 }; f.workload.unestimatedTasksTotal = 2; f.workload.subjects[0].remainingMinutes = 90;
  const flat = Object.fromEntries(factSections(f).flatMap(s => s.rows));
  assert.equal(flat['Marked complete on or before the deadline'], '80%'); assert.equal(flat['Most common weekday for marking complete'], 'Monday (50%)');
  assert.match(flat['Heavy stretch'], /^Yes .*plus 1 overdue/); assert.equal(flat['Missing or unreadable deadline'], '2');
  assert.match(flat['Change from last week'], /^Not available/); assert.equal(flat['Subtasks done on open tasks'], '1 of 4');
  assert.equal(flat['3 other subjects'], '5 open'); assert.match(flat['Open tasks with no subtasks'], /^2 /); assert.match(flat['Programming'], /about 90 min/);
});

test('facts: missing or broken data never throws and never prints undefined/NaN', () => {
  for (const f of [undefined, null, {}, { completion: {}, deadlines: {}, workload: { subjects: 'x' }, patterns: {} }, { completion: { weeklyCompletion: 'x', totalTasks: NaN } }]) {
    const html = factsHtml(f);
    assert.doesNotMatch(html, /undefined|NaN|null/); assert.ok(html.length > 0);
  }
  assert.deepEqual(factSections({ workload: { subjects: [] } })[2].rows, [['Open tasks', 'None']]);
});

// ---------- mock API contract (same rules as the backend) ----------
test('mock engine: POST /ai/insights follows the consent contract and never claims AI', () => {
  for (const body of [{}, { aiConsent: true }, { aiConsent: false }]) {
    const r = call('POST', '/ai/insights', body);
    assert.equal(r.mock, true); assert.equal(r.aiGenerated, false); assert.equal(r.source, 'mock-client'); assert.equal(insightSource(r).kind, 'demo');
    assert.equal(validInsights(r), true);
    assert.deepEqual(r.insights.map(i => i.area), Object.keys(INSIGHT_AREAS));
    assert.doesNotMatch(JSON.stringify(r), /groq|gemini/i);
  }
  for (const bad of ['true', 1, 'yes', null, [], {}, 'false']) rejects(() => call('POST', '/ai/insights', { aiConsent: bad }), 422, /aiConsent/);
  rejects(() => call('POST', '/ai/insights', [1]), 400);
});

test('mock engine: returns a fresh copy every time and the existing endpoints are unchanged', () => {
  const a = mockInsights(); a.summary = 'changed'; a.facts.completion.completed = 99;
  assert.notEqual(mockInsights().summary, 'changed'); assert.equal(mockInsights().facts.completion.completed, 6);
  const db = seedV2();
  assert.equal(mockV2Request(db, 'GET', '/progress', undefined, { todayIso: '2026-11-16' }).insightSource, 'mock-sample');
  assert.equal(mockV2Request(db, 'POST', '/ai/plan', { title: 'Paper', deadline: '2026-11-26' }, { todayIso: '2026-11-16' }).mock, true);
});

// ---------- page and client wiring (static) ----------
test('renderer: suggestion area labels are separate from suggestion text', () => {
  const html = insightsHtml({
    mock: false, aiGenerated: true, source: 'groq', summary: 'Summary',
    insights: [{ area: 'completion', text: 'Complete tasks.' }, { area: 'workload', text: 'No open work.' }, { area: 'deadlines', text: 'No deadlines.' }],
    suggestions: [{ area: 'completion', text: 'Keep tracking tasks.' }],
    facts: { completion: {}, deadlines: {}, workload: {}, patterns: {} }
  });
  assert.match(html, /<small class="tag">Completion<\/small><span class="tip-text">Keep tracking tasks\.<\/span>/);
});

test('page: the Generate button sends only {aiConsent: <box state>} and the box is cleared after every request', () => {
  const p = src('js/pages/progress.js');
  assert.equal((p.match(/api\.getInsights\(/g) || []).length, 1, 'one place sends insight requests');
  assert.match(p, /api\.getInsights\(\{aiConsent:box\.checked===true\}\)/);
  assert.doesNotMatch(p, /aiConsent:true/); assert.doesNotMatch(p, /aiConsent:(?!box)/);
  assert.match(p, /finally\{box\.checked=false\}/);
  assert.match(p, /id="ins-consent"/); assert.doesNotMatch(p, /id="ins-consent"[^>]*(checked|required)/); // optional and unticked by default
  assert.match(p, /guard\(async\(\)=>\{[\s\S]*\},card\)/); // one request at a time, card locked meanwhile
  assert.ok(p.indexOf('validInsights(r)') < p.indexOf('insightsHtml(r)'), 'shape is checked before anything is drawn');
  assert.equal((p.match(/\.innerHTML=/g) || []).length, 2, 'only the page template and the result block');
  assert.match(p, /out\.innerHTML=insightsHtml\(r\)/); // the result block receives only the escaping renderer's output
  assert.match(p, /out\.textContent=/); // loading and errors use textContent, never HTML
});

test('page: consent text names what is sent, what is not, both providers, and the fallback', () => {
  const p = src('js/pages/progress.js'), box = p.slice(p.indexOf('class="consent"'), p.indexOf('id="ins-gen"'));
  for (const w of [/aggregate task counts, workload and deadline statistics/, /Groq/, /Google Gemini/, /Task titles, subject names, your name, email, account identifiers, and calendar dates are never sent/, /rule-based insights are shown and nothing is sent/, /Optional/, /Tick the box again/]) assert.match(box, w);
  assert.doesNotMatch(box, /task titles? (and|may be sent)/i);
});

test('page: the existing Progress content is preserved', () => {
  const p = src('js/pages/progress.js');
  for (const w of ['Progress &amp; Procrastination Insights', 'Weekly Completion Trend', 'Productivity Insight', 'Completion Rate', 'On-time Completion', 'Tasks Completed', 'Overdue Tasks', "'rule-based':'RULE-BASED'", 'api.getProgress', 'bars(p.weeklyCompletion']) assert.ok(p.includes(w), w);
  assert.match(p, /\$\{AI_CARD\}`;wireInsights\(el\)/);
});

test('client: api.getInsights posts to /ai/insights; the legacy mock answers; V2 stays dormant', () => {
  const c = src('js/api/client.js');
  assert.match(c, /getInsights: b => req\('POST', '\/ai\/insights', b\)/);
  assert.match(c, /case 'POST \/ai\/insights': return mockInsights\(\);/);
  assert.match(c, /const MOCK_V2 = false;/);
  assert.match(src('js/config.js'), /USE_MOCK = false/);
});

test('client: existing plan and chat calls are untouched', () => {
  const c = src('js/api/client.js');
  assert.match(c, /planTask: b => req\('POST', '\/ai\/plan', b\), askAssistant: b => req\('POST', '\/ai\/chat', b\)/);
});

test('css: the new styles are additive and scoped to the insights card', () => {
  const css = src('css/styles.css'), block = css.slice(css.indexOf('/* Phase 4.2: AI Insights card'));
  assert.ok(block.length > 200);
  for (const sel of block.split('}').map(r => r.split('{')[0].trim()).filter(Boolean)) assert.match(sel, /#ins|\.ins-|\.tip-list|\.lim-list|\.tag|\.facts|@media/, sel);
});
