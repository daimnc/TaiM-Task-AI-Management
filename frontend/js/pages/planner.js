import {api} from '../api/client.js';
import {$,load,guard,esc,fmtDate,toast,today,iso,isCompleted,sortByDue} from '../ui.js';
import {MAX_SUBTASKS,subtaskCounts,subtaskCapacity,planStepsToSubtasks,addingReopens} from '../taskStats.js';
// The planner only generates subtasks and appends them to an EXISTING parent task. It never creates tasks.
// Step dates from the plan are not shown or saved: subtasks have no date field.
const HINT='Choose a parent task, generate a breakdown, then review the steps before adding them as subtasks.';
const label=t=>`${t.title} · due ${fmtDate(t.deadline)}${isCompleted(t)?' · completed':''}`;
const opt=(t,sel)=>`<option value="${esc(t.task_id)}"${t.task_id===sel?' selected':''}>${esc(label(t))}</option>`;
export default{title:'AI Task Planner',render(el,q){
 load(el,()=>api.getTasks(),all=>{
  const head=`<div class="page-head"><div><h2>AI Task Planner</h2><p class="sub">Break a task into subtasks you can complete one by one.</p></div><span class="pill violet" id="src">✦ TASK PLANNER</span></div>`;
  if(!all.length){el.innerHTML=head+`<div class="card"><div class="state">You have no tasks yet. The planner adds subtasks to an existing task, so create a task in My Tasks first.<br><br><a class="btn primary" href="#/tasks">Go to My Tasks</a></div></div>`;return}
  let tasks=sortByDue(all),steps=null;
  const first=tasks.find(t=>t.task_id===q.get('task'))||tasks[0];
  el.innerHTML=`${head}<div class="grid2 even" id="grid"><form class="card" id="f"><h3>Plan subtasks for</h3>
   <label>Parent task<select name="task_id">${tasks.map(t=>opt(t,first.task_id)).join('')}</select></label>
   <label>Requirements<textarea name="requirements" maxlength="2000" placeholder="Optional: what does this task need?"></textarea></label>
   <div class="row"><label>Deadline<input type="date" name="deadline" required value="${esc(first.deadline||iso(today()))}"></label><label>Time per day<select name="hoursPerDay">${[0.5,1,2,3].map(h=>`<option value="${h}"${h===1?' selected':''}>${h<1?'30 min':h+' hour'}/day</option>`).join('')}</select></label></div>
   <small class="hint">Deadline and daily time only estimate the minutes per step. Step dates are not saved.</small><br>
   <button class="btn primary" id="gen">✦ Generate breakdown</button></form>
   <div class="card"><h3>Current subtasks</h3><div id="cur"></div><h3 style="margin-top:18px">Suggested subtasks</h3><div id="out" class="note">${HINT}</div></div></div>`;
  const f=$('#f',el),out=$('#out',el),cur=$('#cur',el),grid=$('#grid',el),E=f.elements,parent=()=>tasks.find(t=>t.task_id===E.task_id.value);
  const drawCur=()=>{const p=parent(),s=Array.isArray(p.subtasks)?p.subtasks:[],c=subtaskCounts(p);
   cur.innerHTML=(c.total?`<p class="hint">${c.done} of ${c.total} done · ${c.total} of ${MAX_SUBTASKS} used</p><ul class="sublist">${s.map(x=>`<li class="${x.status==='completed'?'done':''}"><span class="mark" aria-hidden="true">${x.status==='completed'?'✓':'○'}</span><span class="st-title">${esc(x.title)}</span><small>~${esc(x.estimated_minutes)} min</small></li>`).join('')}</ul>`:`<p class="hint">No subtasks yet · 0 of ${MAX_SUBTASKS} used</p>`)
    +(addingReopens(p)?`<p class="warnbox">This task is completed. Adding subtasks will reopen it.</p>`:'')};
  // Add is enabled only when 1..capacity steps are ticked, so the 20-subtask limit is never hit by a request.
  const sync=()=>{const add=$('#add',out);if(!add)return;const n=out.querySelectorAll('[data-i]:checked').length,cap=subtaskCapacity(parent()),m=$('#cap',out);
   add.disabled=!n||n>cap;
   m.textContent=cap===0?`This task already has ${MAX_SUBTASKS} subtasks, the limit. Delete some in My Tasks to add more.`:n>cap?`Only ${cap} more subtask${cap===1?'':'s'} fit (limit ${MAX_SUBTASKS}). Untick ${n-cap} step${n-cap===1?'':'s'}.`:`${n} selected · ${cap} slot${cap===1?'':'s'} left`};
  const reset=()=>{steps=null;out.className='note';out.textContent=HINT;$('#src',el).textContent='✦ TASK PLANNER';drawCur()};
  E.task_id.onchange=()=>{E.deadline.value=parent().deadline||iso(today());reset()};
  out.onchange=e=>{if(e.target.matches('[data-i]'))sync()};
  // One lock for the whole planner: no second generate or add while a request is pending, and the parent cannot change meanwhile.
  const gen=guard(async()=>{const p=parent();out.className='state';out.textContent='Generating…';
   try{const r=await api.planTask({title:p.title,requirements:E.requirements.value,deadline:E.deadline.value,hoursPerDay:+E.hoursPerDay.value});
    $('#src',el).textContent=r.aiGenerated?'✦ AI-GENERATED PLAN':'✦ TEMPLATE PLAN · NO AI MODEL USED';
    if(!Array.isArray(r.subtasks)||!r.subtasks.length){steps=null;out.className='state';out.textContent='No steps were generated. Try again.';return}
    steps=r.subtasks;out.className='';
    out.innerHTML=`<p class="hint">${esc(r.notice||'')}</p>${steps.map((s,i)=>`<label class="chk"><span><b>${esc(s.title)}</b><small>~${esc(s.minutes)} min</small></span><input type="checkbox" checked data-i="${i}"></label>`).join('')}<p class="hint" id="cap"></p>${addingReopens(p)?'<p class="warnbox">This task is completed. Adding subtasks will reopen it.</p>':''}<br><button class="btn primary" id="add" type="button">Add selected steps as subtasks</button>`;
    $('#add',out).onclick=()=>add();sync()}
   catch(x){steps=null;out.className='state err';out.textContent=x.message}},grid);
  const add=guard(async()=>{const p=parent(),ids=[...out.querySelectorAll('[data-i]:checked')].map(c=>+c.dataset.i),items=planStepsToSubtasks(steps,ids);
   if(!items.length)return toast('Select at least one step','bad');
   if(items.length>subtaskCapacity(p))return toast(`Only ${subtaskCapacity(p)} more subtasks fit (limit ${MAX_SUBTASKS}).`,'bad');
   if(addingReopens(p)&&!confirm(`"${p.title}" is completed. Adding subtasks will reopen it and set it to In progress. Continue?`))return;
   try{const u=await api.addSubtasks(p.task_id,{subtasks:items});
    tasks=tasks.map(t=>t.task_id===u.task_id?u:t);[...E.task_id.options].find(o=>o.value===u.task_id).textContent=label(u); // the response is the updated parent: existing subtasks are kept, new ones appended
    steps=null;out.className='note';out.textContent=`${items.length} subtask${items.length===1?'':'s'} added to "${u.title}". Generate again to add more, or open My Tasks to work on them.`;drawCur();
    toast(`${items.length} subtask${items.length===1?'':'s'} added`)}
   catch(x){toast(x.message,'bad')}},grid); // on failure nothing was saved (all or nothing) and the ticked steps stay for a retry
  f.onsubmit=e=>{e.preventDefault();gen()};
  drawCur()})}};
