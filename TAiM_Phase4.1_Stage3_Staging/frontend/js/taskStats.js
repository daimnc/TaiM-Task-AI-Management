// Pure task-date rules shared by the pages. No DOM. "Today" is always passed in as 'YYYY-MM-DD'.
// Overdue : deadline is before today and the task is not completed.
// Due soon: deadline is today or within the next 3 days, and the task is not completed.
import {isCompleted,pad,cleanName} from './ui.js';
export const DUE_SOON_DAYS=3;
const DATE=/^\d{4}-\d{2}-\d{2}$/;
const dayNo=s=>{const[y,m,d]=s.split('-').map(Number);return Date.UTC(y,m-1,d)/864e5};
const usable=t=>typeof t?.deadline==='string'&&DATE.test(t.deadline);
export const daysBetween=(fromIso,toIso)=>dayNo(toIso)-dayNo(fromIso);
export const isOverdue=(t,todayIso)=>usable(t)&&!isCompleted(t)&&t.deadline<todayIso;
export const isDueSoon=(t,todayIso)=>{if(!usable(t)||isCompleted(t))return false;const n=daysBetween(todayIso,t.deadline);return n>=0&&n<=DUE_SOON_DAYS};
export const taskCounts=(tasks,todayIso)=>({total:tasks.length,completed:tasks.filter(isCompleted).length,open:tasks.filter(t=>!isCompleted(t)).length,
 overdue:tasks.filter(t=>isOverdue(t,todayIso)).length,dueSoon:tasks.filter(t=>isDueSoon(t,todayIso)).length});
// Open tasks (overdue included) whose deadline is on or before today + `days`, soonest first. Used by Reminders with the leadDays setting.
export const dueWithin=(tasks,todayIso,days)=>tasks.filter(t=>usable(t)&&!isCompleted(t)&&daysBetween(todayIso,t.deadline)<=days).sort((a,b)=>a.deadline.localeCompare(b.deadline));
// ---- calendar (month is 0-11, like Date) ----
export const dateKey=(y,m,d)=>`${y}-${pad(m+1)}-${pad(d)}`;
export const monthInfo=(y,m)=>({first:new Date(Date.UTC(y,m,1)).getUTCDay(),days:new Date(Date.UTC(y,m+1,0)).getUTCDate()});
export const shiftMonth=(y,m,k)=>{const t=y*12+m+k;return{y:Math.floor(t/12),m:((t%12)+12)%12}};
export const tasksByDate=ts=>{const map=new Map();for(const t of ts)if(usable(t)){if(!map.has(t.deadline))map.set(t.deadline,[]);map.get(t.deadline).push(t)}return map};
export const monthTasks=(ts,y,m)=>ts.filter(t=>usable(t)&&t.deadline.startsWith(`${y}-${pad(m+1)}-`)).sort((a,b)=>a.deadline.localeCompare(b.deadline));
// ---- subtasks (Stage B). Records saved before subtasks existed have no `subtasks` field: they count as having none. ----
export const MAX_SUBTASKS=20; // same limit as the backend, counting the subtasks already saved
export const hasSubtasks=t=>Array.isArray(t?.subtasks)&&t.subtasks.length>0;
export const subtaskCounts=t=>{const s=Array.isArray(t?.subtasks)?t.subtasks:[];return{total:s.length,done:s.filter(x=>x?.status==='completed').length}};
export const subtaskCapacity=t=>Math.max(MAX_SUBTASKS-subtaskCounts(t).total,0);
// Planner steps ({title,minutes,dueDate}) -> request items for POST /tasks/{id}/subtasks. Only the picked indexes are sent,
// in order. dueDate is dropped on purpose: subtasks store no date. Minutes that are not a usable number are left out (server default).
export const planStepsToSubtasks=(steps,picked)=>(picked||[]).filter(i=>steps?.[i]).map(i=>{const s=steps[i],m=Math.round(+s.minutes),item={title:cleanName(s.title).slice(0,120)};
 if(Number.isFinite(m)&&m>=1)item.estimated_minutes=Math.min(m,Number.MAX_SAFE_INTEGER);return item});
