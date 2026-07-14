# Enhancement notes — Phased Roadmap, Proctored Tests, and Alerts

This adds the three enhancements discussed: a multi-phase roadmap with
gated project review, a proctored phase-end test, and a notification
system (deadline alerts + focus-mode distraction nudges). Nothing in the
original app was removed — this is additive. The old single-shot
learning plan (`/api/learning-plan/generate`) still works exactly as
before; the new phased system builds on top of it.

## What's new

### 1. Phased roadmap (`backend/database.py`, `gemini_service.py`, `main.py`)
- New tables: `phases`, `project_submissions`, `test_attempts`, `notifications`.
- `progress` gained `phase_id`, `due_date`, `notified` columns (auto-migrated
  for existing databases).
- `POST /api/phases/generate` — breaks a learning plan's career goal into
  3-5 realistically-timed phases (e.g. "Basics" 8 weeks, "Intermediate"
  10 weeks...) via `gemini_service.generate_phased_roadmap`. Phase 1
  activates immediately (its weekly tasks become real `progress` rows with
  due dates); the rest start `locked`.
- `GET /api/phases` — the full roadmap with each phase's tasks and % done.

### 2. Project submission + AI review (gated progression)
- `POST /api/projects/submit` — submit code or a link for the active
  phase's project. `gemini_service.review_project_submission` returns
  approve/revise plus a structured error list (issue / why / fix). Approval
  flips the phase to `project_approved` (unlocking its test); rejection
  keeps it in `project_review` so the student can fix and resubmit.
- `GET /api/projects/{phase_id}` — latest submission + feedback.

### 3. Proctored phase-end test (25 marks)
- `POST /api/tests/start` — generates a 25-question multiple-choice test
  from the phase's focus skills (`gemini_service.generate_phase_test`).
- `POST /api/tests/violation` — the frontend calls this whenever it detects
  the browser tab losing focus or exiting fullscreen during the test.
  After 3 violations the test auto-submits with whatever was answered.
  **Caveat documented in the code and to the student up front:** this is
  browser-tab-level detection (Fullscreen API + Page Visibility API) — it
  cannot see or block activity in a separate native app, only this tab.
- `POST /api/tests/submit` — grades the test; ≥60% passes, marks the phase
  `completed`, and activates the next phase automatically.

### 4. Notifications (deadline alerts + focus-mode nudges)
- `GET /api/notifications` — runs an on-demand overdue-task check for the
  current user, then returns their recent notifications.
- An APScheduler background job (`_check_all_deadlines_job`) also runs
  every 24h across all users, so alerts don't depend on someone opening
  the app.
- `POST /api/notifications/distraction` — called by the optional "Focus
  Mode" toggle on the Roadmap page when the browser tab loses focus for
  5+ seconds. **Caveat:** a website can only observe its own tab's focus
  state, not activity in other native apps (Instagram/Facebook outside
  the browser) — that would require a browser extension or a mobile
  companion app using platform usage-tracking APIs, which is out of scope
  for this web app and noted as a future enhancement.

## Frontend
- New page: `frontend/phases.html` + `frontend/js/phases.js` — phase
  timeline, task checklist, project submission modal with AI feedback,
  fullscreen proctored test flow, and the Focus Mode toggle.
- `frontend/js/api.js` now injects a notification bell into the nav on
  every authenticated page (polls `/api/notifications` every 60s).
- New CSS in `frontend/css/style.css` for phase cards, status badges,
  review feedback, test UI, and the notification dropdown — reuses the
  existing "Trailhead" design tokens, no new fonts/colors introduced.

## Setup
No new setup steps beyond the original README — `pip install -r
requirements.txt` now also installs `APScheduler`. Existing users of the
old flat learning plan can generate a phased roadmap for that same plan
at any time from the new "Roadmap" nav link.

## Feature batch — Forgot Password, Skill Gap Analysis, Course Recommendations, Browser Notifications

Four additions, each slotted into the existing architecture rather than
built as parallel systems. Nothing existing was removed or changed in
behavior.

