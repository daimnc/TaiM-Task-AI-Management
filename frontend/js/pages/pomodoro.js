import {api} from '../api/client.js';
import {$,esc,toast,categoryLabel} from '../ui.js';
import {createPomodoro,MODES,fmtClock,progressPct,finishMessage} from '../pomodoro.js';
// Timer state lives at module level, so a running session keeps counting while you visit other pages (single-page app).
// It is NOT saved: a browser refresh resets it, and no session history is stored.
const timer=createPomodoro(),views=new Set();let iv=null,taskId='',note='';
const paintAll=()=>views.forEach(f=>f());
const step=()=>{const r=timer.tick();if(r){note=finishMessage(r);toast(note)}if(timer.state.status!=='running'){clearInterval(iv);iv=null}paintAll()};
const ensureLoop=()=>{if(!iv)iv=setInterval(step,500)};
if(typeof document!=='undefined')document.addEventListener('visibilitychange',()=>{if(!document.hidden)step()}); // catch up at once when the tab becomes visible again
export default{title:'Pomodoro Timer',render(el,q){
 if(q.get('task'))taskId=q.get('task');
 el.innerHTML=`<div class="page-head"><div><h2>Pomodoro Timer</h2><p class="sub">Work in focused 25-minute sessions. Take a 5-minute break after each one, and a 15-minute break after every fourth.</p></div></div>
 <div class="card pomo"><div class="modes" id="modes"></div><div class="mlbl" id="mlbl"></div><div class="time" id="time">25:00</div><span class="prog"><i id="bar" style="width:0%"></i></span>
 <div class="ctl" id="ctl"></div><label>Working on (optional)<select id="task"><option value="">No specific task</option></select></label><p class="hint" id="note" hidden></p><p class="hint" id="count"></p></div>`;
 let sig='',titles={};const task=$('#task',el);
 const paint=()=>{if(!el.isConnected){views.delete(paint);return}
  const s=timer.state,run=s.status==='running',clock=fmtClock(s.remainingMs);
  $('#time',el).textContent=clock;$('#bar',el).style.width=progressPct(s)+'%';
  $('#mlbl',el).textContent=`${MODES[s.mode].label.toUpperCase()} · ${{idle:'READY',running:'RUNNING',paused:'PAUSED'}[s.status]}`;
  const nsig=s.mode+s.status;if(nsig!==sig){sig=nsig;
   $('#modes',el).innerHTML=Object.entries(MODES).map(([k,v])=>`<button type="button" data-mode="${k}" class="${k===s.mode?'on':''}"${run?' disabled':''}>${v.label} · ${v.minutes} min</button>`).join('');
   $('#ctl',el).innerHTML=(run?'<button class="btn primary big" data-act="pause">Pause</button>':s.status==='paused'?'<button class="btn primary big" data-act="start">Resume</button>':'<button class="btn primary big" data-act="start">Start</button>')+(s.status==='idle'?'':'<button class="btn big" data-act="reset">Reset</button>')}
  document.title=run?`${clock} · ${MODES[s.mode].label} · TAiM`:'Pomodoro Timer · TAiM';
  const n=$('#note',el);n.hidden=!note;n.textContent=note;
  $('#count',el).textContent=`Focus sessions completed in this browser tab: ${s.focusDone} (not saved; resets when the page is refreshed).`+(taskId&&titles[taskId]?` Current task: ${titles[taskId]}.`:'')};
 views.add(paint);
 el.onclick=e=>{const a=e.target.closest('[data-act]'),m=e.target.closest('[data-mode]');
  if(m){timer.setMode(m.dataset.mode);note='';sig='';paint();return}
  if(!a)return;
  if(a.dataset.act==='start'){note='';timer.start();ensureLoop()}else if(a.dataset.act==='pause')timer.pause();else if(a.dataset.act==='reset'){timer.reset();note=''}
  sig='';paint()};
 task.onchange=()=>{taskId=task.value;paint()};
 api.getTasks().then(ts=>{const open=ts.filter(t=>t.status!=='completed');titles=Object.fromEntries(open.map(t=>[t.task_id,t.title]));
  task.insertAdjacentHTML('beforeend',open.map(t=>`<option value="${esc(t.task_id)}">${esc(t.title)} (${esc(categoryLabel(t.category))})</option>`).join(''));
  if(!titles[taskId])taskId='';task.value=taskId;paint()}).catch(()=>{note='Could not load your tasks. The timer still works.';paint()});
 if(timer.state.status==='running')ensureLoop();
 paint()}};
