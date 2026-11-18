import {api} from '../api/client.js';
import {$,load,esc,fmtDate,toast,today,iso,cleanName,joinTitle,addSequentially,CATEGORY_LABELS,IMPORTANCE_LABELS} from '../ui.js';
const NEW='__new__',kv=(m,s)=>Object.entries(m).map(([v,l])=>`<option value="${v}"${v===s?' selected':''}>${l}</option>`).join('');
export default{title:'AI Task Planner',render(el,q){
 load(el,()=>Promise.all([api.getSubjects(),q.get('task')?api.getTasks().catch(()=>[]):[]]),([subjects,tasks])=>{
 const parent=tasks.find(x=>x.task_id===q.get('task'))||{},sel=subjects.some(s=>s.subject_id===parent.subject_id)?parent.subject_id:(subjects[0]?.subject_id??NEW);
 el.innerHTML=`<div class="page-head"><div><h2>AI Task Planner</h2><p class="sub">Break large academic tasks into manageable activities.</p></div><span class="pill violet" id="src">✦ TASK PLANNER</span></div>
 <div class="grid2 even"><form class="card" id="f"><h3>Describe your task</h3><label>Task<input name="title" required maxlength="120" value="${esc(parent.title||'Research Paper: Artificial Intelligence')}"></label>
 <label>Requirements<textarea name="requirements" maxlength="2000">Research and write a paper with introduction, related literature, discussion, and conclusion.</textarea></label>
 <div class="row"><label>Deadline<input type="date" name="deadline" required value="${esc(parent.deadline||iso(today()))}"></label><label>Time per day<select name="hoursPerDay">${[0.5,1,2,3].map(h=>`<option value="${h}"${h===1?' selected':''}>${h<1?'30 min':h+' hour'}/day</option>`).join('')}</select></label></div>
 <h3 style="margin-top:6px">Save steps as</h3>
 <label>Subject<select name="subject_id" onchange="this.form.querySelector('[data-ns]').hidden=this.value!=='${NEW}'">${subjects.map(s=>`<option value="${esc(s.subject_id)}"${s.subject_id===sel?' selected':''}>${esc(s.subject_name)}</option>`).join('')}<option value="${NEW}"${sel===NEW?' selected':''}>+ New subject…</option></select></label>
 <label data-ns${sel===NEW?'':' hidden'}>New subject name<input name="new_subject" maxlength="100" placeholder="e.g. Research Methods"></label>
 <div class="row"><label>Category<select name="category">${kv(CATEGORY_LABELS,parent.category||'assignment')}</select></label><label>Importance<select name="importance">${kv(IMPORTANCE_LABELS,parent.importance||'medium')}</select></label></div>
 <button class="btn primary" id="gen">✦ Generate breakdown</button></form>
 <div class="card"><h3>Suggested subtasks</h3><div id="out" class="note">Your task breakdown will appear here. Review the steps before adding them to your task list.</div></div></div>`;
 const f=$('#f',el),out=$('#out',el),E=f.elements;let created=null;
 f.onsubmit=async e=>{e.preventDefault();const b=$('#gen',el);b.disabled=true;out.className='state';out.textContent='Generating…';
  try{const title=cleanName(E.title.value),r=await api.planTask({title,requirements:E.requirements.value,deadline:E.deadline.value,hoursPerDay:+E.hoursPerDay.value});
   $('#src',el).textContent=r.aiGenerated?'✦ AI-GENERATED PLAN':'✦ TEMPLATE PLAN · NO AI MODEL USED';
   out.className='';out.innerHTML=`<p class="hint">${esc(r.notice||'')}</p>${r.subtasks.map((s,i)=>`<label class="chk"><span><b>${esc(s.title)}</b><small>Due ${fmtDate(s.dueDate)} · ~${s.minutes} min</small></span><input type="checkbox" checked data-i="${i}"></label>`).join('')}<br><button class="btn primary" id="add">Add steps to My Tasks</button>`;
   $('#add',out).onclick=async()=>{const ids=[...out.querySelectorAll('[data-i]:checked')].map(c=>+c.dataset.i);if(!ids.length)return toast('Select at least one step','bad');
    const add=$('#add',out);add.disabled=true;
    try{let sid=E.subject_id.value;
     if(sid===NEW){const name=cleanName(E.new_subject.value);if(!name)throw new Error('Enter a name for the new subject');if(!created||created.subject_name!==name)created=await api.createSubject({subject_name:name});sid=created.subject_id}
     const res=await addSequentially(ids,i=>api.createTask({title:joinTitle(title,r.subtasks[i].title),subject_id:sid,category:E.category.value,importance:E.importance.value,deadline:r.subtasks[i].dueDate}),
      i=>{const c=out.querySelector(`[data-i="${ids[i]}"]`);c.checked=false;c.disabled=true}); // saved steps are locked, so a retry cannot add them twice
     if(res.error){toast(`Added ${res.ok} of ${ids.length} steps. Stopped at "${r.subtasks[ids[res.failedAt]].title}": ${res.error.message}`,'bad');add.disabled=false;return}
     toast(`${res.ok} step${res.ok===1?'':'s'} added`);location.hash='#/tasks'}
    catch(x){toast(x.message,'bad');add.disabled=false}}}
  catch(x){out.className='state err';out.textContent=x.message}b.disabled=false}})}};
