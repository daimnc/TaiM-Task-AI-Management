// Pure task-date rules shared by the pages. No DOM. "Today" is always passed in as 'YYYY-MM-DD'.
// Overdue : deadline is before today and the task is not completed.
// Due soon: deadline is today or within the next 3 days, and the task is not completed.
import {isCompleted,pad} from './ui.js';
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
