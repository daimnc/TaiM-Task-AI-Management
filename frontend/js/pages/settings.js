import {api,auth} from '../api/client.js';
import {$,load,esc,toast} from '../ui.js';
export default{title:'Settings',render(el){load(el,api.getSettings,s=>{
 el.innerHTML=`<div class="page-head"><div><h2>Settings</h2><p class="sub">Manage your planning preferences.</p></div></div>
 <form class="card narrow" id="f"><h3>Academic Profile</h3><div class="row"><label>Name<input name="name" required value="${esc(s.name)}"></label><label>Program<input name="program" value="${esc(s.program)}"></label></div>
 <h3 style="margin-top:10px">Planning Preferences</h3>
 <label class="chk">Default reminder lead time<select name="leadDays" style="width:auto">${[1,2,3,5,7].map(d=>`<option value="${d}"${d===s.leadDays?' selected':''}>${d} day${d>1?'s':''}</option>`).join('')}</select></label>
 <label class="chk">Preferred study session<select name="sessionMinutes" style="width:auto">${[25,45,60,90].map(d=>`<option value="${d}"${d===s.sessionMinutes?' selected':''}>${d} minutes</option>`).join('')}</select></label>
 <label class="chk">Weekly planning summary<input type="checkbox" name="weeklySummary"${s.weeklySummary?' checked':''}></label>
 <br><button class="btn primary" id="go">Save changes</button></form>`;
 $('#f',el).onsubmit=async e=>{e.preventDefault();const f=e.target,b=$('#go',el);b.disabled=true;
  try{const r=await api.saveSettings({name:f.name.value.trim(),program:f.program.value.trim(),leadDays:+f.leadDays.value,sessionMinutes:+f.sessionMinutes.value,weeklySummary:f.weeklySummary.checked});auth.set(auth.token,{...auth.user,name:r.name,program:r.program});toast('Settings saved')}
  catch(x){toast(x.message,'bad')}b.disabled=false}})}};
