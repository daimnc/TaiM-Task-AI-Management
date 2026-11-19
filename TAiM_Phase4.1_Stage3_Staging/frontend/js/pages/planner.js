import {api} from '../api/client.js';
import {$,load,guard,esc,fmtDate,toast,today,iso,isCompleted,sortByDue} from '../ui.js';
import {MAX_SUBTASKS,MAX_STEP_TITLE,MAX_EDITOR_ROWS,subtaskCounts,subtaskCapacity,planStepsToSubtasks,addingReopens,rowsFromPlan,moveRow,removeRow,addRow,selectedIndexes,validateRows,rowsAsSteps,planSource} from '../taskStats.js';
// The planner only generates subtasks and appends them to an EXISTING parent task. It never creates tasks.
// Step dates from the plan are not shown or saved: subtasks have no date field.
// Every plan request needs the consent box ticked first (the box is cleared again after each request). Suggestions are editable rows:
// edit, add, remove, reorder and tick which ones to save. Only ticked, valid rows are sent, in the order shown.
const HINT='Choose a parent task, generate a breakdown, then review the steps before adding them as subtasks.';
const label=t=>`${t.title} · due ${fmtDate(t.deadline)}${isCompleted(t)?' · completed':''}`;
const opt=(t,sel)=>`<option value="${esc(t.task_id)}"${t.task_id===sel?' selected':''}>${esc(label(t))}</option>`;
// The locked area is inert while a guarded call runs, so focus is moved just after the lock is released.
const later=fn=>setTimeout(fn,0);
const rowHtml=(r,i,n)=>`<div class="srow" data-k="${r.key}"><input type="checkbox" data-f="sel" aria-label="Save step ${i+1}"${r.selected?' checked':''}>
 <div class="sfields"><input data-f="title" maxlength="${MAX_STEP_TITLE*2}" aria-label="Title of step ${i+1}" value="${esc(r.title)}" placeholder="Step title"><span class="smin"><input data-f="min" inputmode="numeric" aria-label="Minutes for step ${i+1}" value="${esc(r.minutes)}"> min</span></div>
 <div class="sacts"><button type="button" class="lnk" data-a="up" aria-label="Move step ${i+1} up"${i===0?' disabled':''}>↑</button><button type="button" class="lnk" data-a="down" aria-label="Move step ${i+1} down"${i===n-1?' disabled':''}>↓</button><button type="button" class="lnk del" data-a="del" aria-label="Remove step ${i+1}">Remove</button></div>
 <p class="err" data-e hidden></p></div>`;
