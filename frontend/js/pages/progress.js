import {api} from '../api/client.js';
import {$,load,esc,bars,guard} from '../ui.js';
import {insightsHtml,insightSource,validInsights} from '../insights.js';
// insightSource comes from the API: 'rule-based' (computed from your tasks) or 'mock-sample' (browser demo data).
const SRC={'rule-based':'RULE-BASED','mock-sample':'SAMPLE DATA'};
// AI Insights (Phase 4.2). Consent is optional: unticked = rule-based insights and nothing is sent to any AI provider. The box is cleared after every request.
const AI_CARD=`<div class="card" id="ins"><div class="ins-head"><h3>AI Insights</h3><span class="pill st-not_started" id="ins-pill">NOT GENERATED YET</span></div>
 <p class="mut" style="line-height:1.7">A plain-language reading of your recorded tasks. TAiM calculates every number itself; an AI model (optional) only helps explain them.</p>
 <div class="consent"><label class="cons"><input type="checkbox" id="ins-consent" aria-describedby="ins-info"><span>I agree that anonymized task statistics may be sent to Groq and, if needed, Google Gemini to write the explanation.</span></label>
  <small class="hint" id="ins-info">Optional. The data may include aggregate task counts, workload and deadline statistics, importance categories, weekday patterns (when enough history exists), and anonymous labels such as S1 or T1. Task titles, subject names, your name, email, account identifiers, and calendar dates are never sent. Without the tick, rule-based insights are shown and nothing is sent. Tick the box again for each new request.</small></div>
 <button class="btn primary" id="ins-gen" type="button">✦ Generate insights</button>
 <div id="ins-out" class="ins-out" aria-live="polite"><div class="state">Choose Generate insights to see your summary.</div></div></div>`;
function wireInsights(el){
 const card=$('#ins',el),out=$('#ins-out',el),box=$('#ins-consent',el),pill=$('#ins-pill',el);
 const gen=guard(async()=>{out.className='state';out.textContent='Generating insights…';
  try{const r=await api.getInsights({aiConsent:box.checked===true});
   if(!validInsights(r))throw new Error('The server sent an unexpected answer. Please try again.');
   const s=insightSource(r);pill.textContent=s.pill;pill.className='pill '+s.cls;out.className='ins-result';out.innerHTML=insightsHtml(r)}
  catch(x){pill.textContent='NOT GENERATED';pill.className='pill st-not_started';out.className='state err';out.textContent=x&&x.message?x.message:'Insights could not be generated.'}
  finally{box.checked=false}},card);
 $('#ins-gen',el).onclick=()=>gen()}
export default{title:'My Progress',render(el){load(el,api.getProgress,p=>{
 const s=(l,v)=>`<div class="card stat"><span class="mut">${l}</span><b>${v}</b></div>`,tag=SRC[p.insightSource];
 el.innerHTML=`<div class="page-head"><div><h2>Progress &amp; Procrastination Insights</h2><p class="sub">Understand your productivity using recorded activity.</p></div></div>
 <div class="stats">${s('Completion Rate',p.completionRate+'%')}${s('On-time Completion',p.onTimeRate+'%')}${s('Tasks Completed',p.completed)}${s('Overdue Tasks',p.overdue)}</div>
 <div class="grid2 even"><div class="card"><h3>Weekly Completion Trend</h3>${bars(p.weeklyCompletion,p.weeklyCompletion.map((_,i)=>'W'+(i+1)))}</div>
 <div class="card"><h3>Productivity Insight ${tag?`<span class="pill violet">${tag}</span>`:''}</h3><p class="mut" style="line-height:1.7">${esc(p.insight)}</p><div class="note">Insights are based on task history entered into TAiM. They are suggestions, not a diagnosis or judgment.</div></div></div>${AI_CARD}`;wireInsights(el)})}};
