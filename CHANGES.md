# Review notes

## Second pass — proctored-test auto-submit bug + stale copy

Went through every page as a user would: register → profile → career
advisor → learning planner → dashboard → phased roadmap → project
submission → proctored test → certificate → AI chat, plus a full static
trace matching every frontend `fetch` call against its backend route and
every `id="..."` reference against the HTML that's supposed to contain it.
(Couldn't launch the live server in this environment — no network access
to install `fastapi`/`uvicorn`/etc. — so this was a thorough code-level
walkthrough plus isolated unit tests of the changed logic, not a live
click-through.)

**Bug found and fixed: auto-submitted proctored tests discarded real
answers and forced a score of 0.** When a student hit 3 tab-switch/
minimize violations during a phase test, `POST /api/tests/violation`
never received their selected answers (the frontend only sent
`attempt_id`), so the backend just hardcoded `score=0` and always failed
the phase — even if the student had already answered 20/25 questions
correctly before the violations happened. This contradicted the
documented behavior ("the test auto-submits with whatever was
answered"). Fixed by:
- `TestViolationRequest` now carries the student's current answers.
- `frontend/js/phases.js` sends the in-progress answers with every
  violation report.
- Backend grading logic (score/pass-fail + phase completion, badge
  awards, next-phase unlock, notifications) is now shared between a
  normal submit and a violation-triggered auto-submit via two new
  helpers (`_grade_test_answers`, `_finalize_test_phase`), so an
  auto-submit is graded exactly like a normal one instead of being a
  special-cased zero.
- The result screen after an auto-submit now shows the real score and,
  if it was actually a passing score, unlocks the next phase instead of
  always marking the phase failed.

**Stale copy fixed:** an earlier pass changed the career advisor from
recommending 3 careers to 5 (visible in `career-advisor.html` and the
prompt in `gemini_service.py`), but `index.html`'s homepage copy and
`README.md` still said "3" / "top 3" in three places. Updated to match
the actual behavior (5).

Everything else — auth, profile, phased roadmap generation/gating,
project submission + AI review, badges/streaks, notifications,
certificate generation, and all frontend↔backend contracts (every `id`
referenced by each page's JS exists in that page's HTML; every `fetch`
path/shape matches a real route/model) — checked out with no further
issues found.


I read through every backend and frontend file, installed the dependencies
in a clean virtual environment, ran the server, and exercised the full user
flow through the real API (register → profile → career recommend → select →
generate learning plan → progress update → dashboard). Overall the codebase
was well-structured and already close to production quality for a student
project — clean separation of concerns, parameterized SQL (no injection
risk), bcrypt password hashing, JWT sessions, and proper HTML-escaping in
the frontend JS (no XSS risk from AI-generated or user-entered text).

## ⚠️ Action required: rotate your Gemini API key

`backend/.env` in the uploaded zip contained a **live Gemini API key**.
That file has been removed from this package (only the placeholder
`.env.example` is included — copy it to `.env` and fill in your own key,
per the README). Since the key was already sitting in a file you shared,
you should treat it as compromised:

1. Go to https://aistudio.google.com/app/apikey
2. Delete/revoke the old key
3. Generate a new one and put it in your own local `.env`

## Bug fixed: Gemini calls could hang indefinitely

`gemini_service.py` calls Google's Gemini API and already had a good mock
fallback for when that call fails — but the call itself had no enforced
timeout. On a slow, filtered, or unreachable network, the underlying
`google-generativeai` library could hang the request forever instead of
falling back to the mock generator, leaving the user stuck on a spinner
with no error and no response.

Fixed by running the Gemini call in a worker thread with a hard 25-second
result timeout (`concurrent.futures`), so the API always responds — either
with a real Gemini result or the mock fallback — no matter what the network
is doing. This is on top of the existing 20s SDK-level timeout, which alone
wasn't always honored on connection-level failures.

## Everything else: verified working, no changes needed

- Auth: register, duplicate-email rejection, login, wrong-password
  rejection, JWT-protected routes, 401 on missing/expired token — all
  correct.
- Profile create/update (upsert) and fetch — correct.
- Career advisor: recommend → options → select flow, including the
  high-quality mock fallback careers when Gemini is unavailable — correct.
- Learning plan generation from a selected career or a profile's
  `career_goal`, auto-creation of progress-tracker rows — correct.
- Progress tracking and the dashboard's live progress-percentage
  calculation — correct.
- All seven frontend pages load and serve correctly from the FastAPI
  static-file routes.
- Removed a couple of stray machine-specific files (`powershell.cmd`) that
  weren't part of the actual application.
- Added a `.gitignore` so `.env`, the SQLite file, and `__pycache__` never
  get committed by accident in the future.

## Not changed

`seed_data.py`'s demo login (`demo@student.com` / `demo1234`) is intentional
and documented in the README as a quick way to explore the app — left as is.

## New feature: AI Chat page

Added a simple free-form Q&A page so you can talk to the AI directly instead
of only going through the structured career/planner forms:

- **Backend:** `POST /api/chat` (`gemini_service.chat_reply`) — takes a
  message plus optional conversation history, returns a plain-text reply.
  Uses the same profile-aware context and hard-timeout/mock-fallback pattern
  as the rest of the app, so it behaves the same way whether or not Gemini
  is reachable.
- **Frontend:** new `chat.html` + `js/chat.js` — a chat bubble UI with
  Enter-to-send, an auto-growing textarea, and an "AI Chat" link added to
  the nav on the profile/career-advisor/learning-planner/dashboard pages.
- Tested end-to-end: registered a user, chatted with and without prior
  history, confirmed the 422 validation on an empty message, the 403 on a
  missing auth token, and the ~25s hard-timeout fallback path when Gemini
  isn't reachable.

## New: file upload, leaderboard, email alerts, mentor dashboard

Closed the four gaps flagged as "not built" in the previous status check.

- **File upload for projects** — `POST /api/projects/submit-file`
  (multipart), stores the file under `backend/uploads/<user_id>/<phase_id>/`,
  reviewed by the same `gemini_service.review_project_submission` used for
  pasted code (`.zip` archives get a placeholder note instead of inline
  content, since they aren't unpacked). 5 MB limit, allowlisted extensions.
  `phases.html`'s submission modal now has an "Upload a file" option.
- **Leaderboard** — `GET /api/leaderboard`, ranks all students by
  `streak + badges*5 + completed_phases*10`. New `leaderboard.html` page,
  linked in the nav on every authenticated page.
- **Email alerts** — best-effort SMTP send (`send_email_alert` in
  `main.py`) fires alongside the existing in-app notification whenever the
  daily deadline-check job finds an overdue task. Off by default
  (`EMAIL_ALERTS_ENABLED=false` in `.env`); silently a no-op until an SMTP
  provider is configured, and any send failure is caught/logged, never
  raised, so a bad SMTP config can't break the scheduler job.
- **Mentor/teacher dashboard** — `users.role` (`student` | `mentor`) and a
  per-mentor `mentor_code` generated at registration. Students link
  themselves via `POST /api/mentor/link` (a field added to `profile.html`);
  mentors see their cohort's progress at `GET /api/mentor/dashboard` /
  the new `mentor-dashboard.html` page, gated by a `get_current_mentor_id`
  dependency that 403s non-mentor accounts.
- **DB migrations**: `users.role`, `users.mentor_code`,
  `student_profiles.mentor_id`, `project_submissions.file_path`,
  `project_submissions.file_name` — all added via the existing
  `ALTER TABLE ... IF NOT EXISTS`-style migration block in `database.py`,
  so upgrading an existing `learning_planner.db` doesn't require a reset.

### Verified without a live server
This sandbox has no network access, so `pip install fastapi` (etc.) wasn't
possible and the app couldn't be started with `uvicorn`. What was actually
checked:
- `python -m py_compile` on every backend file — no syntax errors.
- A `symtable`-based free-variable scan of `main.py` — no undefined names
  in any function body.
- `database.init_db()` run for real against both a fresh SQLite file and a
  simulated pre-upgrade DB (old schema, missing the new columns/tables) —
  confirmed every new column and table is created either way.
- The leaderboard and mentor-dashboard SQL queries run against seeded
  sample data with `sqlite3` directly (outside FastAPI) — confirmed
  correct point totals, sort order, and that a mentor only sees students
  who linked to their code.
- `send_email_alert` exercised directly — confirmed it's a true no-op
  when `EMAIL_ALERTS_ENABLED=false`, and that a bad/unreachable SMTP host
  is caught and returns `False` instead of raising.

**Not verified**: an actual end-to-end request through FastAPI/uvicorn
(routing, request validation, auth dependency wiring), the file-upload
endpoint's multipart handling, or a real SMTP send. Recommend running
`uvicorn main:app --reload` locally and smoke-testing register-as-mentor,
project file upload, and the leaderboard/mentor pages before treating
this as production-verified.