export default{title:'AI Task Planner',render(el,q){
 load(el,()=>api.getTasks(),all=>{
  const head=`<div class="page-head"><div><h2>AI Task Planner</h2><p class="sub">Break a task into subtasks you can complete one by one.</p></div><span class="pill violet" id="src">✦ TASK PLANNER</span></div>`;
  if(!all.length){el.innerHTML=head+`<div class="card"><div class="state">You have no tasks yet. The planner adds subtasks to an existing task, so create a task in My Tasks first.<br><br><a class="btn primary" href="#/tasks">Go to My Tasks</a></div></div>`;return}
  let tasks=sortByDue(all),rows=null;
  const first=tasks.find(t=>t.task_id===q.get('task'))||tasks[0];
  el.innerHTML=`${head}<div class="grid2 even" id="grid"><form class="card" id="f"><h3>Plan subtasks for</h3>
   <label>Parent task<select name="task_id">${tasks.map(t=>opt(t,first.task_id)).join('')}</select></label>
   <label>Requirements<textarea name="requirements" maxlength="2000" placeholder="Optional: what does this task need?"></textarea></label>
   <div class="row"><label>Deadline<input type="date" name="deadline" required value="${esc(first.deadline||iso(today()))}"></label><label>Time per day<select name="hoursPerDay">${[0.5,1,2,3].map(h=>`<option value="${h}"${h===1?' selected':''}>${h<1?'30 min':h+' hour'}/day</option>`).join('')}</select></label></div>
   <small class="hint">Deadline and daily time help estimate the minutes per step. Step dates are not saved.</small>
   <div class="consent"><label class="cons"><input type="checkbox" name="aiConsent" id="consent" aria-describedby="consentInfo consentErr"><span>I agree that the task title, requirements, deadline and available hours per day may be sent to Groq first and, if needed, Google Gemini to suggest steps.</span></label>
    <small class="hint" id="consentInfo">Groq is tried first. If it fails or returns unusable steps, Google Gemini may also receive the same task details. If neither provider is configured or available, a built-in template is shown. Only the task title, requirements, deadline and available hours per day are sent. Nothing is sent until you tick this box, and you need to tick it again for each new plan.</small>
    <p class="err" id="consentErr" role="alert" hidden></p></div>
   <button class="btn primary" id="gen">✦ Generate breakdown</button></form>
   <div class="card"><h3>Current subtasks</h3><div id="cur"></div><h3 style="margin-top:18px">Suggested subtasks</h3><div id="out" class="note">${HINT}</div></div></div>`;
  const f=$('#f',el),out=$('#out',el),cur=$('#cur',el),grid=$('#grid',el),E=f.elements,parent=()=>tasks.find(t=>t.task_id===E.task_id.value),consentErr=$('#consentErr',el);
  const drawCur=()=>{const p=parent(),s=Array.isArray(p.subtasks)?p.subtasks:[],c=subtaskCounts(p);
   cur.innerHTML=(c.total?`<p class="hint">${c.done} of ${c.total} done · ${c.total} of ${MAX_SUBTASKS} used</p><ul class="sublist">${s.map(x=>`<li class="${x.status==='completed'?'done':''}"><span class="mark" aria-hidden="true">${x.status==='completed'?'✓':'○'}</span><span class="st-title">${esc(x.title)}</span><small>~${esc(x.estimated_minutes)} min</small></li>`).join('')}</ul>`:`<p class="hint">No subtasks yet · 0 of ${MAX_SUBTASKS} used</p>`)
    +(addingReopens(p)?`<p class="warnbox">This task is completed. Adding subtasks will reopen it.</p>`:'')};
  // Add is enabled only when 1..capacity steps are ticked, so the 20-subtask limit is never hit by a request.
  const sync=()=>{const add=$('#add',out);if(!add)return;const n=selectedIndexes(rows).length,cap=subtaskCapacity(parent()),m=$('#cap',out);
   add.disabled=!n||n>cap;
   const more=$('#more',out);if(more)more.disabled=rows.length>=MAX_EDITOR_ROWS;
   m.textContent=cap===0?`This task already has ${MAX_SUBTASKS} subtasks, the limit. Delete some in My Tasks to add more.`:n>cap?`Only ${cap} more subtask${cap===1?'':'s'} fit (limit ${MAX_SUBTASKS}). Untick ${n-cap} step${n-cap===1?'':'s'}.`:`${n} selected · ${cap} slot${cap===1?'':'s'} left`};
  const showErrors=errors=>{for(const r of rows){const box=$(`[data-k="${r.key}"]`,out);if(!box)continue;const e=errors[r.key],p=$('[data-e]',box);
   p.hidden=!e;p.textContent=e?[e.title&&`Title: ${e.title}`,e.minutes&&`Minutes: ${e.minutes}`].filter(Boolean).join(' '):'';
   $('[data-f="title"]',box).setAttribute('aria-invalid',e&&e.title?'true':'false');$('[data-f="min"]',box).setAttribute('aria-invalid',e&&e.minutes?'true':'false')}};
  const drawRows=(focusKey,sel)=>{const n=rows.length;$('#rows',out).innerHTML=rows.map((r,i)=>rowHtml(r,i,n)).join('');sync();
   if(focusKey){const box=$(`[data-k="${focusKey}"]`,out),b=box&&$(sel,box);(b&&!b.disabled?b:box&&$('[data-f="title"]',box))?.focus()}};
  const reset=()=>{rows=null;out.className='note';out.textContent=HINT;$('#src',el).textContent='✦ TASK PLANNER';E.aiConsent.checked=false;consentErr.hidden=true;drawCur()};
  E.task_id.onchange=()=>{E.deadline.value=parent().deadline||iso(today());reset()};
  E.aiConsent.onchange=()=>{if(E.aiConsent.checked)consentErr.hidden=true};
  const rowOf=t=>{const box=t.closest('[data-k]'),i=box?rows.findIndex(r=>r.key===box.dataset.k):-1;return i<0?null:{box,i,row:rows[i]}};
  out.onchange=e=>{if(!e.target.matches('[data-f="sel"]'))return;const o=rowOf(e.target);if(o){o.row.selected=e.target.checked;sync()}};
  out.oninput=e=>{const o=e.target.matches('[data-f="title"],[data-f="min"]')?rowOf(e.target):null;if(!o)return;
   if(e.target.dataset.f==='title')o.row.title=e.target.value;else o.row.minutes=e.target.value;
   const p=$('[data-e]',o.box);p.hidden=true;e.target.setAttribute('aria-invalid','false')}; // typing clears that row's message; it is checked again on Add
  out.onclick=e=>{const b=e.target.closest('[data-a],#more');if(!b||!rows)return;
   if(b.id==='more'){rows=addRow(rows);drawRows(rows[rows.length-1].key,'[data-f="title"]');return}
   const o=rowOf(b);if(!o)return;
   if(b.dataset.a==='up'||b.dataset.a==='down'){rows=moveRow(rows,o.i,b.dataset.a==='up'?-1:1);drawRows(o.row.key,`[data-a="${b.dataset.a}"]`)}
   else if(b.dataset.a==='del'){const next=rows[o.i+1]||rows[o.i-1];rows=removeRow(rows,o.i);if(rows.length)drawRows(next.key,'[data-f="title"]');else showEmpty()}};
  const showEmpty=()=>{rows=null;out.className='state';out.textContent='All steps were removed. Generate a new breakdown to continue.'};
  const showPlan=(r,p)=>{const s=planSource(r);$('#src',el).textContent=s.pill;rows=rowsFromPlan(r.subtasks);out.className='';
   out.innerHTML=`<p class="srcline ${s.kind}"><b>${esc(s.heading)}</b></p>${r.notice?`<p class="hint">${esc(r.notice)}</p>`:''}<div id="rows"></div>
    <button class="btn" id="more" type="button">+ Add a step</button><p class="hint" id="cap"></p>${addingReopens(p)?'<p class="warnbox">This task is completed. Adding subtasks will reopen it.</p>':''}<br><button class="btn primary" id="add" type="button">Add selected steps as subtasks</button>`;
   $('#add',out).onclick=()=>add();drawRows()};
  // One lock for the whole planner: no second generate or add while a request is pending, and the parent cannot change meanwhile.
  const gen=guard(async()=>{const p=parent();
   // No consent, no request: nothing is sent to the server (and so nothing to either provider) unless the box is ticked.
   if(!E.aiConsent.checked){consentErr.textContent='Tick the box to agree before generating a plan.';consentErr.hidden=false;later(()=>E.aiConsent.focus());return}
   consentErr.hidden=true;out.className='state';out.textContent='Generating…';
   try{const r=await api.planTask({title:p.title,requirements:E.requirements.value,deadline:E.deadline.value,hoursPerDay:+E.hoursPerDay.value,aiConsent:true});
    if(!Array.isArray(r.subtasks)||!r.subtasks.length){rows=null;$('#src',el).textContent=planSource(r).pill;out.className='state';out.textContent='No steps were generated. Try again.';return}
    showPlan(r,p)}
   catch(x){rows=null;out.className='state err';out.textContent=x.message}
   finally{E.aiConsent.checked=false}},grid); // the box is cleared after every request: each plan needs its own consent
  const add=guard(async()=>{const p=parent();
   const v=validateRows(rows);
   if(!v.count)return toast('Select at least one step','bad');
   showErrors(v.errors);
   if(!v.ok){const k=Object.keys(v.errors)[0],box=$(`[data-k="${k}"]`,out);box?.scrollIntoView?.({block:'nearest'});later(()=>$(v.errors[k].title?'[data-f="title"]':'[data-f="min"]',box)?.focus());return toast('Fix the highlighted steps first','bad')}
   const items=planStepsToSubtasks(rowsAsSteps(rows),selectedIndexes(rows));
   if(!items.length)return toast('Select at least one step','bad');
   if(items.length>subtaskCapacity(p))return toast(`Only ${subtaskCapacity(p)} more subtasks fit (limit ${MAX_SUBTASKS}).`,'bad');
   if(addingReopens(p)&&!confirm(`"${p.title}" is completed. Adding subtasks will reopen it and set it to In progress. Continue?`))return;
   try{const u=await api.addSubtasks(p.task_id,{subtasks:items});
    tasks=tasks.map(t=>t.task_id===u.task_id?u:t);[...E.task_id.options].find(o=>o.value===u.task_id).textContent=label(u); // the response is the updated parent: existing subtasks are kept, new ones appended
    rows=null;out.className='note';out.textContent=`${items.length} subtask${items.length===1?'':'s'} added to "${u.title}". Generate again to add more, or open My Tasks to work on them.`;drawCur();
    toast(`${items.length} subtask${items.length===1?'':'s'} added`)}
   catch(x){toast(x.message,'bad')}},grid); // on failure nothing was saved (all or nothing) and the edited steps stay for a retry
  f.onsubmit=e=>{e.preventDefault();gen()};
  drawCur()})}};
