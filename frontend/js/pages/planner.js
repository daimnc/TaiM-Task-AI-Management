import {api} from '../api/client.js';
import {$,esc,fmtDate,toast,today,iso} from '../ui.js';
export default{title:'AI Task Planner',render(el,q){
 el.innerHTML=`<div class="page-head"><div><h2>AI Task Planner</h2><p class="sub">Break large academic tasks into manageable activities.</p></div><span class="pill violet">✦ AI-POWERED · DEMO</span></div>
 <div class="grid2 even"><form class="card" id="f"><h3>Describe your task</h3><label>Task<input name="title" required value="Research Paper: Artificial Intelligence"></label>
 <label>Requirements<textarea name="requirements">Research and write a paper with introduction, related literature, discussion, and conclusion.</textarea></label>
 <div class="row"><label>Deadline<input type="date" name="deadline" required value="${iso(today())}"></label><label>Time per day<select name="hoursPerDay">${[0.5,1,2,3].map(h=>`<option value="${h}"${h===1?' selected':''}>${h<1?'30 min':h+' hour'}/day</option>`).join('')}</select></label></div>
 <button class="btn primary" id="gen">✦ Generate breakdown</button></form>
 <div class="card"><h3>Suggested subtasks</h3><div id="out" class="note">Your AI-generated task breakdown will appear here. Review the steps before adding them to your task list.</div></div></div>`;
 const f=$('#f',el),out=$('#out',el);let parent={category:'Assignment'};
 if(q.get('task'))api.getTasks().then(ts=>{const t=ts.find(x=>x.id===q.get('task'));if(t){parent=t;f.title.value=t.title;f.deadline.value=t.deadline}}).catch(()=>{});
 f.onsubmit=async e=>{e.preventDefault();const b=$('#gen',el);b.disabled=true;out.className='state';out.textContent='Generating…';
  try{const body=Object.fromEntries(new FormData(f)),r=await api.planTask(body),title=body.title;
   out.className='';out.innerHTML=`<p class="mut small">${r.mock?'Mock response — not real AI.':''}</p>${r.subtasks.map((s,i)=>`<label class="chk"><span><b>${esc(s.title)}</b><small>Due ${fmtDate(s.dueDate)} · ~${s.minutes} min</small></span><input type="checkbox" checked data-i="${i}"></label>`).join('')}<br><button class="btn primary" id="add">Add subtasks to My Tasks</button>`;
   $('#add',out).onclick=async()=>{const sel=[...out.querySelectorAll('[data-i]:checked')].map(c=>r.subtasks[+c.dataset.i]);if(!sel.length)return toast('Select at least one subtask','bad');
    try{await Promise.all(sel.map(s=>api.createTask({title:`${title} — ${s.title}`,course:parent.course||'',category:parent.category,priority:parent.priority||'Medium',deadline:s.dueDate,progress:0})));toast(`${sel.length} subtasks added`);location.hash='#/tasks'}catch(x){toast(x.message,'bad')}}}
  catch(x){out.className='state err';out.textContent=x.message}b.disabled=false}}};
