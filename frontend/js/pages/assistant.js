import {api} from '../api/client.js';
import {$,esc,guard} from '../ui.js';

const starters = ['What should I work on first?','What deadlines should I prepare for?','Help me break a large assignment into steps.'];
const sourceName = source => ({Groq:'Groq AI',Gemini:'Google Gemini','rule-based':'Rule-based','mock-client':'Browser demo',ai:'AI provider'}[source] || 'TAiM Assistant');

export default {title:'AI Assistant',render(el) {
  let log = [{role:'assistant',text:'Hello! I can help you prioritize academic tasks, think through deadlines, and organize your workload.'}];
  el.innerHTML = `
    <div class="page-head"><div><h2>AI Assistant</h2><p class="sub">Ask for help with academic planning and prioritization.</p></div></div>
    <section class="card narrow assistant-card">
      <div class="assistant-top"><div><span class="pill violet">TAiM ACADEMIC ASSISTANT</span><p class="mut small">Read-only support. It does not create, edit, or complete tasks.</p></div><button class="btn" type="button" id="clear-chat">Clear chat</button></div>
      <div class="assistant-prompts" aria-label="Suggested questions">${starters.map((s,i)=>`<button type="button" class="btn assistant-prompt" data-prompt="${i}">${esc(s)}</button>`).join('')}</div>
      <div class="chat assistant-chat" id="chat" aria-live="polite"></div>
      <form class="chatbar assistant-chatbar" id="assistant-form">
        <input name="message" maxlength="1000" placeholder="Ask TAiM Assistant…" autocomplete="off" required aria-label="Message">
        <button class="btn primary" type="submit">Send</button>
      </form>
      <div class="assistant-meta"><span id="char-count" class="mut small">0 / 1000</span><span id="source" class="pill">Not sent</span></div>
      <label class="assistant-consent"><input type="checkbox" id="ai-consent"> <span><strong>Allow AI processing for this message</strong><small>Your current message, the six most recent conversation messages, and anonymized task context may be sent to Groq or Google Gemini. Task titles and subject names are replaced with labels before sending. Personal information you type into chat is not automatically anonymized. If unchecked, TAiM uses its rule-based response instead.</small></span></label>
      <p class="assistant-notice mut small" id="notice">Your message is processed by your TAiM backend. Nothing is saved as a conversation.</p>
    </section>`;
  const chat = $('#chat',el), form = $('#assistant-form',el), input = $('input[name="message"]',form);
  const consent = $('#ai-consent',el), sendButton = $('button[type="submit"]',form);
  const draw = () => {
    chat.innerHTML = log.map(item => `<div class="msg ${item.role==='user'?'me':''}">${esc(item.text)}</div>`).join('');
    chat.scrollTop = chat.scrollHeight;
  };
  const send = guard(async message => {
    const history = log.slice(-6).map(item => ({role:item.role,text:item.text}));
    log.push({role:'user',text:message});
    log.push({role:'assistant',text:'Thinking…'});
    draw(); sendButton.disabled = true;
    const useAI = consent.checked;
    consent.checked = false;
    try {
      const result = await api.askAssistant({message,history,aiConsent:useAI});
      if (!result || typeof result.reply !== 'string' || !result.reply.trim()) throw new Error('The assistant returned an invalid response.');
      log[log.length-1] = {role:'assistant',text:result.reply};
      $('#source',el).textContent = sourceName(result.source);
      $('#notice',el).textContent = result.notice || '';
    } catch (error) {
      log[log.length-1] = {role:'assistant',text:`Sorry, I could not process that message. ${error.message || 'Please try again.'}`};
      $('#source',el).textContent = error.status===429 ? 'Rate limited' : 'Request failed';
      $('#notice',el).textContent = error.status===429 ? 'The AI request limit has been reached. Please wait before trying again.' : 'No conversation was saved.';
    } finally {
      sendButton.disabled = false;
      draw();
    }
  },form);
  form.onsubmit = e => {
    e.preventDefault();
    const message = input.value.trim();
    if (!message || send.busy) return;
    input.value = ''; $('#char-count',el).textContent = '0 / 1000';
    send(message);
  };
  input.oninput = () => $('#char-count',el).textContent = `${input.value.length} / 1000`;
  $('#clear-chat',el).onclick = () => {
    if (send.busy) return;
    log = [{role:'assistant',text:'Chat cleared. What would you like help with?'}];
    $('#source',el).textContent = 'Not sent'; $('#notice',el).textContent = 'Your message is processed by your TAiM backend. Nothing is saved as a conversation.';
    consent.checked = false; draw();
  };
  el.querySelectorAll('[data-prompt]').forEach(button => button.onclick = () => {
    if (send.busy) return;
    input.value = starters[Number(button.dataset.prompt)];
    $('#char-count',el).textContent = `${input.value.length} / 1000`;
    input.focus();
  });
  draw();
}};
