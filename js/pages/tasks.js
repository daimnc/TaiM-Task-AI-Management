import {api} from '../api/client.js';
import {$,load,esc,fmtDate,pill,isDone,sortByDue,empty,toast} from '../ui.js';
import {taskModal,CATEGORIES,opts} from '../components/taskModal.js';
const row=t=>`<tr><td><b>${esc(t.title)}</b><small>${esc(t.course)}</small></td><td data-l="Category">${esc(t.category)}</td><td data-l="Deadline">${fmtDate(t.deadline)}</td><td data-l="Priority">${pill(t.priority)}</td><td data-l="Progress"><span class="prog"><i style="width:${t.progress}%"></i></span>${t.progress}%</td><td class="acts"><button class="lnk" data-a="done" data-id="${t.id}">${isDone(t)?'Reopen':'Done'}</button><button class="lnk" data-a="edit" data-id="${t.id}">Edit</button><button class="lnk del" data-a="del" data-id="${t.id}">Delete</button></td></tr>`;
export default{title:'My Tasks',render(el){
 el.innerHTML=`<div class="page-head"><div><h2>My Tasks</h2><p class="sub">Manage assignments, exams, projects, and research.</p></div><button class="btn primary" id="add">+ Add Task</button></div>
 <div class="card"><div class="toolbar"><input id="q" placeholder="Search tasks…"><select id="cat"><option value="">All categories</option>${opts(CATEGORIES)}</select><select id="st"><option value="">All statuses</option><option value="active">Active</option><option value="done">Completed</option></select></div><div id="list" class="tablewrap"></div></div>`;
 let tasks=[];const list=$('#list',el);
 const draw=()=>{const q=$('#q',el).value.toLowerCase(),c=$('#cat',el).value,s=$('#st',el).value;
  const r=sortByDue(tasks).filter(t=>(!q||(t.title+t.course).toLowerCase().includes(q))&&(!c||t.category===c)&&(!s||(s==='done')===isDone(t)));
  list.innerHTML=r.length?`<table><thead><tr><th>TASK</th><th>CATEGORY</th><th>DEADLINE</th><th>PRIORITY</th><th>PROGRESS</th><th></th></tr></thead><tbody>${r.map(row).join('')}</tbody></table>`:empty(tasks.length?'No tasks match your filters.':'No tasks yet. Click "+ Add Task" to create one.')};
 const refresh=()=>load(list,api.getTasks,t=>{tasks=t;draw()});
 const act=async fn=>{try{await fn();refresh()}catch(e){toast(e.message,'bad')}};
 ['q','cat','st'].forEach(i=>$('#'+i,el).oninput=draw);
 $('#add',el).onclick=()=>taskModal(null,refresh);
 list.onclick=e=>{const b=e.target.closest('[data-a]');if(!b)return;const t=tasks.find(x=>x.id===b.dataset.id);
  if(b.dataset.a==='edit')taskModal(t,refresh);
  if(b.dataset.a==='done')act(()=>api.updateTask(t.id,{progress:isDone(t)?80:100}));
  if(b.dataset.a==='del'&&confirm(`Delete "${t.title}"?`))act(()=>api.deleteTask(t.id).then(()=>toast('Task deleted')))};
 refresh()}};
