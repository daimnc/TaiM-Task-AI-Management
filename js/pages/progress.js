import {api} from '../api/client.js';
import {load,esc,bars} from '../ui.js';
export default{title:'My Progress',render(el){load(el,api.getProgress,p=>{
 const s=(l,v)=>`<div class="card stat"><span class="mut">${l}</span><b>${v}</b></div>`;
 el.innerHTML=`<div class="page-head"><div><h2>Progress &amp; Procrastination Insights</h2><p class="sub">Understand your productivity using recorded activity.</p></div></div>
 <div class="stats">${s('Completion Rate',p.completionRate+'%')}${s('On-time Completion',p.onTimeRate+'%')}${s('Tasks Completed',p.completed)}${s('Overdue Tasks',p.overdue)}</div>
 <div class="grid2 even"><div class="card"><h3>Weekly Completion Trend</h3>${bars(p.weeklyCompletion,p.weeklyCompletion.map((_,i)=>'W'+(i+1)))}</div>
 <div class="card"><h3>AI Productivity Insight <span class="pill violet">DEMO</span></h3><p class="mut" style="line-height:1.7">${esc(p.insight)}</p><div class="note">Insights are based on task history entered into TAiM. They are suggestions, not a diagnosis or judgment.</div></div></div>`})}};
