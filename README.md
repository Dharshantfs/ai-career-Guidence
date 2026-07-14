# AI Learning Planner & Career Advisor

> **Reviewed & polished.** See [CHANGES.md](./CHANGES.md) for what was checked, tested, and fixed in this pass — including an important security note about your Gemini API key.


A full-stack web app that helps students pick a suitable career and get a
personalized, AI-generated learning plan — powered by Google's Gemini API.

Built with:
- **Frontend:** HTML, CSS, vanilla JavaScript
- **Backend:** FastAPI (Python)
- **Database:** SQLite
- **AI:** Google Gemini API

---

## 1. Features

- **Home page** — project overview + "Get Started" call to action
- **Register / Login** — secure signup with hashed passwords + JWT sessions
- **Student Profile** — education, department, college, year, skills, interests, daily study hours, optional career goal
- **AI Career Advisor** — if no career goal is set, asks a few quick questions and returns the top 5 recommended careers (with description, required skills, future scope, and reasoning)
- **AI Learning Planner** — generates a daily plan, weekly plan, monthly roadmap, skills to learn, free resources, and a small practice project for the chosen career
- **Dashboard** — profile summary, selected career, learning plan, and progress percentage
- **Progress Tracker** — check off tasks and watch your progress bar update in real time
- **AI Chat** — a simple free-form Q&A page to ask the AI anything directly (not just structured career/planner forms), with conversation context kept for the session

---

## 2. Project structure

```
ai_learning_planner/
├── backend/
│   ├── main.py              # FastAPI app + all API routes
│   ├── database.py          # SQLite connection + table creation
│   ├── models.py             # Pydantic request/response schemas
│   ├── auth_utils.py         # Password hashing + JWT helpers
│   ├── gemini_service.py     # Gemini API calls (career advice + learning plans)
│   ├── seed_data.py          # Optional: creates one demo login for testing
│   ├── requirements.txt
│   └── .env.example          # Copy to .env and fill in your Gemini API key
├── frontend/
│   ├── index.html            # Home
│   ├── register.html
│   ├── login.html
│   ├── profile.html          # Student Profile
│   ├── career-advisor.html   # AI Career Advisor
│   ├── learning-planner.html # AI Learning Planner
│   ├── dashboard.html        # Dashboard + Progress Tracker
│   ├── chat.html              # AI Chat (free-form Q&A)
│   ├── css/style.css
│   └── js/
│       ├── api.js            # Shared fetch wrapper + auth/session helpers
│       ├── auth.js            # Register/login form logic
│       ├── profile.js
│       ├── career.js
│       ├── planner.js
│       └── dashboard.js
├── database/
│   └── schema.sql             # Reference copy of the schema (auto-created by database.py)
└── README.md
```

---

## 3. Prerequisites

- Python 3.10 or newer
- A free Gemini API key: https://aistudio.google.com/app/apikey

---

## 4. Installation guide

**Step 1 — Get the code onto your machine and open a terminal in the project's root folder** (the folder containing `backend/`, `frontend/`, `database/`).

**Step 2 — Create a virtual environment (recommended)**

```bash
python -m venv venv

# Activate it:
# Windows:
venv\Scripts\activate
# macOS / Linux:
source venv/bin/activate
```

**Step 3 — Install backend dependencies**

```bash
cd backend
pip install -r requirements.txt
```

**Step 4 — Configure your environment variables**

```bash
# still inside backend/
cp .env.example .env      # Windows: copy .env.example .env
```

Open `.env` and fill in:

```
GEMINI_API_KEY=your_real_gemini_api_key
JWT_SECRET_KEY=any_long_random_string
JWT_EXPIRE_MINUTES=1440
```

**Step 5 — Run the server**

```bash
uvicorn main:app --reload --port 8000
```

You should see:
```
[database] SQLite ready at .../backend/learning_planner.db
Uvicorn running on http://127.0.0.1:8000
```

**Step 6 — Open the app**

Go to **http://127.0.0.1:8000** in your browser. The FastAPI server serves
both the API (`/api/...`) and the frontend pages from a single port, so
there's nothing else to start.

**Step 7 (optional) — Load sample/demo data**

In a second terminal (with the venv activated, inside `backend/`):

```bash
python seed_data.py
```

This creates a demo login you can use immediately:
```
email:    demo@student.com
password: demo1234
```

---

## 5. How the app flows

1. **Home** → click **Get Started** → **Register**
2. Fill in your **Student Profile** (career goal is optional)
3. If you left career goal blank → **AI Career Advisor** asks 3 quick
   questions, then shows your **top 5 career matches** — pick one
4. **AI Learning Planner** generates your daily/weekly/monthly plan,
   skills list, free resources, and a practice project
5. **Dashboard** shows everything together, with a checklist you can tick
   off — your progress percentage updates automatically

---

## 6. API reference

All endpoints are prefixed with `/api`. Except register/login, every route
requires an `Authorization: Bearer <token>` header (the frontend handles
this automatically once you're logged in).

| Method | Endpoint                        | Purpose                                   |
|--------|----------------------------------|--------------------------------------------|
| POST   | `/api/register`                 | Create an account, returns a session token |
| POST   | `/api/login`                    | Log in, returns a session token            |
| POST   | `/api/profile`                  | Create/update your student profile         |
| GET    | `/api/profile`                  | Get your saved profile                     |
| POST   | `/api/career/recommend`         | Get 3 AI-recommended careers               |
| GET    | `/api/career/options`           | Get your last set of recommendations       |
| POST   | `/api/career/select`            | Choose one recommended career              |
| POST   | `/api/learning-plan/generate`   | Generate an AI learning plan               |
| POST   | `/api/progress/update`          | Mark a task complete/incomplete            |
| GET    | `/api/dashboard`                | Get everything for the dashboard           |
| POST   | `/api/chat`                     | Free-form Q&A with the AI, with optional session conversation history |

Interactive API docs (Swagger UI) are also available automatically at
**http://127.0.0.1:8000/docs** once the server is running.

---

## 7. Notes on the Gemini integration

- Model used: `gemini-2.0-flash` (fast, works well on the free tier). You
  can change this in `backend/gemini_service.py` if you have access to a
  different Gemini model.
- Gemini is prompted to reply in strict JSON, which is parsed directly into
  the database and API responses. If Gemini ever wraps its answer in
  markdown code fences, `gemini_service.py` strips them automatically.
- If `GEMINI_API_KEY` is missing or still set to the placeholder value,
  career/learning-plan requests will return a clear error explaining how
  to fix it, instead of failing silently.

---

## 8. Security notes

- Passwords are hashed with bcrypt (via `passlib`) — never stored in plain text.
- Login sessions use signed JWTs with an expiry (`JWT_EXPIRE_MINUTES`).
- `JWT_SECRET_KEY` should be a long, random string in any real deployment —
  never commit your real `.env` file to version control.
- CORS is wide open (`allow_origins=["*"]`) for easy local development.
  Restrict this in `backend/main.py` before deploying publicly.

---

## 9. Troubleshooting

- **"AI career advisor failed" / "AI learning planner failed"** — check that
  `GEMINI_API_KEY` in `backend/.env` is correct and has quota remaining.
- **401 errors / getting logged out unexpectedly** — your session token
  expired (default 24 hours); just log in again.
- **Port already in use** — run on a different port:
  `uvicorn main:app --reload --port 8001` (then open that port in your browser).
