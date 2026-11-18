import {CONFIG} from './config.js';
export const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
export const $=(s,r=document)=>r.querySelector(s);
export const pad=n=>String(n).padStart(2,'0');
export const iso=d=>`${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())}`;
export const today=()=>CONFIG.MOCK_TODAY?new Date(CONFIG.MOCK_TODAY+'T00:00:00'):new Date(new Date().toDateString());
export const addDays=k=>{const d=today();d.setDate(d.getDate()+k);return d};
export const daysUntil=s=>Math.round((new Date(s+'T00:00:00')-today())/864e5);
export const fmtDate=s=>new Date(s+'T00:00:00').toLocaleDateString('en-US',{month:'short',day:'numeric'});
export const dueText=s=>{const d=daysUntil(s);return d<0?'Overdue':d===0?'Due today':d===1?'Due tomorrow':`Due in ${d} days`};
export const isDone=t=>t.progress>=100;
export const sortByDue=ts=>[...ts].sort((a,b)=>a.deadline.localeCompare(b.deadline));
export const topPick=ts=>{const a=ts.filter(t=>!isDone(t));return a.filter(t=>t.priority==='High').sort((x,y)=>x.progress-y.progress)[0]||a[0]};
export const pill=p=>`<span class="pill ${p.toLowerCase()}">${esc(p)}</span>`;
export const empty=m=>`<div class="state">${esc(m)}</div>`;
export const bars=(v,l)=>{const m=Math.max(...v,1);return `<div class="bars">${v.map((x,i)=>`<div><i style="height:${Math.max(x/m*100,6)}%"></i><small>${l[i]}</small></div>`).join('')}</div>`};
export function toast(msg,type=''){const t=document.createElement('div');t.className='toast '+type;t.textContent=msg;document.body.append(t);setTimeout(()=>t.remove(),2800)}
// Loading / error(+retry) wrapper: render(data) is called on success.
export async function load(el,fn,render){el.innerHTML='<div class="state">Loading…</div>';try{render(await fn())}catch(e){el.innerHTML=`<div class="state err">${esc(e.message)}<br><br><button class="btn" data-r>Retry</button></div>`;$('[data-r]',el).onclick=()=>load(el,fn,render)}}
// Request lock: the wrapped function runs only when the previous call has finished (success or error). While it is
// pending, `area` (optional element) is dimmed and made inert so it cannot be clicked again. `run.busy` tells callers.
export function guard(fn,area){let busy=false;const run=async(...a)=>{if(busy)return;busy=true;if(area){area.classList?.add('locked');area.inert=true}
 try{return await fn(...a)}finally{busy=false;if(area){area.classList?.remove('locked');area.inert=false}}};
 Object.defineProperty(run,'busy',{get:()=>busy});return run}
export function modal(title,body,onSubmit){
 const o=document.createElement('div');o.className='overlay';
 o.innerHTML=`<form class="modal card"><h3>${esc(title)}</h3>${body}<p class="err" hidden></p><div class="row end"><button type="button" class="btn" data-x>Cancel</button><button class="btn primary">Save</button></div></form>`;
 document.body.append(o);const f=$('form',o),err=$('.err',o),close=()=>o.remove();
 $('[data-x]',o).onclick=close;o.onclick=e=>{if(e.target===o)close()};
 f.onsubmit=async e=>{e.preventDefault();const b=$('.primary',f);b.disabled=true;try{await onSubmit(new FormData(f));close()}catch(x){err.textContent=x.message;err.hidden=false;b.disabled=false}};
}
// ---- Phase 1 API contract helpers (used by the pages from Batch 3.2). Every helper above is unchanged. ----
// Values are the backend's lowercase enums; these maps only add the text shown to the student.
export const CATEGORY_LABELS={assignment:'Assignment',project:'Project',exam:'Exam',quiz:'Quiz',research:'Research',other:'Other'};
export const IMPORTANCE_LABELS={high:'High',medium:'Medium',low:'Low'};
export const categoryLabel=c=>Object.hasOwn(CATEGORY_LABELS,c)?CATEGORY_LABELS[c]:String(c??'');
export const importanceLabel=i=>Object.hasOwn(IMPORTANCE_LABELS,i)?IMPORTANCE_LABELS[i]:String(i??'');
// "Done" is the task's status. Never infer it from progress: a reopened task is in_progress at 100%.
export const isCompleted=t=>t?.status==='completed';
export const importancePill=i=>{const k=Object.hasOwn(IMPORTANCE_LABELS,i)?i:'medium';return `<span class="pill ${k}">${IMPORTANCE_LABELS[k]}</span>`};
// Same display rule the server's fallback uses: high-importance open task with the least progress, else the soonest.
export const topOpenTask=ts=>{const o=ts.filter(t=>!isCompleted(t)),hi=o.filter(t=>t.importance==='high').sort((a,b)=>a.progress_pct-b.progress_pct||a.deadline.localeCompare(b.deadline))[0];return hi||[...o].sort((a,b)=>a.deadline.localeCompare(b.deadline))[0]};
// ---- Phase 3.2 Stage 1 helpers (additive) ----
export const STATUS_LABELS={not_started:'Not started',in_progress:'In progress',completed:'Completed'};
export const statusLabel=s=>Object.hasOwn(STATUS_LABELS,s)?STATUS_LABELS[s]:String(s??'');
export const statusPill=s=>{const k=Object.hasOwn(STATUS_LABELS,s)?s:'not_started';return `<span class="pill st-${k}">${STATUS_LABELS[k]}</span>`};
// Name of the subject with this id, or a visible placeholder (never blank, never throws).
export const subjectName=(subjects,id)=>(subjects||[]).find(s=>s.subject_id===id)?.subject_name??'Unknown subject';
// Trim and collapse runs of spaces, the same clean-text rule the API uses for names.
export const cleanName=s=>String(s??'').split(/\s+/).filter(Boolean).join(' ');
// ---- Phase 3.2 Stage 2 helpers (additive) ----
export const catClass=c=>'cat-'+(Object.hasOwn(CATEGORY_LABELS,c)?c:'other');
// "Parent — step", cut so the result never exceeds the API's 120-character title limit.
export const joinTitle=(a,b,max=120)=>{a=cleanName(a);b=cleanName(b);const s=` — ${b}`;return a.length+s.length<=max?a+s:a.slice(0,Math.max(max-s.length-1,1)).trimEnd()+'…'+s};
// Runs create(item,index) one at a time and stops at the first failure, so a retry never duplicates what was already saved.
export async function addSequentially(items,create,onAdded){let ok=0;for(let i=0;i<items.length;i++){try{await create(items[i],i);ok++;onAdded?.(i)}catch(error){return{ok,failedAt:i,error}}}return{ok,failedAt:-1,error:null}}
