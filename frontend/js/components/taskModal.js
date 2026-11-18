import {api} from '../api/client.js';
import {modal,toast,esc,today,iso,cleanName,isCompleted,CATEGORY_LABELS,IMPORTANCE_LABELS} from '../ui.js';
export const CATEGORIES=Object.keys(CATEGORY_LABELS);
export const opts=(l,s)=>l.map(x=>`<option${String(x)===String(s)?' selected':''}>${x}</option>`).join('');
const kv=(m,s)=>Object.entries(m).map(([v,l])=>`<option value="${v}"${v===s?' selected':''}>${l}</option>`).join('');
const NEW='__new__';
// Add (task=null) or edit a task. `done` runs after a successful save. `defaults` may hold deadline or subject_id.
// New tasks never send status or progress_pct (the server sets them). Status changes use start/complete/reopen on the Tasks page.
export async function taskModal(task,done,defaults={}){
 let subjects;try{subjects=await api.getSubjects()}catch(e){return toast(e.message,'bad')}
 const t={title:'',subject_id:subjects[0]?.subject_id??NEW,category:'assignment',importance:'medium',deadline:iso(today()),progress_pct:0,...defaults,...task};
 const sel=subjects.some(s=>s.subject_id===t.subject_id)?t.subject_id:NEW,locked=!!task&&isCompleted(task);let created=null;
 const subjOpts=subjects.map(s=>`<option value="${esc(s.subject_id)}"${s.subject_id===sel?' selected':''}>${esc(s.subject_name)}</option>`).join('')+`<option value="${NEW}"${sel===NEW?' selected':''}>+ New subject…</option>`;
 modal(task?'Edit task':'Add task',`
 <label>Title<input name="title" required maxlength="120" value="${esc(t.title)}"></label>
 <label>Subject<select name="subject_id" onchange="this.form.querySelector('[data-ns]').hidden=this.value!=='${NEW}'">${subjOpts}</select></label>
 <label data-ns${sel===NEW?'':' hidden'}>New subject name<input name="new_subject" maxlength="100" placeholder="e.g. Mathematics"></label>
 <div class="row"><label>Category<select name="category">${kv(CATEGORY_LABELS,t.category)}</select></label><label>Importance<select name="importance">${kv(IMPORTANCE_LABELS,t.importance)}</select></label></div>
 <label>Deadline<input type="date" name="deadline" required value="${esc(t.deadline)}"></label>
 ${task?`<label><span>Progress: <output>${t.progress_pct}</output>%</span><input type="range" name="progress_pct" min="0" max="100" step="1" value="${t.progress_pct}"${locked?' disabled':''} oninput="this.parentNode.querySelector('output').value=this.value"></label><small class="hint">${locked?'Completed tasks stay at 100%. Reopen the task to change progress.':'Progress does not change the status. Use Start or Done in the task list.'}</small>`:''}`,
 async fd=>{
  const b={title:cleanName(fd.get('title')),category:fd.get('category'),importance:fd.get('importance'),deadline:fd.get('deadline')};
  if(!b.title)throw new Error('Title is required');if(!b.deadline)throw new Error('Deadline is required');
  let sid=fd.get('subject_id');
  if(sid===NEW){const name=cleanName(fd.get('new_subject'));if(!name)throw new Error('Enter a name for the new subject');
   if(!created||created.subject_name!==name)created=await api.createSubject({subject_name:name}); // reused if the task save fails and the user retries
   sid=created.subject_id}
  b.subject_id=sid;
  if(task){if(fd.has('progress_pct'))b.progress_pct=+fd.get('progress_pct');await api.updateTask(task.task_id,b)}else await api.createTask(b);
  toast(task?'Task updated':'Task added');done()});
}
