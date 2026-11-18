import {api} from '../api/client.js';
import {$,load,esc,today,fmtDate,categoryLabel,subjectName,isCompleted,catClass} from '../ui.js';
import {taskModal} from '../components/taskModal.js';
import {monthInfo,dateKey,shiftMonth,tasksByDate,monthTasks} from '../taskStats.js';
export default{title:'Academic Calendar',render(el){
 const t0=today();let y=t0.getFullYear(),m=t0.getMonth(),tasks=[],subjects=[];
 el.innerHTML=`<div class="page-head"><div><h2>Academic Calendar</h2><p class="sub">A unified view of all your deadlines.</p></div><button class="btn" id="add">+ Add task</button></div>
 <div class="card"><div class="row between"><h3 id="lbl" style="margin:0"></h3><div class="row"><button class="btn" data-n="-1" aria-label="Previous month">‹</button><button class="btn" data-n="0">Today</button><button class="btn" data-n="1" aria-label="Next month">›</button></div></div><div id="cal"></div></div>
 <p class="legend mut">Violet: Assignment / Research &nbsp; Cyan: Exam / Quiz &nbsp; Orange: Project &nbsp; Grey: Other &nbsp; Faded: Completed</p>`;
 const cal=$('#cal',el);
 const draw=()=>{$('#lbl',el).textContent=new Date(y,m).toLocaleDateString('en-US',{month:'long',year:'numeric'});
  const {first,days}=monthInfo(y,m),by=tasksByDate(tasks),cls=t=>`${catClass(t.category)}${isCompleted(t)?' done':''}`;
  let h=['Sun','Mon','Tue','Wed','Thu','Fri','Sat'].map(d=>`<div class="dow">${d}</div>`).join('')+'<div class="day off"></div>'.repeat(first);
  for(let d=1;d<=days;d++){const k=dateKey(y,m,d),ev=by.get(k)||[];h+=`<div class="day" data-date="${k}"><span>${d}</span>${ev.map(t=>`<button class="chip ${cls(t)}" data-id="${esc(t.task_id)}" title="${esc(t.title)} · ${esc(subjectName(subjects,t.subject_id))}">${esc(t.title)}</button>`).join('')}<div class="dots">${ev.map(t=>`<i class="${cls(t)}"></i>`).join('')}</div></div>`}
  const mt=monthTasks(tasks,y,m);
  cal.innerHTML=`<div class="calgrid">${h}</div><div class="agenda">${mt.map(t=>`<button class="ag" data-id="${esc(t.task_id)}"><i class="${cls(t)}"></i><span><b>${esc(t.title)}</b><small>${fmtDate(t.deadline)} · ${esc(categoryLabel(t.category))} · ${esc(subjectName(subjects,t.subject_id))}${isCompleted(t)?' · Completed':''}</small></span></button>`).join('')||'<p class="mut small">No deadlines this month.</p>'}</div>`};
 const refresh=()=>load(cal,()=>Promise.all([api.getTasks(),api.getSubjects()]),([t,s])=>{tasks=t;subjects=s;draw()});
 el.onclick=e=>{const n=e.target.closest('[data-n]');
  if(n){const v=+n.dataset.n;if(v){({y,m}=shiftMonth(y,m,v))}else{y=t0.getFullYear();m=t0.getMonth()}draw();return}
  const c=e.target.closest('.chip,.ag');if(c){const t=tasks.find(x=>x.task_id===c.dataset.id);if(t)taskModal(t,refresh);return}
  const d=e.target.closest('.day[data-date]');if(d)taskModal(null,refresh,{deadline:d.dataset.date})};
 $('#add',el).onclick=()=>taskModal(null,refresh);
 refresh()}};
