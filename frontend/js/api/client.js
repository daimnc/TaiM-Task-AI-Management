// ALL data access goes through `api`. UI never calls fetch or touches mock data directly.
import {CONFIG} from '../config.js';
import {seed} from './mockData.js';
import {iso,addDays,daysUntil,dueText,fmtDate,topPick,sortByDue} from '../ui.js';
export class ApiError extends Error{constructor(m,status){super(m);this.status=status}}
export const auth={
 get token(){try{return localStorage.getItem(CONFIG.TOKEN_KEY)}catch{return null}},
 get user(){try{return JSON.parse(localStorage.getItem(CONFIG.USER_KEY))}catch{return null}},
 set(token,user){localStorage.setItem(CONFIG.TOKEN_KEY,token);localStorage.setItem(CONFIG.USER_KEY,JSON.stringify(user))},
 clear(){localStorage.removeItem(CONFIG.TOKEN_KEY);localStorage.removeItem(CONFIG.USER_KEY)}};

async function real(method,path,body){
 const r=await fetch(CONFIG.API_BASE+path,{method,headers:{'Content-Type':'application/json',...(auth.token?{Authorization:'Bearer '+auth.token}:{})},body:body?JSON.stringify(body):undefined});
 if(!r.ok){if(r.status===401)auth.clear();throw new ApiError((await r.json().catch(()=>({}))).detail||r.statusText,r.status)}
 return r.status===204?null:r.json();
}

// ---- Mock backend (in-memory + localStorage). Remove once the Python API exists. ----
const KEY='taim_mock_db';let db;
const getDb=()=>{if(!db){try{db=JSON.parse(localStorage.getItem(KEY))}catch{}db||=structuredClone(seed)}return db};
const save=()=>{try{localStorage.setItem(KEY,JSON.stringify(db))}catch{}};
async function mock(method,path,body){
 await new Promise(r=>setTimeout(r,250));const d=getDb();
 const m=path.match(/^\/tasks(?:\/(\w+))?$/);
 if(m){const id=m[1];
  if(method==='GET')return d.tasks;
  if(method==='POST'){const t={...body,id:'t'+Date.now()+Math.random().toString(36).slice(2,5)};d.tasks.push(t);save();return t}
  const i=d.tasks.findIndex(t=>t.id===id);if(i<0)throw new ApiError('Task not found',404);
  if(method==='PATCH'){d.tasks[i]={...d.tasks[i],...body};save();return d.tasks[i]}
  if(method==='DELETE'){d.tasks.splice(i,1);save();return null}}
 switch(method+' '+path){
  case 'POST /auth/login':if(!body.email||(body.password||'').length<6)throw new ApiError('Invalid email or password (demo: 6+ characters).',401);return {token:'mock-token',user:{...d.user,email:body.email}};
  case 'POST /auth/register':if((body.password||'').length<6)throw new ApiError('Password must be at least 6 characters.',422);d.user={...d.user,name:body.name,email:body.email,program:body.program||''};d.settings={...d.settings,name:body.name,program:body.program||''};save();return {token:'mock-token',user:d.user};
  case 'GET /settings':return d.settings;
  case 'PUT /settings':d.settings={...d.settings,...body};save();return d.settings;
  case 'GET /reminders/preferences':return d.reminderPrefs;
  case 'PUT /reminders/preferences':d.reminderPrefs={...d.reminderPrefs,...body};save();return d.reminderPrefs;
  case 'GET /progress':{const h=d.history,act=d.tasks.filter(t=>t.progress<100);return {completionRate:h.completionRate,onTimeRate:h.onTimeRate,completed:h.completed+d.tasks.length-act.length,overdue:act.filter(t=>daysUntil(t.deadline)<0).length,weeklyChange:h.weeklyChange,weeklyProductivity:h.weeklyProductivity,weeklyCompletion:h.weeklyCompletion,insight:h.insight}}
  case 'POST /ai/plan':{const steps=['Define scope and outline','Gather and review sources','Draft main sections','Revise and add citations','Final proofread and submit'],n=steps.length,span=Math.max(daysUntil(body.deadline),1),mins=Math.round((+body.hoursPerDay||1)*30);
   return {mock:true,subtasks:steps.map((title,i)=>({title,dueDate:iso(addDays(Math.round(span*(i+1)/n))),minutes:mins}))}}
  case 'POST /ai/chat':{const q=(body.message||'').toLowerCase();let reply;const open=d.tasks.filter(t=>t.progress<100);
   if(/first|priorit|start/.test(q)){const t=topPick(d.tasks);reply=t?`Based on your recorded tasks, start with "${t.title}" (${t.progress}% done, ${dueText(t.deadline).toLowerCase()}). Try a 25-minute session.`:'You have no open tasks.'}
   else if(/due|deadline|soon/.test(q))reply=open.length?'Upcoming: '+sortByDue(open).slice(0,3).map(t=>`${t.title} (${fmtDate(t.deadline)})`).join('; ')+'.':'Nothing is due.';
   else reply='I can help with prioritizing tasks and deadlines. Try asking "What should I work on first?"';
   return {mock:true,reply}}}
 throw new ApiError('Not found: '+method+' '+path,404);
}
const req=(m,p,b)=>(CONFIG.USE_MOCK?mock:real)(m,p,b);
export const api={
 login:b=>req('POST','/auth/login',b),register:b=>req('POST','/auth/register',b),
 getTasks:()=>req('GET','/tasks'),createTask:b=>req('POST','/tasks',b),updateTask:(id,b)=>req('PATCH','/tasks/'+id,b),deleteTask:id=>req('DELETE','/tasks/'+id),
 getProgress:()=>req('GET','/progress'),
 getSettings:()=>req('GET','/settings'),saveSettings:b=>req('PUT','/settings',b),
 getReminderPrefs:()=>req('GET','/reminders/preferences'),saveReminderPrefs:b=>req('PUT','/reminders/preferences',b),
 planTask:b=>req('POST','/ai/plan',b),askAssistant:b=>req('POST','/ai/chat',b)};
