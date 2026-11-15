// Halden-style letter-by-letter reveal: each character goes invisible+blurred → ghost → accent → final colour.
// Honors prefers-reduced-motion (text is left untouched). Original text stays accessible via aria-label.
const clamp=(v,a=0,b=1)=>Math.min(b,Math.max(a,v)),mixc=(a,b,t)=>a.map((v,i)=>Math.round(v+(b[i]-v)*t));
export function splitChars(el){
 const chars=[],label=el.innerHTML.replace(/<br\s*\/?>/g,' ').replace(/<[^>]+>/g,'').replace(/\s+/g,' ').trim();
 const walk=(src,dst,hl)=>src.childNodes.forEach(n=>{
  if(n.nodeType===3)n.textContent.split(/(\s+)/).forEach(tok=>{
   if(!tok)return;if(/^\s+$/.test(tok))return dst.append(document.createTextNode(tok));
   const w=document.createElement('span');w.className='lw';
   [...tok].forEach(ch=>{const s=document.createElement('span');s.className='lc';s.textContent=ch;if(hl)s.dataset.hl='1';w.append(s);chars.push(s)});dst.append(w)});
  else if(n.nodeName==='BR')dst.append(document.createElement('br'));
  else{const c=n.cloneNode(false);dst.append(c);walk(n,c,hl||n.classList.contains('hl'))}});
 const root=document.createElement('span');root.setAttribute('aria-hidden','true');walk(el,root,false);
 el.setAttribute('aria-label',label);el.replaceChildren(root);return chars;
}
export function revealOnLoad(el,{duration=1250,delay=0,spread=.35,ghost=[255,255,255],accent=[63,124,255],final=[28,32,64],hlFinal=[91,79,224]}={}){
 if(matchMedia('(prefers-reduced-motion: reduce)').matches)return()=>{};
 const chars=splitChars(el),n=chars.length;let raf=0;el.classList.add('revealing');
 const paint=p=>chars.forEach((c,i)=>{
  const t=clamp((p*(1+spread)-i/n)/spread);let o=1,col,blur=0;
  if(t<=.35){const k=t/.35;o=k;col=ghost;blur=8-6.5*k}
  else if(t<=.7){const k=(t-.35)/.35;col=mixc(ghost,accent,k);blur=1.5*(1-k)}
  else col=mixc(accent,c.dataset.hl?hlFinal:final,(t-.7)/.3);
  c.style.opacity=o;c.style.color=`rgb(${col})`;c.style.filter=blur>.05?`blur(${blur}px)`:'none'});
 const T0=performance.now()+delay;paint(0);
 const step=now=>{const p=clamp((now-T0)/duration);paint(p);
  if(p<1)raf=requestAnimationFrame(step);else{chars.forEach(c=>c.removeAttribute('style'));el.classList.remove('revealing')}};
 raf=requestAnimationFrame(step);return()=>cancelAnimationFrame(raf);
}
