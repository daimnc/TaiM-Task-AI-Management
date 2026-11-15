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
export function modal(title,body,onSubmit){
 const o=document.createElement('div');o.className='overlay';
 o.innerHTML=`<form class="modal card"><h3>${esc(title)}</h3>${body}<p class="err" hidden></p><div class="row end"><button type="button" class="btn" data-x>Cancel</button><button class="btn primary">Save</button></div></form>`;
 document.body.append(o);const f=$('form',o),err=$('.err',o),close=()=>o.remove();
 $('[data-x]',o).onclick=close;o.onclick=e=>{if(e.target===o)close()};
 f.onsubmit=async e=>{e.preventDefault();const b=$('.primary',f);b.disabled=true;try{await onSubmit(new FormData(f));close()}catch(x){err.textContent=x.message;err.hidden=false;b.disabled=false}};
}
