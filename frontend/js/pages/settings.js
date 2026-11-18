import {api,auth} from '../api/client.js';
import {$,load,esc,toast,cleanName} from '../ui.js';
export default{title:'Settings',render(el){load(el,api.getSettings,s=>{
 el.innerHTML=`<div class="page-head"><div><h2>Settings</h2><p class="sub">Manage your planning preferences.</p></div></div>
 <form class="card narrow" id="f"><h3>Profile</h3><label>Name<input name="full_name" required maxlength="80" value="${esc(s.full_name)}"></label>
 <h3 style="margin-top:10px">Planning Preferences</h3>
 <label class="chk">Default reminder lead time<select name="leadDays" style="width:auto">${[1,2,3,5,7].map(d=>`<option value="${d}"${d===s.leadDays?' selected':''}>${d} day${d>1?'s':''}</option>`).join('')}</select></label>
 <small class="hint">Smart Reminders lists open tasks due within this many days.</small>
 <label class="chk">Preferred study session<select name="sessionMinutes" style="width:auto">${[25,45,60,90].map(d=>`<option value="${d}"${d===s.sessionMinutes?' selected':''}>${d} minutes</option>`).join('')}</select></label>
 <small class="hint">Used for suggested study times on the Dashboard and Reminders. The Pomodoro timer always uses 25/5/15-minute sessions.</small>
 <br><button class="btn primary" id="go">Save changes</button></form>`;
 $('#f',el).onsubmit=async e=>{e.preventDefault();const f=e.target,b=$('#go',el),name=cleanName(f.full_name.value);if(!name)return toast('Name is required','bad');b.disabled=true;
  try{const r=await api.saveSettings({full_name:name,leadDays:+f.leadDays.value,sessionMinutes:+f.sessionMinutes.value});
   auth.set(auth.token,{...auth.user,name:r.full_name});
   const av=document.querySelector('.who .avatar'),nm=document.querySelector('.who .mut');if(av)av.textContent=(r.full_name||'S')[0].toUpperCase();if(nm)nm.textContent=r.full_name+' account';
   toast('Settings saved')}
  catch(x){toast(x.message,'bad')}b.disabled=false}})}};
