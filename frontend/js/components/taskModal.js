import {api} from '../api/client.js';
import {modal,toast,esc,today,iso} from '../ui.js';
export const CATEGORIES=['Assignment','Research','Project','Examination'];
export const opts=(l,s)=>l.map(x=>`<option${String(x)===String(s)?' selected':''}>${x}</option>`).join('');
// Add (task=null) or edit a task. `done` runs after a successful save.
export function taskModal(task,done,defaults={}){
 const t={title:'',course:'',category:'Assignment',priority:'Medium',deadline:iso(today()),progress:0,...defaults,...task};
 modal(task?'Edit task':'Add task',`
 <label>Title<input name="title" required maxlength="120" value="${esc(t.title)}"></label>
 <label>Course<input name="course" value="${esc(t.course)}"></label>
 <div class="row"><label>Category<select name="category">${opts(CATEGORIES,t.category)}</select></label><label>Priority<select name="priority">${opts(['High','Medium','Low'],t.priority)}</select></label></div>
 <div class="row"><label>Deadline<input type="date" name="deadline" required value="${t.deadline}"></label><label><span>Progress: <output>${t.progress}</output>%</span><input type="range" name="progress" min="0" max="100" step="5" value="${t.progress}" oninput="this.parentNode.querySelector('output').value=this.value"></label></div>`,
 async fd=>{const b=Object.fromEntries(fd);b.progress=+b.progress;b.title=b.title.trim();if(!b.title)throw new Error('Title is required');
  task?await api.updateTask(task.id,b):await api.createTask(b);toast(task?'Task updated':'Task added');done()});
}
