import {api} from '../api/client.js';
import {$,load,esc,empty,toast,modal,cleanName} from '../ui.js';
const nameModal=(title,value,save)=>modal(title,`<label>Subject name<input name="subject_name" required maxlength="100" value="${esc(value)}"></label>`,async fd=>{
 const name=cleanName(fd.get('subject_name'));if(!name)throw new Error('Subject name is required');await save(name)});
export default{title:'Subjects',render(el){
 el.innerHTML=`<div class="page-head"><div><h2>Subjects</h2><p class="sub">Group your tasks by course or subject. Every task belongs to one subject.</p></div><button class="btn primary" id="add">+ Add Subject</button></div><div class="card" id="list"></div>`;
 let subjects=[],counts={};const list=$('#list',el);
 const draw=()=>{list.innerHTML=subjects.length?subjects.map(s=>{const n=counts[s.subject_id]||0;
  return `<div class="item row"><div><b>${esc(s.subject_name)}</b><small>${n} task${n===1?'':'s'}</small></div><div class="acts"><button class="lnk" data-a="rename" data-id="${esc(s.subject_id)}">Rename</button><button class="lnk del" data-a="del" data-id="${esc(s.subject_id)}">Delete</button></div></div>`}).join(''):empty('No subjects yet. Click "+ Add Subject" to create your first one.')};
 const refresh=()=>load(list,()=>Promise.all([api.getSubjects(),api.getTasks()]),([s,t])=>{subjects=s;counts={};t.forEach(x=>counts[x.subject_id]=(counts[x.subject_id]||0)+1);draw()});
 $('#add',el).onclick=()=>nameModal('Add subject','',async name=>{await api.createSubject({subject_name:name});toast('Subject added');refresh()});
 list.onclick=async e=>{const b=e.target.closest('[data-a]');if(!b)return;const s=subjects.find(x=>x.subject_id===b.dataset.id);if(!s)return;
  if(b.dataset.a==='rename')nameModal('Rename subject',s.subject_name,async name=>{await api.renameSubject(s.subject_id,{subject_name:name});toast('Subject renamed');refresh()});
  if(b.dataset.a==='del'){const n=counts[s.subject_id]||0;
   if(n)return toast(`"${s.subject_name}" still has ${n} task${n===1?'':'s'}. Move or delete them first.`,'bad');
   if(!confirm(`Delete subject "${s.subject_name}"?`))return;
   try{await api.deleteSubject(s.subject_id);toast('Subject deleted');refresh()}catch(x){toast(x.message,'bad')}}};
 refresh()}};