### 1. Forgot password (`backend/database.py`, `models.py`, `main.py`, `auth_utils.py` reused)
- New table: `password_reset_tokens` (user_id, token, expires_at, used).
- `POST /api/auth/forgot-password` — always returns a generic success
  message (never reveals whether an email is registered). If a matching
  account exists, issues a random 32-byte URL-safe token (30 min expiry)
  and reuses the existing `send_email_alert` helper to email a reset link.
  If `EMAIL_ALERTS_ENABLED` is false (no SMTP configured), the reset link
  is returned directly in the API response instead, so the whole flow —
  including on a machine with no email setup — still works end-to-end for
  local testing, the same spirit as the existing demo-login note on the
  login page.
- `POST /api/auth/reset-password` — verifies the token is unused and
  unexpired, updates the password hash via the existing `hash_password`,
  and invalidates the token (and any earlier unused tokens for that user).
- New pages: `forgot-password.html`, `reset-password.html`; a "Forgot
  password?" link was added under the password field on `login.html`.

### 2. Skill gap analysis (`backend/database.py`, `gemini_service.py`, `models.py`, `main.py`)
- New table: `skill_gaps` (career_id, career_name, matched_skills,
  missing_skills, summary — one row per analysis run, so history is kept).
- `gemini_service.analyze_skill_gap()` compares the student's typed skills
  against a career's `required_skills` using the model (so "JS" correctly
  matches a requirement listed as "JavaScript"), with an offline substring-
  match mock fallback if Gemini is unreachable.
- `POST /api/skill-gap/analyze` — analyzes against the student's currently
  selected career by default, or a specific `career_id` if passed (useful
  for comparing recommended-but-not-yet-chosen careers).
- `GET /api/skill-gap/latest` — returns the most recent analysis, so
  revisiting the page doesn't force a re-run.
- New page: `skill-gap.html` (linked from every student nav bar, after
  "Learning Planner"), renders matched skills as green chips and missing
  skills as orange chips, same visual language as the existing
  `.skill-chip` career cards.

### 3. Course recommendation module (same files as above)
- New table: `course_recommendations` (tied to a `skill_gaps` row; one
  entry per missing skill: title, provider, resource_type, url,
  description).
- `gemini_service.recommend_courses()` — for each missing skill, asks the
  model for one specific, real, free-or-low-cost course/tutorial/
  certification, with a freeCodeCamp-based mock fallback if Gemini is
  unreachable.
- `POST /api/skill-gap/courses` — generates recommendations for a given
  (or the latest) skill-gap analysis; regenerating replaces the old set.
- `GET /api/skill-gap/courses/{skill_gap_id}` — fetches a previously
  generated set without calling the AI again.
- On `skill-gap.html`, this is presented as the natural next step directly
  below the skill-gap results — "identify what's missing, then recommend
  where to learn it" is one continuous flow, not two separate pages.

### 4. Browser (OS-level) notifications — study reminders (`backend/main.py`, `frontend/js/api.js`)
- Reuses the existing `notifications` table and polling infrastructure
  (`GET /api/notifications`, the nav bell) rather than building a second
  notification system. Added a new notification `type`: `study_reminder`.
- New APScheduler job `_send_study_reminders_job`, registered alongside the
  existing daily deadline-check job: once a day (and once ~15s after
  server startup, so the feature is visible immediately in a demo), checks
  every student profile's `last_activity_date`; anyone who hasn't logged
  activity yet today gets one `study_reminder` notification. A new
  `last_reminder_date` column (auto-migrated) caps this to one nudge per
  student per day.
- Frontend: the notification bell's existing 60-second poll
  (`refreshNotifications` in `api.js`) now also calls
  `maybeShowBrowserNotifications()`, which fires a native
  `Notification(...)` for any unread notification the browser hasn't shown
  yet — but only if the student has granted permission. A small "Enable
  study reminders" button appears in the nav (next to the bell) the first
  time a logged-in student visits, calling the standard
  `Notification.requestPermission()`; it disappears for good once the
  student grants or denies, tracked in `localStorage`. This only ever adds
  a native notification on top of the in-app one — nothing changes for a
  student who never grants permission.
- Browser notification permission (like all browser permissions) is
  per-site and per-browser: it has to be granted again on a different
  browser/device, and only fires while the browser itself is open (not a
  true push notification requiring no browser at all, since that needs a
  service worker + push server, which is out of scope for this app's
  single-page-served-by-FastAPI architecture).
