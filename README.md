# TAiM Frontend
Dependency-free ES-module app (vanilla JS + CSS, hash routing). No build step.
### Run

Run from the project root:

    python -m http.server 5500 --directory frontend

Open http://localhost:5500

No build step or npm installation is required.

The frontend currently uses mock authentication and data. Any email with a password of at least 6 characters can log in. Data persists in localStorage under `taim_mock_db`.
## Structure
index.html · css/styles.css · js/{main,config,ui}.js · js/api/{client,mockData}.js · js/components/taskModal.js · js/pages/*.js (10 pages)
## Backend Integration

The planned backend uses Python Flask.

API base URL:

    http://localhost:5000/api

Current frontend configuration in `js/config.js`:

- `USE_MOCK:true` — use mock data.
- `API_BASE` — backend API address.

Keep mock functionality until the Flask API is implemented, integrated, and tested. Do not remove mock files during initial integration.
## Current Mock API Contract (Provisional)
| Method & path | Body → Response |
|---|---|
| POST /auth/login | `{email,password}` → `{token,user}` |
| POST /auth/register | `{name,email,password,program}` → `{token,user}` |
| GET /tasks · POST /tasks | → `Task[]` · `Task` (no id) → `Task` |
| PATCH /tasks/{id} · DELETE /tasks/{id} | partial `Task` → `Task` · 204 |
| GET /progress | → `{completionRate,onTimeRate,completed,overdue,weeklyChange,weeklyProductivity[7],weeklyCompletion[4],insight}` |
| GET/PUT /settings | `{name,program,leadDays,sessionMinutes,weeklySummary}` |
| GET/PUT /reminders/preferences | `{deadline,dailySummary,progressCheckin,quietHours}` (booleans) |
| POST /ai/plan | `{title,requirements,deadline,hoursPerDay}` → `{subtasks:[{title,dueDate,minutes}]}` |
| POST /ai/chat | `{message}` → `{reply}` |

`Task`: `{id,title,course,category: Assignment|Research|Project|Examination, deadline:"YYYY-MM-DD", priority: High|Medium|Low, progress:0-100}` (progress 100 = done). `user`: `{id,name,email,program}`.
Mock AI responses include `mock:true` to identify simulated responses. Real AI integration and corresponding UI changes will be handled separately.

## Landing page
`js/pages/landing.js` composes `components/publicNav.js` (floating navbar) and `components/glow.js` (canvas hero glow, reduced-motion aware). Styles: `css/landing.css`. Pages may return a cleanup function from `render()`; `main.js` calls it on navigation.
