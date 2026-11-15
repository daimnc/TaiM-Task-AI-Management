import {api,auth} from '../api/client.js';
import {$} from '../ui.js';
export default{title:'Sign in',public:true,render(el,q){
 let mode=q.get('mode')==='signup'?'signup':'login';
 const draw=()=>{el.innerHTML=`<div class="authwrap"><form class="card auth" id="f"><a class="logo dark" href="#/"><span style="color:#fff">T</span>TAiM</a>
 <div class="tabs"><button type="button" data-m="login" class="${mode==='login'?'on':''}">Log in</button><button type="button" data-m="signup" class="${mode==='signup'?'on':''}">Sign up</button></div>
 ${mode==='signup'?'<label>Full name<input name="name" required></label><label>Program<input name="program" placeholder="e.g. BS Computer Science"></label>':''}
 <label>Email<input type="email" name="email" required></label><label>Password<input type="password" name="password" required minlength="6"></label>
 ${auth.token?'<p class="mut small" style="margin:4px 0 12px">You are already signed in. <a href="#/dashboard" style="color:var(--pur);font-weight:600">Open workspace</a></p>':''}<p class="err" id="e" hidden></p><button class="btn primary big" id="go">${mode==='signup'?'Create account':'Log in'}</button>
 <p class="mut small" style="margin-top:10px">Demo mode: any email with a 6+ character password works. No real authentication yet.</p></form></div>`;
  el.querySelectorAll('[data-m]').forEach(b=>b.onclick=()=>{mode=b.dataset.m;draw()});
  $('#f',el).onsubmit=async e=>{e.preventDefault();const go=$('#go',el),err=$('#e',el);go.disabled=true;err.hidden=true;
   try{const r=await(mode==='signup'?api.register:api.login)(Object.fromEntries(new FormData(e.target)));auth.set(r.token,r.user);location.hash='#/dashboard'}
   catch(x){err.textContent=x.message;err.hidden=false;go.disabled=false}}};
 draw()}};
