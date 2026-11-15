// Halden-inspired atmospheric bowl glow in a tiny 96x60 canvas that CSS stretches (bilinear = soft).
// Fixed behind the page: intro bloom, idle drift, and a scroll-driven deepen/widen (Halden's fitted keyframes).
// Pauses when `watch` (the hero) is off-screen or the tab is hidden; ~30fps; static under prefers-reduced-motion.
const W=96,H=60,ss=t=>{t=Math.min(1,Math.max(0,t));return t*t*(3-2*t)},mix=(a,b,t)=>a.map((v,i)=>v+(b[i]-v)*t);
const START=[-.3,.3,.1];
// [scroll q = scrollY/innerHeight, tip, half, soft]; q=0 is the TAiM resting bowl
const KEYS=[[0,.45,.36,.22],[.08,.65,.38,.22],[.18,.80,.38,.22],[.40,.95,.38,.19],[.66,1.05,.46,.16],[.87,1.05,.66,.13],[1.15,1.10,.90,.10],[1.43,1.30,1.60,.10],[1.80,2.40,3.00,.10]];
const target=q=>{for(let i=1;i<KEYS.length;i++)if(q<=KEYS[i][0]){const a=KEYS[i-1],b=KEYS[i],t=(q-a[0])/(b[0]-a[0]);return[1,2,3].map(k=>a[k]+(b[k]-a[k])*t)}return KEYS.at(-1).slice(1)};
export function startGlow(canvas,{core=[150,200,245],rim=[220,216,255],out=[244,245,251],watch=canvas}={}){
 const x=canvas.getContext('2d'),im=x.createImageData(W,H),reduce=matchMedia('(prefers-reduced-motion: reduce)');
 let raf=0,visible=true,last=0,intro=true,cur=START.slice();const T0=performance.now();
 function paint(now,[tip,half,soft]){
  if(!reduce.matches){tip+=Math.sin(now*.00033+1.3)*.02;half+=Math.sin(now*.0005)*.015}
  const asp=(canvas.clientWidth||innerWidth)/(canvas.clientHeight||innerHeight),P=[];
  for(let i=0;i<=48;i++){const yy=-.3+(tip+.3)*i/48;P.push([half*asp*Math.pow(Math.max(0,1-yy/tip),.72),yy])}
  for(let j=0;j<H;j++)for(let i=0;i<W;i++){
   const px=Math.abs((i+.5)/W-.5)*asp,py=(j+.5)/H;let d=1e9;
   for(let k=0;k<48;k++){const[ax,ay]=P[k],[bx,by]=P[k+1],dx=bx-ax,dy=by-ay,l=dx*dx+dy*dy||1e-9,u=Math.min(1,Math.max(0,((px-ax)*dx+(py-ay)*dy)/l));d=Math.min(d,Math.hypot(px-ax-u*dx,py-ay-u*dy))}
   const inside=py<tip&&px<half*asp*Math.pow(1-py/tip,.72),g=1-ss(((inside?-d:d)-.25+soft)/(2*soft));
   const c=g<.38?mix(out,rim,ss(g/.38)):mix(rim,core,ss((g-.38)/.62)),o=(j*W+i)*4;
   im.data[o]=c[0];im.data[o+1]=c[1];im.data[o+2]=c[2];im.data[o+3]=255}
  x.putImageData(im,0,0)}
 const loop=now=>{raf=requestAnimationFrame(loop);if(!visible||document.hidden||now-last<33)return;last=now;
  const tg=target(Math.max(0,scrollY)/innerHeight);
  if(intro){const e=ss(((now-T0)/1000-.25)/1.05);cur=START.map((s,i)=>s+(tg[i]-s)*e);if(e>=1)intro=false}
  else cur=cur.map((c,i)=>c+(tg[i]-c)*.12);
  paint(now,cur)};
 const still=()=>paint(0,KEYS[0].slice(1));
 const io=new IntersectionObserver(([en])=>{visible=en.isIntersecting});io.observe(watch);
 if(reduce.matches){still();addEventListener('resize',still)}else raf=requestAnimationFrame(loop);
 return()=>{cancelAnimationFrame(raf);io.disconnect();removeEventListener('resize',still)};
}
