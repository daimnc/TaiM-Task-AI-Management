// Pomodoro timer logic. Pure (no DOM). Time comes from a clock function, and the countdown is always computed from an end
// timestamp, so it stays correct when the browser tab is inactive or throttled.
export const MODES={focus:{label:'Focus',minutes:25},short:{label:'Short break',minutes:5},long:{label:'Long break',minutes:15}};
export const CYCLE=4; // a long break follows every 4th completed focus session
const full=mode=>MODES[mode].minutes*60000;
export function createPomodoro(now=()=>Date.now()){
 const s={mode:'focus',status:'idle',remainingMs:full('focus'),endAt:0,focusDone:0};
 const left=()=>s.status==='running'?Math.min(full(s.mode),Math.max(0,s.endAt-now())):s.remainingMs;
 return{
  get state(){return{mode:s.mode,status:s.status,remainingMs:left(),totalMs:full(s.mode),focusDone:s.focusDone}},
  start(){if(s.status==='running')return;if(s.remainingMs<=0)s.remainingMs=full(s.mode);s.endAt=now()+s.remainingMs;s.status='running'}, // also resumes a paused timer
  pause(){if(s.status!=='running')return;s.remainingMs=left();s.status='paused'},
  reset(){s.status='idle';s.remainingMs=full(s.mode)},
  setMode(mode){if(!Object.hasOwn(MODES,mode))return;s.mode=mode;s.status='idle';s.remainingMs=full(mode)},
  // Call regularly. Returns {finished,next} once when a running session ends, otherwise null.
  tick(){if(s.status!=='running'||left()>0)return null;const finished=s.mode;if(finished==='focus')s.focusDone++;
   const next=finished==='focus'?(s.focusDone%CYCLE===0?'long':'short'):'focus';s.mode=next;s.status='idle';s.remainingMs=full(next);return{finished,next}}
 };
}
export const fmtClock=ms=>{const t=Math.max(0,Math.ceil(ms/1000));return `${String(Math.floor(t/60)).padStart(2,'0')}:${String(t%60).padStart(2,'0')}`};
export const progressPct=st=>Math.round(Math.min(1,Math.max(0,1-st.remainingMs/st.totalMs))*100);
export const finishMessage=r=>r.finished==='focus'?`Focus session complete. Time for a ${r.next==='long'?'15-minute long':'5-minute short'} break.`:'Break over. Ready for the next focus session?';
