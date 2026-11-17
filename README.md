# TAiM — Task AI Management

A web app that helps college students organise academic deadlines and break large tasks into smaller steps.
Group 2, BSCS-3A, APPDEV final project.

- **Frontend:** dependency-free ES-module app (vanilla JS + CSS, hash routing, no build step) in `frontend/`.
- **Backend:** Python Flask API in `backend/`, reading and writing Cloud Firestore through the Firebase Admin SDK.
- **Authentication:** Firebase Authentication (email/password and Google), handled in the browser. The backend verifies every request's Firebase ID token.
- **"AI" features:** deterministic, rule-based fallbacks only. **No AI model is connected** (see *AI features* below).

## Architecture

    Browser (frontend, localhost:5500)
       │  Firebase Auth SDK  ──────────►  Firebase Authentication
       │  fetch + "Authorization: Bearer <ID token>"
       ▼
    Flask API (backend, 127.0.0.1:5000, /api/*)
       │  verifies the ID token (the student's UID comes ONLY from the verified token)
       ▼
    Cloud Firestore (Admin SDK; direct browser access is denied by backend/firestore.rules)

The browser never talks to Firestore. All data access goes through the backend. In the frontend, all data access goes through `js/api/client.js`; pages never call `fetch` directly.

## Run

### Backend

Run from `backend/`:

    python -m venv .venv
    # Windows: .venv\Scripts\activate    macOS/Linux: source .venv/bin/activate
    pip install -r requirements.txt
    python app.py

It listens on http://127.0.0.1:5000. Health check: `GET /api/health` (no token needed).

Configuration is read from `backend/.env` (never commit it):

| Variable | Purpose | Default |
|---|---|---|
| `FIREBASE_PROJECT_ID` | Firebase project to use | none (Firestore is not connected without it) |
| `CORS_ORIGINS` | Comma-separated browser origins allowed to call the API | `http://localhost:5500` |
| `TAIM_UTC_OFFSET_HOURS` | Timezone used for "today" on the server | `8` (Philippines) |
| `FLASK_DEBUG` | `true` enables Flask debug mode | `false` |
| `SECRET_KEY` | Flask secret key | development-only placeholder |

The Admin SDK service-account key must be placed at `backend/keys/serviceAccount.json`. It is git-ignored; never commit it or put it in the frontend.
Without `FIREBASE_PROJECT_ID` or the key file the server still starts, but protected routes answer `503` (after the token check).
`127.0.0.1:5500` is **not** an allowed origin by default; open the frontend at `http://localhost:5500` or add the origin to `CORS_ORIGINS`.

### Frontend

Run from the project root:

    python -m http.server 5500 --directory frontend

Open http://localhost:5500. No build step or npm installation is needed.

Firebase web-app settings live in `frontend/js/firebase.js` (a public web config, safe in the frontend). For sign-in to work, `localhost` must be listed under Firebase Console → Authentication → Settings → Authorized domains.

### Real mode and mock mode

Controlled by `USE_MOCK` in `frontend/js/config.js`:

| | Real mode (`USE_MOCK = false`, current setting) | Mock mode (`USE_MOCK = true`) |
|---|---|---|
| Sign-in | Firebase Auth (email/password, Google) | Any email with a 6+ character password |
| Data | Flask API → Firestore | Browser `localStorage` key `taim_mock_db` |
| Backend needed | Yes | No |
| "Today" | The real date (`MOCK_TODAY` is `null`) | Pinned to `2026-11-01` so seeded demo data lines up |

`MOCK_TODAY` is derived from `USE_MOCK` in `config.js`; change only `USE_MOCK`. Mock mode and its files (`js/api/mockData.js` and the mock section of `js/api/client.js`) are kept for demos and development.
In mock mode some figures on the Progress page are static sample data from `mockData.js`, not computed from tasks.

## Tests

Backend tests use a fake Firestore and fake token verification, so they need no Firebase account or network. From `backend/`:

    python -m unittest tests.test_api -v          # no extra packages
    python -m pytest tests/test_api.py -v         # needs requirements-dev.txt

`tests/test_api.py` contains 44 tests covering authentication, task/settings/reminder-preference CRUD and validation, per-student isolation, progress statistics, and the AI fallback endpoints. There are no automated frontend tests yet.

## Current data layout (as implemented today)

Every path starts with the verified Firebase UID:

    users/{uid}/tasks/{taskId}            title, course, category, deadline, priority, progress,
                                          completedOn (server-set when progress reaches 100), createdAt, updatedAt
    users/{uid}/preferences/settings      name, program, leadDays, sessionMinutes, weeklySummary
    users/{uid}/preferences/reminders     deadline, dailySummary, progressCheckin, quietHours

This layout is **being replaced** (see *Planned: data-model migration*). Until that work is finished and verified, this is the layout in use.

## API (as implemented today)

Base URL `http://localhost:5000/api`. Every route except `/health` needs `Authorization: Bearer <Firebase ID token>`.
Errors are JSON: `{"detail": "<text>"}`, with an `errors` object (field → message) on validation failures (`422`). Other statuses: `401` missing/invalid token, `404` not found (including another student's task), `413` body over 64 KB, `503` Firebase not connected.

| Method & path | Body → Response |
|---|---|
| GET `/tasks` · POST `/tasks` | → `Task[]` · `Task` fields (no id) → `Task` (201) |
| PATCH `/tasks/{id}` · DELETE `/tasks/{id}` | partial `Task` → `Task` · 204 |
| GET / PUT `/settings` | `{name, program, leadDays, sessionMinutes, weeklySummary}` (PUT accepts any subset) |
| GET / PUT `/reminders/preferences` | `{deadline, dailySummary, progressCheckin, quietHours}` (booleans) |
| GET `/progress` | → `{completionRate, onTimeRate, completed, overdue, weeklyChange, weeklyProductivity[7], weeklyCompletion[4], insight, insightSource}` |
| POST `/ai/plan` | `{title, requirements, deadline, hoursPerDay}` → `{subtasks:[{title, dueDate, minutes}], mock, aiGenerated, source, notice}` |
| POST `/ai/chat` | `{message}` → `{reply, mock, aiGenerated, source, notice}` |

`Task`: `{id, title, course, category: Assignment|Research|Project|Examination, deadline: "YYYY-MM-DD", priority: High|Medium|Low, progress: 0-100}`. Progress 100 means done.

Sign-in and registration are done by the Firebase SDK in the browser; there are no `/auth/*` backend routes. (`/auth/login` and `/auth/register` exist only inside the mock client.)

`/progress` is computed from the student's stored tasks only; nothing is invented. On-time rate and the weekly series use `completedOn`, so tasks finished before that field existed are left out of those figures.

## AI features

`/ai/plan` and `/ai/chat` are **deterministic fallbacks, not AI**. Responses carry `mock: true`, `aiGenerated: false`, `source: "deterministic-fallback"` and a `notice`, and the UI says so.

- **Planner:** a fixed five-step template spread evenly before the deadline. The title and requirements are not analysed.
- **Assistant:** keyword rules over the student's own tasks.
- **Progress insight:** a rule-based summary, labelled as such.

To add a real provider later, replace `build_plan` / `build_reply` in `backend/fallback_ai.py` and keep the response shape. No paid service is required or assumed.

## Known limitations (current code)

- No subjects page (a task has only a free-text `course`), no real subtasks (the planner saves each accepted step as a separate task), no Pomodoro timer, no PDF/module decomposer, no separate Projects page.
- Reminders are preferences only; nothing is delivered. Procrastination analysis and weekly summaries are not implemented.
- In real mode the frontend's "today" is the browser's local date, while the backend uses `TAIM_UTC_OFFSET_HOURS`. They agree for students in the same timezone as the server setting.

## Planned: data-model migration (not implemented yet)

Nothing in this section exists in the code today. It records the agreed design and its limits.

**Target layout:** top-level collections `students`, `subjects`, `tasks` (with `subtasks`), later `progress_logs`, `reminders` (with `responses`) and `weekly_summaries` (with `insights`). `password_hash` is intentionally omitted because Firebase Authentication holds credentials. `program` and `weeklySummary` are dropped; `leadDays`, `sessionMinutes` and reminder preferences are kept.

**Rules the migration must follow**

- The student identity always comes from the verified ID token, never from a browser-supplied value. Every read, update and delete of `students`, `subjects` and `tasks` checks ownership. Subtasks are reachable only through an owned parent task.
- Dry-run is the default; data is written only with an explicit `--apply`.
- Students are found with `collection("users").list_documents()`, so students whose parent document is missing are included.
- Existing target documents are never overwritten, and legacy documents are never modified or deleted. Legacy data stays untouched.
- Subject IDs are deterministic (derived from the student and the normalised subject name), so re-running always maps the same student's same subject to the same ID.
- A student whose records are invalid, conflicting or would migrate only partially is flagged and not written; the run never reports success in that case. Re-runs are idempotent, and writes respect Firestore's 500-write batch limit.
- A subject cannot be deleted while tasks still reference it; the API returns a clear validation error until those tasks are reassigned or deleted.
- The app is **not** switched to the new collections until migration and verification are complete. Planned gate: the new data routes stay disabled by default (`TAIM_ENABLE_V2`, off) until a clean dry-run, `--apply`, second dry-run and manual checklist have all passed. Stop the old backend writing legacy data after the final dry-run.

**Rollback and recovery limits**

- **Before the new layout is enabled:** rollback is complete. Legacy data is untouched, so reverting the code restores the old behaviour.
- **After it is enabled:** new writes (tasks, subjects, subtasks, settings, reminder preferences) exist only in the new collections. Reverting the code would hide them from the old app. They are not deleted, but there is no reverse migration, and re-running the migration never overwrites or merges newer data back into legacy.
- No export or backup tooling is provided (Firestore managed export requires a paid plan). A reverse script would be a separate, explicitly approved task.

## Frontend structure

`index.html` · `css/{styles,landing}.css` · `js/{main,config,ui,firebase}.js` · `js/api/{client,mockData,firebaseAuth}.js` · `js/components/{taskModal,publicNav,glow,reveal}.js` · `js/pages/*.js` (landing, login, dashboard, tasks, planner, calendar, reminders, progress, assistant, settings).

`js/pages/landing.js` composes `components/publicNav.js` (floating navbar) and `components/glow.js` (canvas hero glow, reduced-motion aware). Styles: `css/landing.css`. Pages may return a cleanup function from `render()`; `main.js` calls it on navigation.
