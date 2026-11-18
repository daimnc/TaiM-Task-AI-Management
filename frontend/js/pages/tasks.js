import {api} from '../api/client.js';
import {$,load,guard,esc,fmtDate,sortByDue,empty,toast,today,iso,categoryLabel,importancePill,statusPill,subjectName,isCompleted,CATEGORY_LABELS} from '../ui.js';
import {taskModal} from '../components/taskModal.js';
import {isOverdue,hasSubtasks,subtaskCounts} from '../taskStats.js';
const btn=(a,id,label,cls='')=>`<button class="lnk ${cls}" data-a="${a}" data-id="${esc(id)}">${label}</button>`;
// A task with subtasks is finished only through its subtasks (the server answers 409 to Done/Reopen), so only Start stays.
const stateBtns=t=>hasSubtasks(t)?(t.status==='not_started'?btn('start',t.task_id,'Start'):''):t.status==='completed'?btn('reopen',t.task_id,'Reopen'):(t.status==='not_started'?btn('start',t.task_id,'Start'):'')+btn('complete',t.task_id,'Done');
const sbtn=(a,t,s,label,cls='')=>`<button class="lnk ${cls}" data-a="${a}" data-id="${esc(t.task_id)}" data-sid="${esc(s.subtask_id)}">${label}</button>`;
const subRows=t=>hasSubtasks(t)?`<tr class="subs"><td colspan="7"><div class="subnote">Progress is calculated from subtasks. Complete or reopen a subtask to change it.</div><ul class="sublist">${t.subtasks.map(s=>{const d=s.status==='completed';return `<li class="${d?'done':''}"><span class="mark" aria-hidden="true">${d?'✓':'○'}</span><span class="st-title">${esc(s.title)}</span><small>~${esc(s.estimated_minutes)} min</small><span class="sacts">${d?sbtn('sub-reopen',t,s,'Reopen'):sbtn('sub-complete',t,s,'Complete')}${sbtn('sub-del',t,s,'Delete','del')}</span></li>`}).join('')}</ul></td></tr>`:'';
const progNote=t=>{if(!hasSubtasks(t))return '';const c=subtaskCounts(t);return `<small>${c.done} of ${c.total} subtasks</small>`};
const OK={start:'Task started',complete:'Task completed',reopen:'Task reopened',subComplete:'Subtask completed',subReopen:'Subtask reopened',subDel:'Subtask deleted'};
export default{title:'My Tasks',render(el){
 el.innerHTML=`<div class="page-head"><div><h2>My Tasks</h2><p class="sub">Manage assignments, exams, projects, and research.</p></div><button class="btn primary" id="add">+ Add Task</button></div>
 <div class="card"><div class="toolbar"><input id="q" placeholder="Search tasks…"><select id="cat"><option value="">All categories</option>${Object.entries(CATEGORY_LABELS).map(([v,l])=>`<option value="${v}">${l}</option>`).join('')}</select><select id="st"><option value="">All statuses</option><option value="active">Active (not completed)</option><option value="not_started">Not started</option><option value="in_progress">In progress</option><option value="completed">Completed</option></select></div><div id="list" class="tablewrap"></div></div>`;
 let tasks=[],subjects=[];const list=$('#list',el);
 const row=(t,td)=>`<tr><td><b>${esc(t.title)}</b><small>${esc(subjectName(subjects,t.subject_id))}</small></td><td data-l="Category">${esc(categoryLabel(t.category))}</td><td data-l="Deadline">${fmtDate(t.deadline)}${isOverdue(t,td)?' <span class="od">Overdue</span>':''}</td><td data-l="Importance">${importancePill(t.importance)}</td><td data-l="Status">${statusPill(t.status)}</td><td data-l="Progress"><span class="prog"><i style="width:${t.progress_pct}%"></i></span>${t.progress_pct}%${progNote(t)}</td><td class="acts">${stateBtns(t)}${btn('edit',t.task_id,'Edit')}${btn('del',t.task_id,'Delete','del')}</td></tr>${subRows(t)}`;
 const draw=()=>{const q=$('#q',el).value.toLowerCase(),c=$('#cat',el).value,s=$('#st',el).value,td=iso(today());
  const r=sortByDue(tasks).filter(t=>(!q||(t.title+' '+subjectName(subjects,t.subject_id)).toLowerCase().includes(q))&&(!c||t.category===c)&&(!s||(s==='active'?!isCompleted(t):t.status===s)));
  list.innerHTML=r.length?`<table><thead><tr><th>TASK</th><th>CATEGORY</th><th>DEADLINE</th><th>IMPORTANCE</th><th>STATUS</th><th>PROGRESS</th><th></th></tr></thead><tbody>${r.map(t=>row(t,td)).join('')}</tbody></table>`:empty(tasks.length?'No tasks match your filters.':'No tasks yet. Click "+ Add Task" to create one.')};
 const refresh=()=>load(list,()=>Promise.all([api.getTasks(),api.getSubjects()]),([t,s])=>{tasks=t;subjects=s;draw()});
 // One lock for every action in the list. Subtask actions (local=true) answer with the updated parent: it replaces the old one in
 // the local list and the table is redrawn, with no full reload. A stale list (404/409) is reloaded after the error is shown.
 const act=guard(async(fn,msg,local)=>{try{const r=await fn();if(msg)toast(msg);if(local&&r?.task_id){tasks=tasks.map(x=>x.task_id===r.task_id?r:x);draw()}else await refresh()}catch(e){toast(e.message,'bad');if(local&&(e.status===404||e.status===409))await refresh()}},list);
 ['q','cat','st'].forEach(i=>$('#'+i,el).oninput=draw);
 $('#add',el).onclick=()=>taskModal(null,refresh);
 list.onclick=e=>{const b=e.target.closest('[data-a]');if(!b)return;const t=tasks.find(x=>x.task_id===b.dataset.id);if(!t)return;const a=b.dataset.a,sid=b.dataset.sid,st=sid?(t.subtasks||[]).find(x=>x.subtask_id===sid):null;
  if(sid&&!st)return;
  if(a==='edit')taskModal(t,refresh);
  else if(a==='start')act(()=>api.startTask(t.task_id),OK.start);
  else if(a==='complete')act(()=>api.completeTask(t.task_id),OK.complete);
  else if(a==='reopen')act(()=>api.reopenTask(t.task_id),OK.reopen);
  else if(a==='sub-complete')act(()=>api.completeSubtask(t.task_id,sid),OK.subComplete,true);
  else if(a==='sub-reopen')act(()=>api.reopenSubtask(t.task_id,sid),OK.subReopen,true);
  else if(a==='sub-del'&&confirm(`Delete subtask "${st.title}"?`))act(()=>api.deleteSubtask(t.task_id,sid),OK.subDel,true);
  else if(a==='del'&&confirm(`Delete "${t.title}"?`))act(()=>api.deleteTask(t.task_id),'Task deleted')};
 refresh()}};
