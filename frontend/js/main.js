import { auth } from './api/client.js';
import { CONFIG } from './config.js';
import { esc } from './ui.js';
import landing from './pages/landing.js'; import login from './pages/login.js'; import dashboard from './pages/dashboard.js'; import tasks from './pages/tasks.js'; import planner from './pages/planner.js';
import calendar from './pages/calendar.js'; import reminders from './pages/reminders.js'; import progress from './pages/progress.js'; import assistant from './pages/assistant.js'; import settings from './pages/settings.js';
const pages = { '': landing, login, dashboard, tasks, planner, calendar, reminders, progress, assistant, settings };
const NAV = [['dashboard', 'Dashboard', '▦'], ['tasks', 'My Tasks', '☷'], ['planner', 'AI Task Planner', '✦'], ['calendar', 'Academic Calendar', '◫'], ['reminders', 'Smart Reminders', '◷'], ['progress', 'My Progress', '▥'], ['assistant', 'AI Assistant', '✧'], ['settings', 'Settings', '⚙']];
const app = document.getElementById('app');
const setNav = o => { const sb = document.getElementById('sb'); if (!sb) return; sb.classList.toggle('open', o); document.getElementById('scrim')?.classList.toggle('on', o); document.body.classList.toggle('lock', o); document.getElementById('menu')?.setAttribute('aria-expanded', o) };
addEventListener('keydown', e => { if (e.key === 'Escape') setNav(false) });
matchMedia('(min-width:861px)').addEventListener('change', e => { if (e.matches) setNav(false) });
let cleanup = null;
function route() {
    cleanup?.(); cleanup = null; document.body.classList.remove('lock');
    const [path, qs = ''] = location.hash.replace(/^#\/?/, '').split('?'), page = Object.hasOwn(pages, path) && pages[path], q = new URLSearchParams(qs);
    if (!page) { location.hash = '#/'; return }
    if (!page.public && !auth.token) { location.hash = '#/login'; return }
    document.title = `${page.title} · TAiM`; window.scrollTo(0, 0);
    if (page.public) { app.innerHTML = ''; const r = page.render(app, q); if (typeof r === 'function') cleanup = r; return }
    app.innerHTML = `<div class="shell"><div class="scrim" id="scrim"></div><aside class="sidebar" id="sb" aria-label="Sidebar"><button class="sb-close" id="sbx" aria-label="Close menu">✕</button><div class="logo"><span>T</span>TAiM</div>${NAV.map(([p, l, i]) => `<a href="#/${p}" class="${p === path ? 'on' : ''}">${i} ${l}</a>`).join('')}<button class="out" id="out">⎋ Log out</button></aside>
 <div class="main"><header class="top"><button class="menu" id="menu" aria-label="Open menu" aria-expanded="false" aria-controls="sb">☰</button><div><small>TAiM WORKSPACE</small><h1>${page.title}</h1></div><span class="who"><span class="avatar">${esc((auth.user?.name || 'S')[0].toUpperCase())}</span><span class="mut">${esc(auth.user?.name || 'Student')} account</span></span></header><main id="view"></main></div></div>`;
    document.getElementById('menu').onclick = () => setNav(true);
    document.getElementById('sbx').onclick = document.getElementById('scrim').onclick = () => setNav(false);
    document.getElementById('sb').querySelectorAll('a').forEach(a => a.onclick = () => setNav(false));
    document.getElementById('out').onclick = async () => { try { await auth.signOut() } catch { } location.hash = '#/' };
    page.render(document.getElementById('view'), q);
}
addEventListener('hashchange', route);
// Mock mode starts immediately (unchanged). Real mode waits until Firebase has restored the session, so a refresh never bounces a signed-in user to /login.
const hashPath = () => location.hash.replace(/^#\/?/, '').split('?')[0];
if (CONFIG.USE_MOCK) route();
else {
    app.innerHTML = '<div class="state">Loading…</div>'; auth.ready().then(() => {
        route();
        let uid = auth.user?.id ?? null;
        // Fires for sign-in and sign-out in this tab and in other tabs. Acts only when the signed-in user actually changes.
        auth.onChange(u => {
            const next = u?.uid ?? null; if (next === uid) return; uid = next;
            // Signed out: the route guard sends protected pages to /login. /login is public, so this cannot loop.
            if (!next) return route();
            // Signed in. On /login: if this tab's own login/register/Google call is running (login.js disables #go meanwhile) it navigates itself when done, so do not interrupt it; otherwise another tab signed in, so open the workspace.
            if (hashPath() === 'login') { if (!document.querySelector('#go')?.disabled) location.hash = '#/dashboard'; return }
            route();
        });
    })
}