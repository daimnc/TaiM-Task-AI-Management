import {api} from '../api/client.js';
import {$,load,esc,today,iso,pad,fmtDate,sortByDue} from '../ui.js';
import {taskModal} from '../components/taskModal.js';
export default{title:'Academic Calendar',render(el){
 const t0=today();let y=t0.getFullYear(),m=t0.getMonth(),tasks=[];
 el.innerHTML=`<div class="page-head"><div><h2>Academic Calendar</h2><p class="sub">A unified view of all your deadlines.</p></div><button class="btn" id="add">+ Add task</button></div>
 <div class="card"><div class="row between"><h3 id="lbl" style="margin:0"></h3><div class="row"><button class="btn" data-n="-1">‹</button><button class="btn" data-n="0">Today</button><button class="btn" data-n="1">›</button></div></div><div id="cal"></div></div>
 <p class="legend mut">Violet: Assignment / Research &nbsp; Cyan: Examination &nbsp; Orange: Project</p>`;
 const cal=$('#cal',el);
 const draw=()=>{$('#lbl',el).textContent=new Date(y,m).toLocaleDateString('en-US',{month:'long',year:'numeric'});
  const first=new Date(y,m,1).getDay(),n=new Date(y,m+1,0).getDate();
  let h=['Sun','Mon','Tue','Wed','Thu','Fri','Sat'].map(d=>`<div class="dow">${d}</div>`).join('')+'<div class="day off"></div>'.repeat(first);
  for(let d=1;d<=n;d++){const k=iso(new Date(y,m,d)),ev=tasks.filter(t=>t.deadline===k);h+=`<div class="day" data-date="${k}"><span>${d}</span>${ev.map(t=>`<button class="chip cat-${t.category}" data-id="${t.id}" title="${esc(t.title)}">${esc(t.title)}</button>`).join('')}<div class="dots">${ev.map(t=>`<i class="cat-${t.category}"></i>`).join('')}</div></div>`}
  const mt=sortByDue(tasks).filter(t=>t.deadline.startsWith(`${y}-${pad(m+1)}-`));
  cal.innerHTML=`<div class="calgrid">${h}</div><div class="agenda">${mt.map(t=>`<button class="ag" data-id="${t.id}"><i class="cat-${t.category}"></i><span><b>${esc(t.title)}</b><small>${fmtDate(t.deadline)} · ${esc(t.category)}</small></span></button>`).join('')||'<p class="mut small">No deadlines this month.</p>'}</div>`};
 const refresh=()=>load(cal,api.getTasks,t=>{tasks=t;draw()});
 el.onclick=e=>{const n=e.target.closest('[data-n]');
  if(n){const v=+n.dataset.n;if(v){m+=v;if(m>11){m=0;y++}if(m<0){m=11;y--}}else{y=t0.getFullYear();m=t0.getMonth()}draw();return}
  const c=e.target.closest('.chip,.ag');if(c)return taskModal(tasks.find(t=>t.id===c.dataset.id),refresh);
  const d=e.target.closest('.day[data-date]');if(d)taskModal(null,refresh,{deadline:d.dataset.date})};
 $('#add',el).onclick=()=>taskModal(null,refresh);
 refresh()}};
