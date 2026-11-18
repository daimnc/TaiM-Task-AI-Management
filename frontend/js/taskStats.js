// Pure task-date rules shared by the pages. No DOM. "Today" is always passed in as 'YYYY-MM-DD'.
// Overdue : deadline is before today and the task is not completed.
// Due soon: deadline is today or within the next 3 days, and the task is not completed.
import {isCompleted} from './ui.js';
export const DUE_SOON_DAYS=3;
const DATE=/^\d{4}-\d{2}-\d{2}$/;
const dayNo=s=>{const[y,m,d]=s.split('-').map(Number);return Date.UTC(y,m-1,d)/864e5};
const usable=t=>typeof t?.deadline==='string'&&DATE.test(t.deadline);
export const daysBetween=(fromIso,toIso)=>dayNo(toIso)-dayNo(fromIso);
export const isOverdue=(t,todayIso)=>usable(t)&&!isCompleted(t)&&t.deadline<todayIso;
export const isDueSoon=(t,todayIso)=>{if(!usable(t)||isCompleted(t))return false;const n=daysBetween(todayIso,t.deadline);return n>=0&&n<=DUE_SOON_DAYS};
export const taskCounts=(tasks,todayIso)=>({total:tasks.length,completed:tasks.filter(isCompleted).length,open:tasks.filter(t=>!isCompleted(t)).length,
 overdue:tasks.filter(t=>isOverdue(t,todayIso)).length,dueSoon:tasks.filter(t=>isDueSoon(t,todayIso)).length});
