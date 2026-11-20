// Phase 4.3: the "Plan my time" card on the AI Task Planner page. Read-only: it never creates or changes a task.
import { api } from '../api/client.js';
import { $, guard } from '../ui.js';
import { assistHtml, assistSource, validPlanAssist } from '../plannerAssist.js';

const opts = (list, sel, f) => list.map(v => `<option value="${v}"${v === sel ? ' selected' : ''}>${f(v)}</option>`).join('');
export const ASSIST_CARD = `<div class="card" id="pa"><div class="ins-head"><h3>Plan my time</h3><span class="pill st-not_started" id="pa-pill">NOT GENERATED YET</span></div>
 <p class="mut" style="line-height:1.7">TAiM works out what to do next and a day-by-day schedule from your open tasks and the time you have. An AI model (optional) may only reword the coaching note; it cannot change the plan.</p>
 <div class="row"><label>Time per day<select id="pa-hours">${opts([0.5, 1, 2, 3, 4], 2, h => h < 1 ? '30 min / day' : h + ' hour' + (h === 1 ? '' : 's') + ' / day')}</select></label><label>Plan for<select id="pa-days">${opts([3, 7, 14], 7, d => d + ' days')}</select></label></div>
 <div class="consent"><label class="cons"><input type="checkbox" id="pa-consent" aria-describedby="pa-info"><span>I agree that an anonymized summary of my plan may be sent to Groq and, if needed, Google Gemini to write the coaching note.</span></label>
  <small class="hint" id="pa-info">Optional. If you agree, TAiM sends anonymous task and subject labels (such as T1 and S1), importance and task status, relative days until deadlines, estimated minutes and estimate types, plus scheduling and risk indicators. It may also send aggregate counts, capacity figures, and yes/no workload flags. Task titles, subject names, your name, email, account identifiers, and calendar dates are never sent. Without the tick, rule-based coaching is shown and nothing is sent. Tick the box again for each new request.</small></div>
 <button class="btn primary" id="pa-gen" type="button">✦ Plan my time</button>
 <div id="pa-out" class="ins-out" aria-live="polite"><div class="state">Choose Plan my time to see your next task and schedule.</div></div></div>`;

export function wireAssist(el) {
  const card = $('#pa', el), out = $('#pa-out', el), box = $('#pa-consent', el), pill = $('#pa-pill', el), gen = $('#pa-gen', el);
  if (!card || !out || !box || !pill || !gen) return;
  const run = guard(async () => {
    out.className = 'state'; out.textContent = 'Planning…';
    try {
      const r = await api.getPlannerAssist({ hoursPerDay: +$('#pa-hours', el).value, horizonDays: +$('#pa-days', el).value, aiConsent: box.checked === true });
      if (!validPlanAssist(r)) throw new Error('The server sent an unexpected answer. Please try again.');
      const s = assistSource(r); pill.textContent = s.pill; pill.className = 'pill ' + s.cls; out.className = 'ins-result'; out.innerHTML = assistHtml(r);
    } catch (x) { pill.textContent = 'NOT GENERATED'; pill.className = 'pill st-not_started'; out.className = 'state err'; out.textContent = x && x.message ? x.message : 'The plan could not be generated.' }
    finally { box.checked = false } // each request needs its own consent
  }, card);
  gen.onclick = () => run();
}
