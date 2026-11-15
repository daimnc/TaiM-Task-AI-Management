import {api} from '../api/client.js';
import {$,esc} from '../ui.js';
export default{title:'AI Assistant',render(el){
 const log=[{who:'bot',text:'Hello! I can help organize your academic workload. Try asking: "What should I work on first?"'}];
 el.innerHTML=`<div class="page-head"><div><h2>AI Assistant</h2><p class="sub">Ask for help with academic planning and prioritization.</p></div></div>
 <div class="card narrow"><span class="pill violet">✦ TAIM ACADEMIC ASSISTANT · DEMO</span><div class="chat" id="chat"></div>
 <form class="chatbar" id="f"><input name="m" placeholder="Ask TAiM Assistant…" autocomplete="off" required><button class="btn primary">Send</button></form>
 <p class="mut small" style="margin-top:10px">Replies are mock, rule-based responses. No real AI is connected yet.</p></div>`;
 const chat=$('#chat',el),draw=()=>{chat.innerHTML=log.map(m=>`<div class="msg ${m.who==='me'?'me':''}">${esc(m.text)}</div>`).join('');chat.scrollTop=chat.scrollHeight};
 $('#f',el).onsubmit=async e=>{e.preventDefault();const f=e.target,text=f.m.value.trim();if(!text)return;f.m.value='';log.push({who:'me',text},{who:'bot',text:'…'});draw();f.querySelector('button').disabled=true;
  try{log[log.length-1].text=(await api.askAssistant({message:text})).reply}catch(x){log[log.length-1].text='Sorry, something went wrong: '+x.message}
  f.querySelector('button').disabled=false;draw()};
 draw()}};
