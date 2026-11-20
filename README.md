# TAiM — Task AI Management

A web app that helps college students organise academic deadlines and break large tasks into smaller steps.
Group 2, BSCS-3A, APPDEV final project.

- **Frontend:** dependency-free ES-module app (vanilla JS + CSS, hash routing, no build step) in `frontend/`.
- **Backend:** Python Flask API in `backend/`, reading and writing Cloud Firestore through the Firebase Admin SDK.
- **Authentication:** Firebase Authentication (email/password and Google), handled in the browser. The backend verifies every request's Firebase ID token.
- **AI task planner:** Groq primary, Google Gemini secondary, with a deterministic local fallback when providers are unavailable.

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
| `GROQ_API_KEY` | Optional Groq API key (primary AI provider) | unset |
| `GROQ_MODEL` | Groq model ID, e.g. `openai/gpt-oss-120b` | unset |
| `GEMINI_API_KEY` | Optional Google Gemini API key (secondary provider) | unset |
| `GEMINI_MODEL` | Gemini model ID | unset |
| `AI_TOTAL_TIMEOUT_SECONDS` | Shared timeout budget for Groq and Gemini attempts | `12` |

Never commit `.env` or share its API keys. AI data disclosure is feature-specific; see the AI features section below.

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

`tests/test_api.py` contains 44 tests covering authentication, task/settings/reminder-preference CRUD and validation, per-student isolation, progress statistics, and the AI fallback endpoints. Frontend tests use Node.js built-in test runner; run from the project root with `node --test frontend/tests/*.test.mjs`.

## Current data layout

The V2 backend uses these top-level Firestore collections:

    students/{uid}                 profile, settings and reminder preferences
    subjects/{subject_id}          subject_id, student_id, subject_name
    tasks/{task_id}                task details, student_id, subject_id and optional embedded subtasks[]

Every student-owned record is associated with the verified Firebase UID. The backend checks ownership before returning or changing an individual subject or task. Legacy `users/{uid}/...` records are not read, written or deleted by the V2 store.

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
| POST `/ai/chat` | `{message, aiConsent?, history?}` → `{reply, mock, aiGenerated, source, notice}` |

`Task`: `{id, title, course, category: Assignment|Research|Project|Examination, deadline: "YYYY-MM-DD", priority: High|Medium|Low, progress: 0-100}`. Progress 100 means done.

Sign-in and registration are done by the Firebase SDK in the browser; there are no `/auth/*` backend routes. (`/auth/login` and `/auth/register` exist only inside the mock client.)

`/progress` is computed from the student's stored tasks only; nothing is invented. On-time rate and the weekly series use `completedOn`, so tasks finished before that field existed are left out of those figures.

## AI features

`POST /api/ai/plan` supports real AI suggestions when providers are configured and the student explicitly consents for that request.

- **Provider order:** Groq first, then Google Gemini if Groq fails. If neither provider produces valid output within the shared timeout, TAiM returns its deterministic five-step template.
- **Data disclosure:** only the task title, requirements, deadline and available hours per day are sent. No student ID, email, name, other tasks or stored records are sent to either provider.
- **Review before saving:** generated steps are suggestions only. The student can edit, reorder, remove and select steps; nothing is stored until the student explicitly adds selected steps to an existing task.
- **Provider safety:** API keys are sent in authorization headers, redirects are refused, model output is sanitized, and provider errors do not expose keys or response bodies. Groq reasoning output is not used.
- **Fallback:** the built-in deterministic template remains available without provider credentials, without consent, or when both providers fail.

`POST /api/ai/chat` supports optional Groq → Gemini responses when the student gives per-message consent. The request accepts a 1–1000 character `message`, optional boolean `aiConsent` (default `false`), and up to six previous `{role, text}` messages (`role` is `user` or `assistant`; no system/developer role is accepted). The backend loads only the authenticated student's task and subject records. Before provider calls, task titles and subject names in the current message and recent history are replaced with server-generated T/S labels; the provider receives only those labels plus bounded task facts and relative deadline days. The chat text typed by the student is not automatically scrubbed of personal information, which is disclosed in the consent prompt. Server-generated T/S aliases remain stable across task and subject edits for the lifetime of the backend process; this alias cache is in memory only and is not written to Firestore. Responses are read-only and are not saved as conversations. The Assistant has a separate limit of 5 provider attempts per minute and 30 per day per student; provider failover counts as one request, and a limit response is HTTP 429. Without consent or when providers fail, the existing rule-based response is used. Chat responses use `Cache-Control: no-store`. The Progress insight remains rule-based unless its own optional AI flow is used.

### Plan My Time (Phase 4.3)

The AI Task Planner includes a read-only **Plan my time** feature. TAiM's deterministic backend calculates the next task, daily allocations, capacity totals, and deadline-risk warnings from the student's open tasks and selected daily time/horizon. It does not create, edit, or save tasks, and it never schedules work after a task's deadline.

- **Scheduling rules:** overdue work is catch-up work, but capacity needed to meet cumulative on-time deadlines is reserved first. This avoids letting overdue work or an individually high-priority task consume capacity that another approaching deadline needs.
- **Estimates:** unfinished subtask estimates are used when available. Otherwise TAiM shows a clearly labelled provisional estimate based on the student's focus-session setting and task category.
- **Optional AI coaching:** only the wording of the qualitative coaching summary and tips may be generated by Groq, with Gemini as fallback. The deterministic schedule, order, minutes, and warnings remain unchanged.
- **Consent and data sent:** consent is requested separately for each request. The anonymous payload may include T/S labels, importance, task status, relative days until deadlines, remaining minutes, estimate source, risk/scheduled-today indicators, and aggregate counts/capacity figures/boolean workload flags. Task titles, subject names, student identity, account identifiers, and calendar dates are not sent. Without consent, the rule-based coaching is used and no provider is called.
- **Validation and fallback:** AI coaching is rejected if it includes unsupported numeric/date/time claims, unknown labels, or advice that changes or implies changing task order or deadlines. Invalid output, provider failure, or missing consent leaves the deterministic rule-based coaching in place.
- **Privacy and writes:** the planner reads only the signed-in student's data and performs no database writes.

## Known limitations (current code)

- No Pomodoro timer, PDF/module decomposer or separate Projects page. Tasks support embedded subtasks; the AI planner lets students review and edit suggestions before adding selected steps to an existing task.
- Reminders are preferences only; nothing is delivered. Procrastination analysis and weekly summaries are not implemented.
- In real mode the frontend's "today" is the browser's local date, while the backend uses `TAIM_UTC_OFFSET_HOURS`. They agree for students in the same timezone as the server setting.

## Data-model migration status

The V2 data layout is implemented in the backend. The migration utility remains a separate, explicit operation: it defaults to dry-run, and writes legacy records only when invoked with `--apply`. The application does not automatically migrate or delete legacy data. Keep `TAIM_ENABLE_V2` disabled until the migration and verification steps for the target Firebase project have been completed.

## Frontend structure

`index.html` · `css/{styles,landing}.css` · `js/{main,config,ui,firebase}.js` · `js/api/{client,mockData,firebaseAuth}.js` · `js/components/{taskModal,publicNav,glow,reveal}.js` · `js/pages/*.js` (landing, login, dashboard, tasks, planner, calendar, reminders, progress, assistant, settings).

`js/pages/landing.js` composes `components/publicNav.js` (floating navbar) and `components/glow.js` (canvas hero glow, reduced-motion aware). Styles: `css/landing.css`. Pages may return a cleanup function from `render()`; `main.js` calls it on navigation.
