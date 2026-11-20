import {auth} from '../api/client.js';
import {startGlow} from '../components/glow.js';
import {revealOnLoad} from '../components/reveal.js';
import {publicNav,bindPublicNav} from '../components/publicNav.js';
const FEATURES=[['☷','Task management','Add, edit, filter and track assignments, exams, projects and research in one list.'],['✦','AI task planner','Turn a big task into smaller dated steps, then add them to your list. (Demo output for now.)'],['◫','Academic calendar','See every deadline in a monthly view and add tasks straight from a date.'],['◷','Smart reminders','Choose which reminders you get, with suggestions based on urgency and progress.'],['▥','Progress insights','Completion rates, weekly trends and on-time tracking from your recorded activity.'],['✧','AI assistant','Ask for academic planning help, prioritization, and deadline guidance.']];
const STEPS=[['Add your tasks','Enter assignments, exams, projects and research with deadlines and priorities.'],['Break them down','Describe a large task and let the AI planner suggest smaller, dated activities to review and add.'],['Stay on track','Use reminders, the calendar and your progress charts to keep ahead of deadlines.']];
const chev='<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="m9 18 6-6-6-6"/></svg>';
export default{title:'Academic task management',public:true,render(el){
 const authed=!!auth.token,go=['#/login?mode=signup','Get started'];
 el.innerHTML=`<div class="landing"><canvas id="glow" width="96" height="60" aria-hidden="true"></canvas>${publicNav(authed)}
 <header class="lhero" id="top">
  <div class="lhero-in"><span class="pill violet fade-up" style="--d:.1s">✦ Task A.I. Management</span>
   <h1>Meet <span class="hl">TAiM</span>,<br>your AI study planner</h1>
   <p class="fade-up" style="--d:1s">TAiM organizes assignments, exams, projects and research, breaks big tasks into manageable steps, and keeps every deadline in sight.</p>
   <div class="lcta-row fade-up" style="--d:1.15s"><a class="btn primary big arrow" href="${go[0]}">${go[1]}<i>${chev}</i></a><a class="btn big" href="#/login">I have an account</a>${authed?'<a class="btn big" href="#/dashboard">Open workspace</a>':''}</div></div>
  <div class="lcaps">${[['☷','Tasks'],['◫','Calendar'],['◷','Reminders'],['▥','Progress']].map(([i,t],k)=>`<div class="fade-up" style="--d:${(1.2+k*.07).toFixed(2)}s"><b>${i}</b> ${t}</div>`).join('')}</div></header>
 <section class="sec"><p class="lead">TAiM is a task manager built for student life. <span>It keeps your coursework in one place, plans the work with AI, and shows how you're really doing.</span></p></section>
 <section class="sec alt" id="features"><div class="sec-head"><h2>Everything your semester needs</h2><p>Six connected tools that share one task list, so nothing falls through the cracks.</p></div>
  <div class="fgrid">${FEATURES.map(([i,t,d])=>`<div class="card"><div class="fico">${i}</div><h3>${t}</h3><p class="mut">${d}</p></div>`).join('')}</div></section>
 <section class="sec" id="how"><div class="sec-head"><h2>How TAiM works</h2><p>From a pile of deadlines to a clear plan in three steps.</p></div>
  <div class="steps">${STEPS.map(([t,d],i)=>`<div class="card"><span class="num">${i+1}</span><h3>${t}</h3><p class="mut">${d}</p></div>`).join('')}</div></section>
 <section class="sec alt" id="ai"><div class="aisplit"><div><div class="sec-head" style="margin-bottom:20px"><h2>AI help that keeps you moving</h2><p>Ask the assistant what to tackle first, or let the planner split a big paper into steps you can finish one session at a time.</p></div>
   <ul class="ticks"><li>Prioritized suggestions based on deadlines and progress</li><li>Review every AI-generated step before it reaches your list</li><li>Suggestions only: you stay in control of your plan</li></ul></div>
  <div class="card"><span class="pill violet">✦ DEMO PREVIEW</span><div class="chat static"><div class="msg me">What should I work on first?</div><div class="msg">Based on your recorded tasks, start with "Research Paper: Artificial Intelligence" (20% done, due in 2 days). Try a 25-minute session.</div></div>
   <p class="mut small">The AI Assistant can use Groq or Google Gemini when you explicitly consent. Otherwise, it uses rule-based responses.</p></div></div></section>
 <section class="sec"><div class="hero lcta"><h2>Ready to organize your semester?</h2><p>Create an account and start planning in minutes.</p><a class="btn light big arrow" href="${go[0]}">${go[1]}<i>${chev}</i></a></div></section>
 <footer class="lfoot"><div class="logo"><span>T</span>TAiM</div><nav><a href="#/" data-scroll="features">Features</a><a href="#/" data-scroll="how">How it works</a>${authed?'<a href="#/dashboard">Workspace</a>':''}<a href="#/login">Log in</a><a href="#/login?mode=signup">Sign up</a></nav>
  <small>TAiM provides rule-based support when optional AI processing is not enabled or available.</small></footer></div>`;
 const root=el.querySelector('.landing'),stopGlow=startGlow(el.querySelector('#glow'),{watch:el.querySelector('#top')}),stopReveal=revealOnLoad(el.querySelector('.lhero h1'),{delay:150}),unbind=bindPublicNav(el);
 requestAnimationFrame(()=>root.classList.add('ready'));
 return()=>{stopGlow();stopReveal();unbind()};
}};