// Adding subtasks to a completed parent reopens it (backend rule), so callers warn first.
export const addingReopens=t=>isCompleted(t);
// ---- Phase 4.1 Stage 2: AI planner suggestion editor (pure logic, no DOM) ----
// A "row" is one editable suggestion: {key, title, minutes (text as typed), selected}. Nothing here talks to the API.
export const MAX_STEP_TITLE=120; // same as the subtask title limit in the API
export const MAX_STEP_MINUTES=100000; // sanity cap for the editor; the template can legitimately produce thousands of minutes
export const MAX_EDITOR_ROWS=MAX_SUBTASKS;
let rowSeq=0;
export const newRow=(title='',minutes='30')=>({key:'r'+(++rowSeq),title:String(title??''),minutes:String(minutes??''),selected:true});
// Plan response -> rows. Dates from the plan are dropped (subtasks have no date field). Capped so a bad response cannot flood the page.
export const rowsFromPlan=subtasks=>(Array.isArray(subtasks)?subtasks:[]).filter(s=>s&&typeof s==='object').slice(0,MAX_EDITOR_ROWS).map(s=>newRow(s.title,Number.isFinite(+s.minutes)&&+s.minutes>=1?Math.round(+s.minutes):''));
export const moveRow=(rows,i,dir)=>{const out=[...rows],j=i+dir;if(!Number.isInteger(i)||i<0||i>=out.length||j<0||j>=out.length)return out;[out[i],out[j]]=[out[j],out[i]];return out};
export const removeRow=(rows,i)=>rows.filter((_,k)=>k!==i);
export const addRow=rows=>rows.length>=MAX_EDITOR_ROWS?[...rows]:[...rows,newRow()];
export const selectedIndexes=rows=>rows.map((r,i)=>r.selected?i:-1).filter(i=>i>=0);
// Only ticked rows are checked. errors is keyed by row key: {title?, minutes?}. ok is false when nothing is ticked or any ticked row is invalid.
export const validateRows=rows=>{const errors={};let count=0;
 for(const r of rows){if(!r.selected)continue;count++;const e={},t=cleanName(r.title),m=String(r.minutes??'').trim();
  if(!t)e.title='Enter a title.';else if(t.length>MAX_STEP_TITLE)e.title=`Use at most ${MAX_STEP_TITLE} characters.`;
  if(!/^\d+$/.test(m)||+m<1)e.minutes='Enter whole minutes, at least 1.';else if(+m>MAX_STEP_MINUTES)e.minutes=`Use at most ${MAX_STEP_MINUTES} minutes.`;
  if(e.title||e.minutes)errors[r.key]=e}
 return{errors,count,ok:count>0&&!Object.keys(errors).length}};
// Rows -> the {title,minutes} steps planStepsToSubtasks expects (call validateRows first; invalid minutes become NaN and are left out there).
export const rowsAsSteps=rows=>rows.map(r=>({title:r.title,minutes:/^\s*\d+\s*$/.test(String(r.minutes))?+r.minutes:NaN}));
// Only explicit, non-mock AI responses from known providers are labelled as AI.
export const planSource=r=>{
 if(r&&r.aiGenerated===true&&r.mock!==true&&r.source==='groq')return{kind:'groq',pill:'✦ AI-GENERATED PLAN · GROQ',heading:'Suggested by Groq. Review and edit each step before saving.'};
 if(r&&r.aiGenerated===true&&r.mock!==true&&r.source==='gemini')return{kind:'gemini',pill:'✦ AI-GENERATED PLAN · GOOGLE GEMINI',heading:'Suggested by Google Gemini. Review and edit each step before saving.'};
 if(r&&r.source==='mock-client')return{kind:'demo',pill:'✦ DEMO PLAN · NO AI MODEL USED',heading:'Browser demo template. No AI model was used.'};
 return{kind:'template',pill:'✦ TEMPLATE PLAN · NO AI MODEL USED',heading:'Built-in template. Not generated by an AI model.'}};
