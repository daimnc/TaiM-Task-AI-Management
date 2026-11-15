import {api} from '../api/client.js';
import {load,esc,topPick,dueText,daysUntil,isDone,sortByDue,empty,toast} from '../ui.js';
const LABELS={deadline:'Deadline reminders',dailySummary:'Daily study summary',progressCheckin:'Progress check-in',quietHours:'Quiet hours'};
export default{title:'Smart Reminders',render(el){const go=()=>load(el,()=>Promise.all([api.getTasks(),api.getReminderPrefs()]),([tasks,prefs])=>{
 const pick=topPick(tasks),up=sortByDue(tasks.filter(t=>!isDone(t)&&daysUntil(t.deadline)<=7));
 el.innerHTML=`<div class="page-head"><div><h2>Smart Reminders</h2><p class="sub">Contextual notifications based on urgency and recorded progress.</p></div></div>
 <div class="grid2 even"><div class="card ai"><span class="pill violet">✦ ADAPTIVE SUGGESTION · DEMO</span>${pick?`<h3>Your ${esc(pick.title)} needs attention</h3><p>${dueText(pick.deadline)}. Your recorded progress is ${pick.progress}%. Try a 25-minute session today.</p><a class="btn primary" href="#/planner?task=${pick.id}">Plan a session</a>`:'<h3>Nothing needs attention</h3>'}</div>
 <div class="card"><h3>Reminder Preferences</h3>${Object.keys(LABELS).map(k=>`<label class="chk">${LABELS[k]}<input type="checkbox" data-k="${k}"${prefs[k]?' checked':''}></label>`).join('')}</div></div>
 <div class="card" style="margin-top:18px"><h3>Upcoming Notifications</h3>${!prefs.deadline?empty('Deadline reminders are turned off.'):up.map(t=>`<div class="item"><b>${esc(t.title)} — ${dueText(t.deadline).toLowerCase()}</b><small>Suggested: work on it for 25 minutes.</small></div>`).join('')||empty('No upcoming notifications.')}</div>`;
 el.querySelectorAll('[data-k]').forEach(c=>c.onchange=async()=>{prefs[c.dataset.k]=c.checked;try{await api.saveReminderPrefs(prefs);toast('Preferences saved');go()}catch(e){c.checked=!c.checked;toast(e.message,'bad')}})});go()}};
