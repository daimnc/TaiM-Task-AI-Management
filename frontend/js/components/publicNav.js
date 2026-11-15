// Floating pill navbar for public pages (adapted from the custom Convix navbar). Hash routing is preserved:
// section links use data-scroll (scrollIntoView) instead of #anchors, which would clash with the router.
const LINKS=[['features','Features'],['how','How it works'],['ai','AI assistance']];
const chev='<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="m9 18 6-6-6-6"/></svg>';
const ico=(c,d)=>`<svg class="${c}" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="${d}"/></svg>`;
export const publicNav=authed=>{
 const links=LINKS.map(([id,l])=>`<a href="#/" data-scroll="${id}">${l}</a>`).join('');
 return `<div class="pubnav"><nav class="pnav" aria-label="Main">
 <a class="logo dark" href="#/" data-scroll="top" aria-label="TAiM home"><span>T</span>TAiM</a>
 <div class="pnav-links">${links}</div>
 <div class="pnav-right">${authed?'<a class="pnav-login" href="#/dashboard">Workspace</a>':''}<a class="pnav-login" href="#/login">Log in</a>
  <a class="pnav-cta" href="#/login?mode=signup"><span>Get started</span><i>${chev}</i></a>
  <button class="pnav-burger" id="pburger" aria-label="Menu" aria-expanded="false">${ico('m','M4 12h16M4 6h16M4 18h16')}${ico('x','M18 6 6 18M6 6l12 12')}</button></div>
 <div class="pnav-panel" id="ppanel">${links}${authed?'<a href="#/dashboard">Open workspace</a>':''}<a href="#/login">Log in</a><a href="#/login?mode=signup">Sign up</a></div></nav></div>`};
export function bindPublicNav(root){
 const b=root.querySelector('#pburger'),p=root.querySelector('#ppanel'),reduce=matchMedia('(prefers-reduced-motion: reduce)');
 const set=o=>{p.classList.toggle('open',o);b.setAttribute('aria-expanded',o)};
 b.onclick=()=>set(!p.classList.contains('open'));
 root.addEventListener('click',e=>{const a=e.target.closest('[data-scroll]');if(!a)return;e.preventDefault();set(false);
  root.querySelector('#'+a.dataset.scroll)?.scrollIntoView({behavior:reduce.matches?'auto':'smooth',block:'start'})});
 const key=e=>{if(e.key==='Escape')set(false)},out=e=>{if(!e.target.closest('.pnav'))set(false)};
 document.addEventListener('keydown',key);document.addEventListener('click',out);
 return()=>{document.removeEventListener('keydown',key);document.removeEventListener('click',out)};
}
