"""
main.py
-------
The FastAPI application entry point. Wires together:
    - database.py       (SQLite storage)
    - models.py          (request/response validation)
    - auth_utils.py      (password hashing + JWT)
    - gemini_service.py  (AI career advice + learning plans)

Run with:
    uvicorn main:app --reload --port 8000

Serves the JSON API under /api/... and also serves the static frontend
(the ../frontend folder) so the whole app runs from a single server and
port, with no CORS issues.
"""

import json
import os
import secrets
import smtplib
from email.message import EmailMessage
from typing import Optional
from datetime import datetime, timedelta, date
from fastapi import FastAPI, HTTPException, Depends, status, UploadFile, File, Form
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from apscheduler.schedulers.background import BackgroundScheduler

from database import init_db, get_connection
from models import (
    RegisterRequest, LoginRequest, TokenResponse,
    ForgotPasswordRequest, ForgotPasswordResponse, ResetPasswordRequest,
    ProfileRequest, ProfileResponse,
    CareerAdvisorQuestionsRequest, CareerRecommendationResponse,
    SelectCareerRequest, GeneratePlanRequest, LearningPlanResponse,
    UpdateProgressRequest, DashboardResponse,
    ChatRequest, ChatResponse,
    GeneratePhasesRequest, PhaseResponse, PhaseTask,
    ProjectSubmitRequest, ProjectSubmissionResponse, ProjectError,
    TestStartRequest, TestStartResponse, TestQuestionForStudent,
    TestViolationRequest, TestSubmitRequest, TestResultResponse,
    NotificationItem, DistractionPingRequest,
    BadgeResponseItem, CertificateResponse,
    LeaderboardEntry, LeaderboardResponse,
    MentorLinkRequest, MentorStudentSummary, MentorDashboardResponse,
    SkillGapAnalyzeRequest, SkillGapResponse,
    CourseRecommendationRequest, CourseRecommendationItem, CourseRecommendationResponse,
)
from auth_utils import hash_password, verify_password, create_access_token, get_current_user_id
import gemini_service
import sqlite3
from datetime import datetime, timedelta, date

app = FastAPI(title="AI Learning Planner & Career Advisor")

# CORS left open for local development. Tighten allow_origins for production.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup():
    init_db()
    _start_scheduler()


def _generate_mentor_code() -> str:
    """Short, shareable code students type in to link themselves to a mentor's cohort."""
    return secrets.token_hex(4).upper()


def get_current_mentor_id(user_id: int = Depends(get_current_user_id)) -> int:
    """Dependency for mentor-only routes. Raises 403 if the logged-in user isn't a mentor."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT role FROM users WHERE id = ?", (user_id,))
    row = cur.fetchone()
    conn.close()
    if not row or row["role"] != "mentor":
        raise HTTPException(status_code=403, detail="This endpoint is only available to mentor accounts.")
    return user_id


# ---------------- EMAIL (best-effort; silently skipped if SMTP isn't configured) ----------------

EMAIL_ALERTS_ENABLED = os.getenv("EMAIL_ALERTS_ENABLED", "false").lower() == "true"
SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SMTP_FROM = os.getenv("SMTP_FROM", SMTP_USER)


def send_email_alert(to_email: str, subject: str, body: str) -> bool:
    """
    Best-effort email send. Returns True/False and never raises — a missing or
    misconfigured SMTP provider must not break the deadline-check job or any
    request that triggers a notification. In-app notifications are always
    created regardless of whether this succeeds.
    """
    if not EMAIL_ALERTS_ENABLED or not SMTP_HOST or not SMTP_USER:
        return False
    try:
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = SMTP_FROM
        msg["To"] = to_email
        msg.set_content(body)
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=10) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.send_message(msg)
        return True
    except Exception as e:
        print(f"[email] failed to send to {to_email}: {e}")
        return False


# =========================================================================
# AUTH
# =========================================================================

@app.post("/api/register", response_model=TokenResponse, tags=["Auth"])
def register(payload: RegisterRequest):
    """Create a new account. Emails must be unique."""
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("SELECT id FROM users WHERE email = ?", (payload.email,))
    if cur.fetchone():
        conn.close()
        raise HTTPException(status_code=400, detail="An account with this email already exists.")

    password_hash = hash_password(payload.password)
    mentor_code = _generate_mentor_code() if payload.role == "mentor" else None
    cur.execute(
        "INSERT INTO users (name, email, password_hash, role, mentor_code) VALUES (?, ?, ?, ?, ?)",
        (payload.name, payload.email, password_hash, payload.role, mentor_code),
    )
    conn.commit()
    user_id = cur.lastrowid
    conn.close()

    token = create_access_token(user_id, payload.email)
    return TokenResponse(access_token=token, user_id=user_id, name=payload.name, email=payload.email,
                          role=payload.role, mentor_code=mentor_code)


@app.post("/api/login", response_model=TokenResponse, tags=["Auth"])
def login(payload: LoginRequest):
    """Verify email + password, return a JWT session token."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT id, name, email, password_hash, role, mentor_code FROM users WHERE email = ?", (payload.email,))
    row = cur.fetchone()
    conn.close()

    if not row or not verify_password(payload.password, row["password_hash"]):
        raise HTTPException(status_code=401, detail="Incorrect email or password.")

    token = create_access_token(row["id"], row["email"])
    return TokenResponse(access_token=token, user_id=row["id"], name=row["name"], email=row["email"],
                          role=row["role"] or "student", mentor_code=row["mentor_code"])


RESET_TOKEN_EXPIRE_MINUTES = 30
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:8000")


@app.post("/api/auth/forgot-password", response_model=ForgotPasswordResponse, tags=["Auth"])
def forgot_password(payload: ForgotPasswordRequest):
    """
    Starts a password reset. Always returns a generic success message
    regardless of whether the email is registered, so this endpoint can't be
    used to figure out which emails have accounts.

    If email sending is configured (EMAIL_ALERTS_ENABLED), the reset link is
    emailed. If not, the link is returned directly in the response so the
    flow still works for local/dev use without an SMTP provider set up.
    """
    generic_message = "If an account exists for that email, a password reset link has been sent."

    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT id, name, email FROM users WHERE email = ?", (payload.email,))
    row = cur.fetchone()

    if not row:
        conn.close()
        return ForgotPasswordResponse(message=generic_message)

    token = secrets.token_urlsafe(32)
    expires_at = (datetime.utcnow() + timedelta(minutes=RESET_TOKEN_EXPIRE_MINUTES)).isoformat()
    # Invalidate any earlier unused tokens for this user before issuing a new one
    cur.execute("UPDATE password_reset_tokens SET used = 1 WHERE user_id = ? AND used = 0", (row["id"],))
    cur.execute(
        "INSERT INTO password_reset_tokens (user_id, token, expires_at) VALUES (?, ?, ?)",
        (row["id"], token, expires_at),
    )
    conn.commit()
    conn.close()

    reset_link = f"{FRONTEND_URL}/reset-password.html?token={token}"
    emailed = send_email_alert(
        row["email"],
        "Reset your password",
        f"Hi {row['name']},\n\nUse the link below to reset your password. "
        f"This link expires in {RESET_TOKEN_EXPIRE_MINUTES} minutes.\n\n{reset_link}\n\n"
        "If you didn't request this, you can safely ignore this email.",
    )

    return ForgotPasswordResponse(message=generic_message, reset_link=None if emailed else reset_link)


@app.post("/api/auth/reset-password", tags=["Auth"])
def reset_password(payload: ResetPasswordRequest):
    """Verifies a reset token (unused, unexpired) and updates the account's password."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT id, user_id, expires_at, used FROM password_reset_tokens WHERE token = ?",
        (payload.token,),
    )
    row = cur.fetchone()

    if not row or row["used"] or datetime.fromisoformat(row["expires_at"]) < datetime.utcnow():
        conn.close()
        raise HTTPException(status_code=400, detail="This reset link is invalid or has expired. Please request a new one.")

    new_hash = hash_password(payload.new_password)
    cur.execute("UPDATE users SET password_hash = ? WHERE id = ?", (new_hash, row["user_id"]))
    cur.execute("UPDATE password_reset_tokens SET used = 1 WHERE id = ?", (row["id"],))
    conn.commit()
    conn.close()
    return {"message": "Password reset successfully. You can now log in with your new password."}


# =========================================================================
# STUDENT PROFILE
# =========================================================================

@app.post("/api/profile", response_model=ProfileResponse, tags=["Profile"])
def save_profile(payload: ProfileRequest, user_id: int = Depends(get_current_user_id)):
    """Create or update the logged-in student's profile (upsert)."""
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("SELECT id FROM student_profiles WHERE user_id = ?", (user_id,))
    existing = cur.fetchone()

    if existing:
        cur.execute("""
            UPDATE student_profiles
            SET name=?, education=?, department=?, college=?, current_year=?,
                skills=?, interests=?, daily_study_hours=?, career_goal=?,
                updated_at=datetime('now')
            WHERE user_id=?
        """, (payload.name, payload.education, payload.department, payload.college,
              payload.current_year, payload.skills, payload.interests,
              payload.daily_study_hours, payload.career_goal, user_id))
    else:
        cur.execute("""
            INSERT INTO student_profiles
                (user_id, name, education, department, college, current_year,
                 skills, interests, daily_study_hours, career_goal)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (user_id, payload.name, payload.education, payload.department, payload.college,
              payload.current_year, payload.skills, payload.interests,
              payload.daily_study_hours, payload.career_goal))

    conn.commit()
    conn.close()
    return ProfileResponse(user_id=user_id, **payload.dict())


@app.get("/api/profile", response_model=ProfileResponse, tags=["Profile"])
def get_profile(user_id: int = Depends(get_current_user_id)):
    """Fetch the logged-in student's saved profile."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM student_profiles WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    conn.close()

    if not row:
        raise HTTPException(status_code=404, detail="No profile found yet. Please create one first.")

    return ProfileResponse(
        user_id=user_id, name=row["name"], education=row["education"],
        department=row["department"], college=row["college"], current_year=row["current_year"],
        skills=row["skills"], interests=row["interests"],
        daily_study_hours=row["daily_study_hours"], career_goal=row["career_goal"],
    )


def _get_profile_dict(user_id: int) -> dict:
    """Internal helper: fetch profile as a plain dict for feeding into Gemini prompts."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM student_profiles WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="Please complete your student profile first.")
    return dict(row)


# =========================================================================
# AI CAREER ADVISOR
# =========================================================================

@app.post("/api/career/recommend", response_model=CareerRecommendationResponse, tags=["Career Advisor"])
def recommend_career(
    answers: CareerAdvisorQuestionsRequest | None = None,
    user_id: int = Depends(get_current_user_id),
):
    """
    Calls Gemini to recommend 3 careers based on the student's profile.
    If the student already set a career_goal in their profile, `answers`
    can be omitted -- the profile alone is used as context.
    """
    profile = _get_profile_dict(user_id)
    extra = answers.dict() if answers else None

    try:
        careers = gemini_service.recommend_careers(profile, extra_answers=extra)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"AI career advisor failed: {e}")

    if not careers:
        raise HTTPException(status_code=502, detail="AI did not return any career suggestions. Please try again.")

    conn = get_connection()
    cur = conn.cursor()
    # Clear old (unselected) recommendations before storing fresh ones
    cur.execute("DELETE FROM careers WHERE user_id = ? AND is_selected = 0", (user_id,))
    for c in careers:
        cur.execute("""
            INSERT INTO careers (user_id, career_name, description, required_skills, future_scope, reason)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (user_id, c.get("career_name", ""), c.get("description", ""),
              json.dumps(c.get("required_skills", [])), c.get("future_scope", ""), c.get("reason", "")))
    conn.commit()

    cur.execute("SELECT * FROM careers WHERE user_id = ? AND is_selected = 0 ORDER BY id DESC LIMIT 5", (user_id,))
    rows = cur.fetchall()
    conn.close()

    result = [{
        "career_name": r["career_name"],
        "description": r["description"],
        "required_skills": json.loads(r["required_skills"] or "[]"),
        "future_scope": r["future_scope"],
        "reason": r["reason"],
    } for r in rows]

    return CareerRecommendationResponse(careers=result)


@app.get("/api/career/options", tags=["Career Advisor"])
def get_career_options(user_id: int = Depends(get_current_user_id)):
    """Fetch the most recently generated (not-yet-selected) career recommendations, with their ids."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM careers WHERE user_id = ? AND is_selected = 0 ORDER BY id DESC LIMIT 5", (user_id,))
    rows = cur.fetchall()
    conn.close()
    return [{
        "id": r["id"], "career_name": r["career_name"], "description": r["description"],
        "required_skills": json.loads(r["required_skills"] or "[]"),
        "future_scope": r["future_scope"], "reason": r["reason"],
    } for r in rows]


@app.post("/api/career/select", tags=["Career Advisor"])
def select_career(payload: SelectCareerRequest, user_id: int = Depends(get_current_user_id)):
    """Mark one of the recommended careers as the student's chosen path."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT id FROM careers WHERE id = ? AND user_id = ?", (payload.career_id, user_id))
    if not cur.fetchone():
        conn.close()
        raise HTTPException(status_code=404, detail="Career option not found.")

    cur.execute("UPDATE careers SET is_selected = 0 WHERE user_id = ?", (user_id,))
    cur.execute("UPDATE careers SET is_selected = 1 WHERE id = ?", (payload.career_id,))
    conn.commit()
    conn.close()
    return {"message": "Career selected successfully.", "career_id": payload.career_id}


# =========================================================================
# SKILL GAP ANALYSIS + COURSE RECOMMENDATIONS
# =========================================================================

def _resolve_target_career(cur, user_id: int, career_id: Optional[int]) -> dict:
    """Finds the career to analyze against: an explicit career_id, else the student's selected career."""
    if career_id:
        cur.execute("SELECT * FROM careers WHERE id = ? AND user_id = ?", (career_id, user_id))
    else:
        cur.execute("SELECT * FROM careers WHERE user_id = ? AND is_selected = 1", (user_id,))
    row = cur.fetchone()
    if not row:
        raise HTTPException(
            status_code=404,
            detail="No target career found. Select a career on the Career Advisor page first, or pass a career_id.",
        )
    return dict(row)


@app.post("/api/skill-gap/analyze", response_model=SkillGapResponse, tags=["Skill Gap"])
def analyze_skill_gap(payload: SkillGapAnalyzeRequest | None = None, user_id: int = Depends(get_current_user_id)):
    """Compares the student's current skills (from their profile) against a target career's required skills."""
    profile = _get_profile_dict(user_id)
    conn = get_connection()
    cur = conn.cursor()

    career_id = payload.career_id if payload else None
    career = _resolve_target_career(cur, user_id, career_id)
    required_skills = json.loads(career["required_skills"] or "[]")

    try:
        result = gemini_service.analyze_skill_gap(profile, career["career_name"], required_skills)
    except Exception as e:
        conn.close()
        raise HTTPException(status_code=502, detail=f"AI skill-gap analysis failed: {e}")

    matched = result.get("matched_skills", [])
    missing = result.get("missing_skills", [])
    summary = result.get("summary", "")

    cur.execute("""
        INSERT INTO skill_gaps (user_id, career_id, career_name, matched_skills, missing_skills, summary)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (user_id, career["id"], career["career_name"], json.dumps(matched), json.dumps(missing), summary))
    conn.commit()
    gap_id = cur.lastrowid
    cur.execute("SELECT * FROM skill_gaps WHERE id = ?", (gap_id,))
    row = cur.fetchone()
    conn.close()

    return SkillGapResponse(
        id=row["id"], career_name=row["career_name"],
        matched_skills=json.loads(row["matched_skills"] or "[]"),
        missing_skills=json.loads(row["missing_skills"] or "[]"),
        summary=row["summary"] or "", created_at=row["created_at"],
    )


@app.get("/api/skill-gap/latest", response_model=Optional[SkillGapResponse], tags=["Skill Gap"])
def get_latest_skill_gap(user_id: int = Depends(get_current_user_id)):
    """Fetches the most recent skill-gap analysis for this student, if any."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM skill_gaps WHERE user_id = ? ORDER BY id DESC LIMIT 1", (user_id,))
    row = cur.fetchone()
    conn.close()
    if not row:
        return None
    return SkillGapResponse(
        id=row["id"], career_name=row["career_name"],
        matched_skills=json.loads(row["matched_skills"] or "[]"),
        missing_skills=json.loads(row["missing_skills"] or "[]"),
        summary=row["summary"] or "", created_at=row["created_at"],
    )


@app.post("/api/skill-gap/courses", response_model=CourseRecommendationResponse, tags=["Skill Gap"])
def recommend_courses(payload: CourseRecommendationRequest | None = None, user_id: int = Depends(get_current_user_id)):
    """
    After a skill gap has been identified, generates a specific course /
    tutorial / certification suggestion for each missing skill.
    """
    conn = get_connection()
    cur = conn.cursor()

    gap_id = payload.skill_gap_id if payload else None
    if gap_id:
        cur.execute("SELECT * FROM skill_gaps WHERE id = ? AND user_id = ?", (gap_id, user_id))
    else:
        cur.execute("SELECT * FROM skill_gaps WHERE user_id = ? ORDER BY id DESC LIMIT 1", (user_id,))
    gap_row = cur.fetchone()
    if not gap_row:
        conn.close()
        raise HTTPException(status_code=404, detail="Run a skill-gap analysis first.")

    missing_skills = json.loads(gap_row["missing_skills"] or "[]")
    if not missing_skills:
        conn.close()
        return CourseRecommendationResponse(skill_gap_id=gap_row["id"], courses=[])

    try:
        courses = gemini_service.recommend_courses(gap_row["career_name"], missing_skills)
    except Exception as e:
        conn.close()
        raise HTTPException(status_code=502, detail=f"AI course recommender failed: {e}")

    # Replace any previously generated recommendations for this analysis
    cur.execute("DELETE FROM course_recommendations WHERE skill_gap_id = ?", (gap_row["id"],))
    for c in courses:
        cur.execute("""
            INSERT INTO course_recommendations
                (user_id, skill_gap_id, skill_name, title, provider, resource_type, url, description)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            user_id, gap_row["id"], c.get("skill_name", ""), c.get("title", ""),
            c.get("provider", ""), c.get("resource_type", "course"), c.get("url", ""), c.get("description", ""),
        ))
    conn.commit()

    cur.execute("SELECT * FROM course_recommendations WHERE skill_gap_id = ? ORDER BY id", (gap_row["id"],))
    rows = cur.fetchall()
    conn.close()

    return CourseRecommendationResponse(
        skill_gap_id=gap_row["id"],
        courses=[CourseRecommendationItem(
            id=r["id"], skill_name=r["skill_name"], title=r["title"], provider=r["provider"] or "",
            resource_type=r["resource_type"] or "course", url=r["url"] or "", description=r["description"] or "",
        ) for r in rows],
    )


@app.get("/api/skill-gap/courses/{skill_gap_id}", response_model=CourseRecommendationResponse, tags=["Skill Gap"])
def get_courses_for_gap(skill_gap_id: int, user_id: int = Depends(get_current_user_id)):
    """Fetches previously generated course recommendations for a given skill-gap analysis."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT id FROM skill_gaps WHERE id = ? AND user_id = ?", (skill_gap_id, user_id))
    if not cur.fetchone():
        conn.close()
        raise HTTPException(status_code=404, detail="Skill-gap analysis not found.")
    cur.execute("SELECT * FROM course_recommendations WHERE skill_gap_id = ? ORDER BY id", (skill_gap_id,))
    rows = cur.fetchall()
    conn.close()
    return CourseRecommendationResponse(
        skill_gap_id=skill_gap_id,
        courses=[CourseRecommendationItem(
            id=r["id"], skill_name=r["skill_name"], title=r["title"], provider=r["provider"] or "",
            resource_type=r["resource_type"] or "course", url=r["url"] or "", description=r["description"] or "",
        ) for r in rows],
    )


# =========================================================================
# AI LEARNING PLANNER
# =========================================================================

@app.post("/api/learning-plan/generate", response_model=LearningPlanResponse, tags=["Learning Planner"])
def generate_plan(payload: GeneratePlanRequest, user_id: int = Depends(get_current_user_id)):
    """
    Generates (via Gemini) and stores a full learning plan for either:
      - the career_id of a previously selected recommendation, or
      - a plain career_name (e.g. when the student already had a career_goal)
    Also auto-creates the individual progress-tracker checklist rows.
    """
    profile = _get_profile_dict(user_id)

    career_name = payload.career_name
    career_id = payload.career_id

    if career_id and not career_name:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT career_name FROM careers WHERE id = ? AND user_id = ?", (career_id, user_id))
        row = cur.fetchone()
        conn.close()
        if not row:
            raise HTTPException(status_code=404, detail="Career not found.")
        career_name = row["career_name"]

    if not career_name:
        career_name = profile.get("career_goal")

    if not career_name:
        raise HTTPException(status_code=400, detail="No career specified. Choose a career first.")

    try:
        plan = gemini_service.generate_learning_plan(profile, career_name)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"AI learning planner failed: {e}")

    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO learning_plans
            (user_id, career_id, career_name, daily_plan, weekly_plan, monthly_roadmap,
             skills_to_learn, resources, practice_project)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        user_id, career_id, career_name,
        json.dumps(plan.get("daily_plan", [])),
        json.dumps(plan.get("weekly_plan", [])),
        json.dumps(plan.get("monthly_roadmap", [])),
        json.dumps(plan.get("skills_to_learn", [])),
        json.dumps(plan.get("resources", [])),
        plan.get("practice_project", ""),
    ))
    plan_id = cur.lastrowid

    # Auto-generate progress tracker rows from each plan section
    def add_tasks(task_list, task_type):
        for task in task_list:
            cur.execute(
                "INSERT INTO progress (user_id, learning_plan_id, task_name, task_type) VALUES (?, ?, ?, ?)",
                (user_id, plan_id, task, task_type),
            )

    add_tasks(plan.get("daily_plan", []), "daily")
    add_tasks(plan.get("weekly_plan", []), "weekly")
    add_tasks(plan.get("monthly_roadmap", []), "monthly")
    add_tasks(plan.get("skills_to_learn", []), "skill")
    if plan.get("practice_project"):
        add_tasks([plan["practice_project"]], "project")

    conn.commit()
    conn.close()

    return LearningPlanResponse(
        id=plan_id, career_name=career_name,
        daily_plan=plan.get("daily_plan", []), weekly_plan=plan.get("weekly_plan", []),
        monthly_roadmap=plan.get("monthly_roadmap", []), skills_to_learn=plan.get("skills_to_learn", []),
        resources=plan.get("resources", []), practice_project=plan.get("practice_project", ""),
    )


# =========================================================================
# PROGRESS TRACKER
# =========================================================================

@app.post("/api/progress/update", tags=["Progress"])
def update_progress(payload: UpdateProgressRequest, user_id: int = Depends(get_current_user_id)):
    """Toggle a single checklist task as completed / not completed."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT id FROM progress WHERE id = ? AND user_id = ?", (payload.progress_id, user_id))
    if not cur.fetchone():
        conn.close()
        raise HTTPException(status_code=404, detail="Progress item not found.")

    cur.execute(
        "UPDATE progress SET is_completed = ?, completed_at = CASE WHEN ? THEN datetime('now') ELSE NULL END WHERE id = ?",
        (1 if payload.is_completed else 0, 1 if payload.is_completed else 0, payload.progress_id),
    )

    if payload.is_completed:
        _update_streak_and_badges(conn, cur, user_id)

    conn.commit()
    conn.close()
    return {"message": "Progress updated."}


# =========================================================================
# DASHBOARD
# =========================================================================

@app.get("/api/dashboard", response_model=DashboardResponse, tags=["Dashboard"])
def get_dashboard(user_id: int = Depends(get_current_user_id)):
    """Aggregates profile + selected career + latest learning plan + progress % for one screen."""
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("SELECT * FROM student_profiles WHERE user_id = ?", (user_id,))
    profile_row = cur.fetchone()
    profile = dict(profile_row) if profile_row else None

    cur.execute("SELECT * FROM careers WHERE user_id = ? AND is_selected = 1", (user_id,))
    career_row = cur.fetchone()
    selected_career = None
    if career_row:
        selected_career = dict(career_row)
        selected_career["required_skills"] = json.loads(selected_career["required_skills"] or "[]")

    cur.execute("SELECT * FROM learning_plans WHERE user_id = ? ORDER BY id DESC LIMIT 1", (user_id,))
    plan_row = cur.fetchone()
    learning_plan = None
    plan_id = None
    if plan_row:
        plan_id = plan_row["id"]
        learning_plan = {
            "id": plan_row["id"],
            "career_name": plan_row["career_name"],
            "daily_plan": json.loads(plan_row["daily_plan"] or "[]"),
            "weekly_plan": json.loads(plan_row["weekly_plan"] or "[]"),
            "monthly_roadmap": json.loads(plan_row["monthly_roadmap"] or "[]"),
            "skills_to_learn": json.loads(plan_row["skills_to_learn"] or "[]"),
            "resources": json.loads(plan_row["resources"] or "[]"),
            "practice_project": plan_row["practice_project"],
        }

    progress_items = []
    progress_percentage = 0.0
    has_phases = False
    if plan_id:
        # Check if a phased roadmap exists for this plan
        cur.execute("SELECT COUNT(*) as count FROM phases WHERE learning_plan_id = ?", (plan_id,))
        has_phases = cur.fetchone()["count"] > 0

        if has_phases:
            # Show only tasks belonging to the active phase
            cur.execute("""
                SELECT p.* FROM progress p
                JOIN phases ph ON p.phase_id = ph.id
                WHERE p.learning_plan_id = ? AND ph.status = 'active'
                ORDER BY p.id
            """, (plan_id,))
        else:
            # Show legacy tasks (phase_id is NULL)
            cur.execute("SELECT * FROM progress WHERE learning_plan_id = ? AND phase_id IS NULL ORDER BY id", (plan_id,))

        prog_rows = cur.fetchall()
        progress_items = [{
            "id": p["id"], "task_name": p["task_name"], "task_type": p["task_type"],
            "is_completed": bool(p["is_completed"]),
        } for p in prog_rows]
        if progress_items:
            done = sum(1 for p in progress_items if p["is_completed"])
            progress_percentage = round((done / len(progress_items)) * 100, 1)

    # Fetch streaks & badges for dashboard
    cur.execute("SELECT current_streak, longest_streak FROM student_profiles WHERE user_id = ?", (user_id,))
    streak_row = cur.fetchone()
    current_streak = streak_row["current_streak"] if streak_row else 0
    longest_streak = streak_row["longest_streak"] if streak_row else 0

    cur.execute("SELECT badge_code, badge_name, description, awarded_at FROM badges WHERE user_id = ? ORDER BY id DESC", (user_id,))
    badge_rows = cur.fetchall()
    badges = [{
        "badge_code": b["badge_code"],
        "badge_name": b["badge_name"],
        "description": b["description"] or "",
        "awarded_at": b["awarded_at"]
    } for b in badge_rows]

    conn.close()

    return DashboardResponse(
        profile=profile, selected_career=selected_career, learning_plan=learning_plan,
        progress=progress_items, progress_percentage=progress_percentage,
        has_phases=has_phases, current_streak=current_streak, longest_streak=longest_streak,
        badges=badges,
    )


# =========================================================================
# AI CHAT
# =========================================================================

@app.post("/api/chat", response_model=ChatResponse, tags=["Chat"])
def chat(payload: ChatRequest, user_id: int = Depends(get_current_user_id)):
    """Free-form Q&A with the AI. Optionally uses the student's profile as context."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM student_profiles WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    conn.close()
    profile = dict(row) if row else None

    history = [h.dict() for h in payload.history]

    try:
        reply = gemini_service.chat_reply(payload.message, history=history, profile=profile)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"AI chat failed: {e}")

    return ChatResponse(reply=reply)



TEST_PASS_PERCENTAGE = 60      # student needs >=60% to pass a phase test and unlock the next phase
MAX_TEST_VIOLATIONS = 3        # tab-switch / minimize events allowed before auto-submit


def _row_learning_plan_owner(cur, learning_plan_id: int, user_id: int):
    cur.execute("SELECT id, career_name FROM learning_plans WHERE id = ? AND user_id = ?", (learning_plan_id, user_id))
    row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Learning plan not found.")
    return row


def _row_phase_owner(cur, phase_id: int, user_id: int):
    cur.execute("SELECT * FROM phases WHERE id = ? AND user_id = ?", (phase_id, user_id))
    row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Phase not found.")
    return row


def _phase_tasks_incomplete_count(cur, phase_id: int) -> int:
    """Server-side enforcement mirroring the frontend gate: how many of this phase's weekly tasks are still unticked."""
    cur.execute("SELECT COUNT(*) c FROM progress WHERE phase_id = ? AND is_completed = 0", (phase_id,))
    return cur.fetchone()["c"]


def _activate_phase(cur, phase_row):
    """
    Materializes a phase's stored weekly_tasks into real `progress` rows with
    due dates spread one-per-week across the phase, and flips its status to
    'active'. Called when a phase first becomes reachable.
    """
    weekly_tasks = json.loads(phase_row["weekly_tasks"] or "[]")
    start = datetime.utcnow().date()
    for i, task in enumerate(weekly_tasks):
        due = start + timedelta(weeks=i + 1)
        cur.execute("""
            INSERT INTO progress (user_id, learning_plan_id, task_name, task_type, phase_id, due_date)
            VALUES (?, ?, ?, 'weekly', ?, ?)
        """, (phase_row["user_id"], phase_row["learning_plan_id"], task, phase_row["id"], due.isoformat()))
    cur.execute(
        "UPDATE phases SET status='active', start_date=?, end_date=? WHERE id=?",
        (start.isoformat(), (start + timedelta(weeks=len(weekly_tasks) or phase_row["duration_weeks"])).isoformat(), phase_row["id"]),
    )


def _phase_to_response(cur, phase_row) -> PhaseResponse:
    cur.execute("SELECT * FROM progress WHERE phase_id = ? ORDER BY id", (phase_row["id"],))
    task_rows = cur.fetchall()
    tasks = [PhaseTask(id=t["id"], task_name=t["task_name"], is_completed=bool(t["is_completed"]), due_date=t["due_date"]) for t in task_rows]
    pct = round((sum(1 for t in tasks if t.is_completed) / len(tasks)) * 100, 1) if tasks else 0.0
    return PhaseResponse(
        id=phase_row["id"], phase_order=phase_row["phase_order"], phase_name=phase_row["phase_name"],
        description=phase_row["description"] or "", duration_weeks=phase_row["duration_weeks"],
        focus_skills=json.loads(phase_row["focus_skills"] or "[]"), project_brief=phase_row["project_brief"] or "",
        start_date=phase_row["start_date"], end_date=phase_row["end_date"], status=phase_row["status"],
        tasks=tasks, task_progress_percentage=pct,
    )


# =========================================================================
# PHASED ROADMAP (multi-month curriculum with gated project + test per phase)
# =========================================================================

@app.post("/api/phases/generate", response_model=list[PhaseResponse], tags=["Phased Roadmap"])
def generate_phases(payload: GeneratePhasesRequest, user_id: int = Depends(get_current_user_id)):
    """Breaks a learning plan's goal into sequential, realistically-timed phases. Phase 1 activates immediately; the rest start locked."""
    conn = get_connection()
    cur = conn.cursor()
    plan_row = _row_learning_plan_owner(cur, payload.learning_plan_id, user_id)

    cur.execute("SELECT * FROM phases WHERE learning_plan_id = ? ORDER BY phase_order", (payload.learning_plan_id,))
    existing = cur.fetchall()
    if existing:
        result = [_phase_to_response(cur, r) for r in existing]
        conn.close()
        return result

    profile = _get_profile_dict(user_id)
    try:
        phases = gemini_service.generate_phased_roadmap(profile, plan_row["career_name"])
    except Exception as e:
        conn.close()
        raise HTTPException(status_code=502, detail=f"AI phased roadmap generation failed: {e}")

    for i, ph in enumerate(phases):
        cur.execute("""
            INSERT INTO phases (user_id, learning_plan_id, phase_order, phase_name, description,
                                 duration_weeks, focus_skills, weekly_tasks, project_brief, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            user_id, payload.learning_plan_id, i + 1, ph.get("phase_name", f"Phase {i+1}"),
            ph.get("description", ""), ph.get("duration_weeks", 4),
            json.dumps(ph.get("focus_skills", [])), json.dumps(ph.get("weekly_tasks", [])),
            ph.get("project_brief", ""), "locked",
        ))

    cur.execute("SELECT * FROM phases WHERE learning_plan_id = ? ORDER BY phase_order", (payload.learning_plan_id,))
    all_phases = cur.fetchall()
    if all_phases:
        _activate_phase(cur, all_phases[0])  # unlock phase 1 immediately

    conn.commit()
    cur.execute("SELECT * FROM phases WHERE learning_plan_id = ? ORDER BY phase_order", (payload.learning_plan_id,))
    result = [_phase_to_response(cur, r) for r in cur.fetchall()]
    conn.close()
    return result


@app.get("/api/phases", response_model=list[PhaseResponse], tags=["Phased Roadmap"])
def list_phases(user_id: int = Depends(get_current_user_id)):
    """All phases for the student's most recent learning plan."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT id FROM learning_plans WHERE user_id = ? ORDER BY id DESC LIMIT 1", (user_id,))
    plan = cur.fetchone()
    if not plan:
        conn.close()
        return []
    cur.execute("SELECT * FROM phases WHERE learning_plan_id = ? ORDER BY phase_order", (plan["id"],))
    result = [_phase_to_response(cur, r) for r in cur.fetchall()]
    conn.close()
    return result


# =========================================================================
# PROJECT SUBMISSION & AI REVIEW
# =========================================================================

@app.post("/api/projects/submit", response_model=ProjectSubmissionResponse, tags=["Projects"])
def submit_project(payload: ProjectSubmitRequest, user_id: int = Depends(get_current_user_id)):
    """Submit a phase-end project. AI reviews it immediately: approves (unlocking the test) or returns specific errors to fix and resubmit."""
    conn = get_connection()
    cur = conn.cursor()
    phase = _row_phase_owner(cur, payload.phase_id, user_id)

    if phase["status"] not in ("active", "project_review"):
        conn.close()
        raise HTTPException(status_code=400, detail=f"This phase is not open for project submission (status: {phase['status']}).")

    if phase["status"] == "active" and _phase_tasks_incomplete_count(cur, payload.phase_id) > 0:
        conn.close()
        raise HTTPException(status_code=400, detail="Tick off all of this phase's weekly tasks before submitting the project.")

    try:
        review = gemini_service.review_project_submission(
            phase["phase_name"], json.loads(phase["focus_skills"] or "[]"),
            phase["project_brief"] or "", payload.submission_type, payload.content,
        )
    except Exception as e:
        conn.close()
        raise HTTPException(status_code=502, detail=f"AI project review failed: {e}")

    approved = bool(review.get("approved"))
    errors = review.get("errors", [])
    score = int(review.get("score", 0) or 0)
    summary = review.get("summary", "")

    cur.execute("""
        INSERT INTO project_submissions (user_id, phase_id, submission_type, content, status, ai_summary, ai_errors, ai_score, reviewed_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
    """, (user_id, payload.phase_id, payload.submission_type, payload.content,
          "approved" if approved else "needs_revision", summary, json.dumps(errors), score))
    submission_id = cur.lastrowid

    new_status = "project_approved" if approved else "project_review"
    cur.execute("UPDATE phases SET status=? WHERE id=?", (new_status, payload.phase_id))

    if approved:
        cur.execute(
            "INSERT INTO notifications (user_id, type, message) VALUES (?, 'phase', ?)",
            (user_id, f"Project approved for '{phase['phase_name']}'! The phase test is now unlocked."),
        )

    conn.commit()
    cur.execute("SELECT * FROM project_submissions WHERE id=?", (submission_id,))
    row = cur.fetchone()
    conn.close()

    return ProjectSubmissionResponse(
        id=row["id"], phase_id=row["phase_id"], status=row["status"], ai_summary=row["ai_summary"] or "",
        ai_errors=[ProjectError(**e) for e in json.loads(row["ai_errors"] or "[]")],
        ai_score=row["ai_score"] or 0, submitted_at=row["submitted_at"], file_name=row["file_name"],
    )


UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "uploads")
MAX_UPLOAD_BYTES = 5 * 1024 * 1024  # 5 MB
ALLOWED_UPLOAD_EXTENSIONS = {
    ".py", ".js", ".ts", ".jsx", ".tsx", ".java", ".c", ".cpp", ".cs", ".go", ".rb",
    ".php", ".html", ".css", ".json", ".md", ".txt", ".sql", ".sh", ".zip",
}


@app.post("/api/projects/submit-file", response_model=ProjectSubmissionResponse, tags=["Projects"])
async def submit_project_file(
    phase_id: int = Form(...),
    file: UploadFile = File(...),
    user_id: int = Depends(get_current_user_id),
):
    """
    Submit a phase-end project as an uploaded file (code archive or single
    source file) instead of pasted code or a link. The file is stored on
    disk under backend/uploads/, and for reviewable text files its content
    is also passed to the same AI reviewer used for pasted code.
    """
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in ALLOWED_UPLOAD_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"Unsupported file type '{ext}'. Allowed: {', '.join(sorted(ALLOWED_UPLOAD_EXTENSIONS))}")

    contents = await file.read()
    if len(contents) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=400, detail="File is too large (5 MB limit).")

    conn = get_connection()
    cur = conn.cursor()
    phase = _row_phase_owner(cur, phase_id, user_id)

    if phase["status"] not in ("active", "project_review"):
        conn.close()
        raise HTTPException(status_code=400, detail=f"This phase is not open for project submission (status: {phase['status']}).")

    if phase["status"] == "active" and _phase_tasks_incomplete_count(cur, phase_id) > 0:
        conn.close()
        raise HTTPException(status_code=400, detail="Tick off all of this phase's weekly tasks before submitting the project.")

    user_dir = os.path.join(UPLOAD_DIR, str(user_id), str(phase_id))
    os.makedirs(user_dir, exist_ok=True)
    safe_name = f"{secrets.token_hex(4)}_{os.path.basename(file.filename)}"
    dest_path = os.path.join(user_dir, safe_name)
    with open(dest_path, "wb") as f:
        f.write(contents)

    # Text-based files get their content reviewed the same way pasted code does.
    # Archives (.zip) can't be inspected without unpacking, so the reviewer
    # gets a note explaining that instead and evaluates from the project brief alone.
    if ext == ".zip":
        review_content = f"[Uploaded archive '{file.filename}' — {len(contents)} bytes. Contents could not be inspected inline.]"
    else:
        try:
            review_content = contents.decode("utf-8", errors="replace")
        except Exception:
            review_content = f"[Uploaded file '{file.filename}' could not be decoded as text.]"

    try:
        review = gemini_service.review_project_submission(
            phase["phase_name"], json.loads(phase["focus_skills"] or "[]"),
            phase["project_brief"] or "", "file", review_content,
        )
    except Exception as e:
        conn.close()
        raise HTTPException(status_code=502, detail=f"AI project review failed: {e}")

    approved = bool(review.get("approved"))
    errors = review.get("errors", [])
    score = int(review.get("score", 0) or 0)
    summary = review.get("summary", "")

    cur.execute("""
        INSERT INTO project_submissions
            (user_id, phase_id, submission_type, content, status, ai_summary, ai_errors, ai_score, reviewed_at, file_path, file_name)
        VALUES (?, ?, 'file', ?, ?, ?, ?, ?, datetime('now'), ?, ?)
    """, (user_id, phase_id, f"[file upload: {file.filename}]",
          "approved" if approved else "needs_revision", summary, json.dumps(errors), score,
          dest_path, file.filename))
    submission_id = cur.lastrowid

    new_status = "project_approved" if approved else "project_review"
    cur.execute("UPDATE phases SET status=? WHERE id=?", (new_status, phase_id))

    if approved:
        cur.execute(
            "INSERT INTO notifications (user_id, type, message) VALUES (?, 'phase', ?)",
            (user_id, f"Project approved for '{phase['phase_name']}'! The phase test is now unlocked."),
        )

    conn.commit()
    cur.execute("SELECT * FROM project_submissions WHERE id=?", (submission_id,))
    row = cur.fetchone()
    conn.close()

    return ProjectSubmissionResponse(
        id=row["id"], phase_id=row["phase_id"], status=row["status"], ai_summary=row["ai_summary"] or "",
        ai_errors=[ProjectError(**e) for e in json.loads(row["ai_errors"] or "[]")],
        ai_score=row["ai_score"] or 0, submitted_at=row["submitted_at"], file_name=row["file_name"],
    )


@app.get("/api/projects/{phase_id}", response_model=Optional[ProjectSubmissionResponse], tags=["Projects"])
def get_latest_submission(phase_id: int, user_id: int = Depends(get_current_user_id)):
    """Latest submission + AI feedback for a phase, if any."""
    conn = get_connection()
    cur = conn.cursor()
    _row_phase_owner(cur, phase_id, user_id)
    cur.execute("SELECT * FROM project_submissions WHERE phase_id = ? AND user_id = ? ORDER BY id DESC LIMIT 1", (phase_id, user_id))
    row = cur.fetchone()
    conn.close()
    if not row:
        return None
    return ProjectSubmissionResponse(
        id=row["id"], phase_id=row["phase_id"], status=row["status"], ai_summary=row["ai_summary"] or "",
        ai_errors=[ProjectError(**e) for e in json.loads(row["ai_errors"] or "[]")],
        ai_score=row["ai_score"] or 0, submitted_at=row["submitted_at"], file_name=row["file_name"],
    )


# =========================================================================
# PROCTORED PHASE-END TEST (25 marks, browser-level anti-cheat)
# =========================================================================

@app.post("/api/tests/start", response_model=TestStartResponse, tags=["Tests"])
def start_test(payload: TestStartRequest, user_id: int = Depends(get_current_user_id)):
    """Generates a fresh 25-question test for an approved phase. The test must be taken fullscreen; the frontend reports violations via /api/tests/violation."""
    conn = get_connection()
    cur = conn.cursor()
    phase = _row_phase_owner(cur, payload.phase_id, user_id)

    if phase["status"] not in ("project_approved", "test_failed"):
        conn.close()
        raise HTTPException(status_code=400, detail="Submit and get your project approved before taking this phase's test.")

    try:
        questions = gemini_service.generate_phase_test(phase["phase_name"], json.loads(phase["focus_skills"] or "[]"))
    except Exception as e:
        conn.close()
        raise HTTPException(status_code=502, detail=f"AI test generation failed: {e}")

    cur.execute("""
        INSERT INTO test_attempts (user_id, phase_id, questions, total_marks, status)
        VALUES (?, ?, ?, ?, 'in_progress')
    """, (user_id, payload.phase_id, json.dumps(questions), len(questions)))
    attempt_id = cur.lastrowid
    conn.commit()
    conn.close()

    student_questions = [
        TestQuestionForStudent(index=i, question=q["question"], options=q["options"])
        for i, q in enumerate(questions)
    ]

    return TestStartResponse(
        attempt_id=attempt_id, phase_name=phase["phase_name"], total_marks=len(questions),
        questions=student_questions,
        instructions=[
            "This test will open in fullscreen and must stay that way for the entire attempt.",
            "Do NOT switch tabs, open another app, or minimize this window.",
            f"Doing so is logged as a violation; after {MAX_TEST_VIOLATIONS} violations the test auto-submits with your current answers.",
            f"You need {TEST_PASS_PERCENTAGE}% or higher to pass and unlock the next phase.",
            "Once you start, there is no pausing -- make sure you're ready before continuing.",
        ],
    )


def _grade_test_answers(attempt, answers: list) -> tuple[int, int, bool]:
    """Pure grading calculation shared by a normal submit and a violation-triggered auto-submit."""
    questions = json.loads(attempt["questions"])
    answer_map = {a.index: a.selected_option for a in answers}
    score = sum(1 for i, q in enumerate(questions) if answer_map.get(i) == q.get("correct_index"))
    total = len(questions)
    passed = total > 0 and (score / total) * 100 >= TEST_PASS_PERCENTAGE
    return score, total, passed


def _finalize_test_phase(cur, user_id: int, attempt, score: int, total: int, passed: bool) -> bool:
    """
    Shared post-grading logic (used by both a normal submit and an auto-submit
    triggered by too many proctoring violations): flips the phase to
    completed/test_failed, awards badges, unlocks the next phase on a pass,
    and raises the relevant notifications. Returns whether the next phase was unlocked.
    """
    next_unlocked = False
    if passed:
        cur.execute("UPDATE phases SET status='completed' WHERE id=?", (attempt["phase_id"],))
        cur.execute("SELECT * FROM phases WHERE id=?", (attempt["phase_id"],))
        this_phase = cur.fetchone()
        cur.execute(
            "SELECT * FROM phases WHERE learning_plan_id=? AND phase_order=?",
            (this_phase["learning_plan_id"], this_phase["phase_order"] + 1),
        )
        next_phase = cur.fetchone()

        # Award "Phase Champion" badge
        try:
            badge_code = f"phase_{this_phase['id']}_champion"
            badge_name = f"Phase Champion: {this_phase['phase_name']}"
            badge_desc = f"Successfully completed all requirements and passed the test for '{this_phase['phase_name']}'!"
            cur.execute("""
                INSERT INTO badges (user_id, badge_code, badge_name, description)
                VALUES (?, ?, ?, ?)
            """, (user_id, badge_code, badge_name, badge_desc))
            cur.execute(
                "INSERT INTO notifications (user_id, type, message) VALUES (?, 'phase', ?)",
                (user_id, f"Congratulations! You've earned the '{badge_name}' badge!"),
            )
        except sqlite3.IntegrityError:
            pass

        if next_phase:
            _activate_phase(cur, next_phase)
            next_unlocked = True
            cur.execute(
                "INSERT INTO notifications (user_id, type, message) VALUES (?, 'phase', ?)",
                (user_id, f"You passed '{this_phase['phase_name']}' ({score}/{total})! '{next_phase['phase_name']}' is now unlocked."),
            )
        else:
            # Award "Roadmap Master" badge
            try:
                cur.execute("SELECT career_name FROM learning_plans WHERE id = ?", (this_phase["learning_plan_id"],))
                lp_row = cur.fetchone()
                c_name = lp_row["career_name"] if lp_row else "selected career"
                cur.execute("""
                    INSERT INTO badges (user_id, badge_code, badge_name, description)
                    VALUES (?, 'roadmap_master', 'Roadmap Master', ?)
                """, (user_id, f"Mastered the entire '{c_name}' roadmap by completing all phases and tests!"))
                cur.execute(
                    "INSERT INTO notifications (user_id, type, message) VALUES (?, 'phase', ?)",
                    (user_id, "Congratulations! You've earned the 'Roadmap Master' badge!"),
                )
            except sqlite3.IntegrityError:
                pass

            cur.execute(
                "INSERT INTO notifications (user_id, type, message) VALUES (?, 'phase', ?)",
                (user_id, f"You passed '{this_phase['phase_name']}' ({score}/{total}) -- that was the final phase. Roadmap complete!"),
            )
    else:
        cur.execute("UPDATE phases SET status='test_failed' WHERE id=?", (attempt["phase_id"],))
        cur.execute(
            "INSERT INTO notifications (user_id, type, message) VALUES (?, 'test', ?)",
            (user_id, f"You scored {score}/{total} -- below the {TEST_PASS_PERCENTAGE}% pass mark. Review the phase material and retake when ready."),
        )
    return next_unlocked


@app.post("/api/tests/violation", tags=["Tests"])
def report_test_violation(payload: TestViolationRequest, user_id: int = Depends(get_current_user_id)):
    """
    Frontend calls this whenever it detects a tab-switch/minimize/blur during an
    active test, sending along whatever answers are currently selected. After
    MAX_TEST_VIOLATIONS this triggers an auto-submit that is graded exactly like
    a normal submission (using those answers) rather than being forced to zero,
    so the outcome reflects what the student had actually answered.
    """
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM test_attempts WHERE id = ? AND user_id = ?", (payload.attempt_id, user_id))
    attempt = cur.fetchone()
    if not attempt:
        conn.close()
        raise HTTPException(status_code=404, detail="Test attempt not found.")
    if attempt["status"] != "in_progress":
        conn.close()
        return {"violations": attempt["violations"], "auto_submitted": True}

    violations = attempt["violations"] + 1
    auto_submit = violations >= MAX_TEST_VIOLATIONS
    cur.execute("UPDATE test_attempts SET violations = ? WHERE id = ?", (violations, payload.attempt_id))

    result = {"violations": violations, "auto_submitted": auto_submit}

    if auto_submit:
        score, total, passed = _grade_test_answers(attempt, payload.answers)
        cur.execute(
            "UPDATE test_attempts SET answers=?, score=?, status='auto_submitted', completed_at=datetime('now') WHERE id=?",
            (json.dumps([a.dict() for a in payload.answers]), score, payload.attempt_id),
        )
        next_unlocked = _finalize_test_phase(cur, user_id, attempt, score, total, passed)
        cur.execute(
            "INSERT INTO notifications (user_id, type, message) VALUES (?, 'test', ?)",
            (user_id, (
                f"Your test was auto-submitted after {MAX_TEST_VIOLATIONS} violations (tab switch / minimize "
                f"detected), graded on the {len(payload.answers)} answer(s) you'd selected: {score}/{total}"
                f"{' -- you passed!' if passed else ' -- you can retake it.'}"
            )),
        )
        result.update({"score": score, "total_marks": total, "passed": passed, "next_phase_unlocked": next_unlocked})

    conn.commit()
    conn.close()
    return result


@app.post("/api/tests/submit", response_model=TestResultResponse, tags=["Tests"])
def submit_test(payload: TestSubmitRequest, user_id: int = Depends(get_current_user_id)):
    """Grades the test. Passing (>=60%) marks the phase completed and unlocks the next phase; failing allows a retake."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM test_attempts WHERE id = ? AND user_id = ?", (payload.attempt_id, user_id))
    attempt = cur.fetchone()
    if not attempt:
        conn.close()
        raise HTTPException(status_code=404, detail="Test attempt not found.")
    if attempt["status"] != "in_progress":
        conn.close()
        raise HTTPException(status_code=400, detail=f"This test attempt is already {attempt['status']}.")

    score, total, passed = _grade_test_answers(attempt, payload.answers)
    new_status = "passed" if passed else "failed"

    cur.execute("""
        UPDATE test_attempts SET answers=?, score=?, status=?, completed_at=datetime('now') WHERE id=?
    """, (json.dumps([a.dict() for a in payload.answers]), score, new_status, payload.attempt_id))

    next_unlocked = _finalize_test_phase(cur, user_id, attempt, score, total, passed)

    conn.commit()
    conn.close()

    return TestResultResponse(
        attempt_id=payload.attempt_id, score=score, total_marks=total, passed=passed,
        violations=attempt["violations"], status=new_status, next_phase_unlocked=next_unlocked,
    )


# =========================================================================
# NOTIFICATIONS (missed-deadline alerts + focus-mode distraction nudges)
# =========================================================================

def _check_deadlines_for_user(cur, user_id: int):
    """Finds overdue, incomplete phase tasks and raises a notification for each one, once."""
    today = datetime.utcnow().date().isoformat()
    cur.execute("""
        SELECT id, task_name FROM progress
        WHERE user_id = ? AND is_completed = 0 AND notified = 0
              AND due_date IS NOT NULL AND due_date < ?
    """, (user_id, today))
    overdue = cur.fetchall()
    if overdue and EMAIL_ALERTS_ENABLED:
        cur.execute("SELECT email, name FROM users WHERE id = ?", (user_id,))
        user_row = cur.fetchone()
    else:
        user_row = None
    for task in overdue:
        message = f"You missed the deadline for: \"{task['task_name']}\". Complete it soon to stay on your roadmap."
        cur.execute(
            "INSERT INTO notifications (user_id, type, message) VALUES (?, 'deadline', ?)",
            (user_id, message),
        )
        cur.execute("UPDATE progress SET notified = 1 WHERE id = ?", (task["id"],))
        if user_row:
            send_email_alert(user_row["email"], "Missed task deadline", f"Hi {user_row['name']},\n\n{message}")


def _check_all_deadlines_job():
    """APScheduler job: runs daily across every user so overdue-task alerts don't depend on someone opening the app."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT DISTINCT user_id FROM progress WHERE due_date IS NOT NULL")
    for row in cur.fetchall():
        _check_deadlines_for_user(cur, row["user_id"])
    conn.commit()
    conn.close()


STUDY_REMINDER_MESSAGES = [
    "You haven't logged any study activity today. A short session now keeps your streak alive.",
    "Reminder: today's tasks on your roadmap are still waiting for you.",
    "Don't lose momentum -- even {hours} focused minutes today keeps you on track.",
]


def _send_study_reminders_job():
    """
    APScheduler job: once a day, nudges any student who hasn't logged
    activity yet today with an in-app notification. The frontend's browser
    Notification permission (see api.js) turns this into a native OS
    notification for students who've opted in, even if the tab isn't focused.
    Capped to one reminder per user per day via last_reminder_date.
    """
    import random
    today = datetime.utcnow().date().isoformat()
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT user_id, daily_study_hours, last_activity_date, last_reminder_date
        FROM student_profiles
    """)
    for row in cur.fetchall():
        if row["last_activity_date"] == today:
            continue  # already studied today, no nudge needed
        if row["last_reminder_date"] == today:
            continue  # already reminded today
        message = random.choice(STUDY_REMINDER_MESSAGES).format(hours=row["daily_study_hours"] or 1)
        cur.execute(
            "INSERT INTO notifications (user_id, type, message) VALUES (?, 'study_reminder', ?)",
            (row["user_id"], message),
        )
        cur.execute(
            "UPDATE student_profiles SET last_reminder_date = ? WHERE user_id = ?",
            (today, row["user_id"]),
        )
    conn.commit()
    conn.close()


_scheduler_started = False


def _start_scheduler():
    global _scheduler_started
    if _scheduler_started:
        return
    scheduler = BackgroundScheduler()
    scheduler.add_job(_check_all_deadlines_job, "interval", hours=24, next_run_time=datetime.utcnow())
    # Runs at 6pm UTC daily -- a reasonable "you still have time to study today" nudge point.
    # Also fires once at startup so the feature is visible immediately without waiting a day.
    scheduler.add_job(_send_study_reminders_job, "cron", hour=18, minute=0)
    scheduler.add_job(_send_study_reminders_job, "date", run_date=datetime.utcnow() + timedelta(seconds=15))
    scheduler.start()
    _scheduler_started = True


@app.get("/api/notifications", response_model=list[NotificationItem], tags=["Notifications"])
def get_notifications(user_id: int = Depends(get_current_user_id)):
    """Also runs an on-demand deadline check for this user, so alerts show up immediately rather than waiting for the next scheduled run."""
    conn = get_connection()
    cur = conn.cursor()
    _check_deadlines_for_user(cur, user_id)
    conn.commit()
    cur.execute("SELECT * FROM notifications WHERE user_id = ? ORDER BY id DESC LIMIT 50", (user_id,))
    rows = cur.fetchall()
    conn.close()
    return [NotificationItem(id=r["id"], type=r["type"], message=r["message"], is_read=bool(r["is_read"]), created_at=r["created_at"]) for r in rows]


@app.post("/api/notifications/{notification_id}/read", tags=["Notifications"])
def mark_notification_read(notification_id: int, user_id: int = Depends(get_current_user_id)):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("UPDATE notifications SET is_read = 1 WHERE id = ? AND user_id = ?", (notification_id, user_id))
    conn.commit()
    conn.close()
    return {"message": "Marked as read."}


DISTRACTION_MESSAGES = [
    "Don't waste your time on {site} -- come back and finish today's task with your learning planner.",
    "Noticed you're on {site} during study time. Your roadmap is waiting -- let's get back to it.",
    "{site} can wait. A few more minutes here keeps your streak alive.",
]


@app.post("/api/notifications/distraction", response_model=NotificationItem, tags=["Notifications"])
def log_distraction(payload: DistractionPingRequest, user_id: int = Depends(get_current_user_id)):
    """
    Called by the frontend's optional 'Focus Mode' when it detects the browser
    tab lost focus (e.g. the student switched to a social media tab) during a
    declared study session. Note: a website can only see its OWN tab's focus
    state -- it cannot see activity in a separate native app -- so this is a
    browser-tab-level nudge, not full device-level monitoring.
    """
    import random
    message = random.choice(DISTRACTION_MESSAGES).format(site=payload.site or "that site")
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("INSERT INTO notifications (user_id, type, message) VALUES (?, 'distraction', ?)", (user_id, message))
    conn.commit()
    notif_id = cur.lastrowid
    cur.execute("SELECT * FROM notifications WHERE id = ?", (notif_id,))
    row = cur.fetchone()
    conn.close()
    return NotificationItem(id=row["id"], type=row["type"], message=row["message"], is_read=bool(row["is_read"]), created_at=row["created_at"])


# =========================================================================
# STREAK AND BADGES HELPERS
# =========================================================================

def _update_streak_and_badges(conn, cur, user_id: int):
    """
    Called whenever a task is marked completed.
    Updates daily study streak, awards badges, and sends notifications.
    """
    today_str = date.today().isoformat()
    yesterday_str = (date.today() - timedelta(days=1)).isoformat()

    # 1. Fetch profile streak data
    cur.execute("SELECT current_streak, longest_streak, last_activity_date FROM student_profiles WHERE user_id = ?", (user_id,))
    profile = cur.fetchone()
    if not profile:
        return

    current_streak = profile["current_streak"] or 0
    longest_streak = profile["longest_streak"] or 0
    last_activity = profile["last_activity_date"]

    # 2. Update streak based on last activity
    if last_activity == today_str:
        # Already active today, streak remains same
        pass
    elif last_activity == yesterday_str:
        # Consecutive day activity
        current_streak += 1
        longest_streak = max(current_streak, longest_streak)
        last_activity = today_str
    else:
        # Reset streak to 1
        current_streak = 1
        longest_streak = max(current_streak, longest_streak)
        last_activity = today_str

    cur.execute("""
        UPDATE student_profiles
        SET current_streak = ?, longest_streak = ?, last_activity_date = ?
        WHERE user_id = ?
    """, (current_streak, longest_streak, last_activity, user_id))

    # Helper to insert a badge and notify
    def award_badge(badge_code: str, name: str, desc: str):
        try:
            cur.execute("""
                INSERT INTO badges (user_id, badge_code, badge_name, description)
                VALUES (?, ?, ?, ?)
            """, (user_id, badge_code, name, desc))
            # Send notification
            cur.execute("""
                INSERT INTO notifications (user_id, type, message)
                VALUES (?, 'phase', ?)
            """, (user_id, f"Congratulations! You've earned the '{name}' badge!"))
        except sqlite3.IntegrityError:
            # Already awarded
            pass

    # 3. Check Badge Rules
    # Rule 1: Completed first task -> "First Step"
    cur.execute("SELECT COUNT(*) as count FROM progress WHERE user_id = ? AND is_completed = 1", (user_id,))
    completed_tasks = cur.fetchone()["count"]
    if completed_tasks >= 1:
        award_badge("first_step", "First Step", "Completed your very first task on your learning journey!")

    # Rule 2: Consistency (3-day streak) -> "Consistency"
    if current_streak >= 3:
        award_badge("streak_3", "Consistency", "Maintained a 3-day learning streak!")

    # Rule 3: Dedicated (7-day streak) -> "Dedicated"
    if current_streak >= 7:
        award_badge("streak_7", "Dedicated", "Maintained a 7-day learning streak!")


# =========================================================================
# CERTIFICATES
# =========================================================================

@app.get("/api/certificate/{plan_id}", response_model=CertificateResponse, tags=["Certificates"])
def get_certificate(plan_id: int, user_id: int = Depends(get_current_user_id)):
    """Fetch certificate metadata if the learning plan's roadmap is fully completed."""
    conn = get_connection()
    cur = conn.cursor()

    # 1. Verify plan exists and user owns it
    cur.execute("SELECT career_name, created_at FROM learning_plans WHERE id = ? AND user_id = ?", (plan_id, user_id))
    plan = cur.fetchone()
    if not plan:
        conn.close()
        raise HTTPException(status_code=404, detail="Learning plan not found.")

    # 2. Check if all phases are completed
    cur.execute("SELECT COUNT(*) as count FROM phases WHERE learning_plan_id = ?", (plan_id,))
    total_phases = cur.fetchone()["count"]

    cur.execute("SELECT COUNT(*) as count FROM phases WHERE learning_plan_id = ? AND status = 'completed'", (plan_id,))
    completed_phases = cur.fetchone()["count"]

    if total_phases == 0 or completed_phases < total_phases:
        conn.close()
        raise HTTPException(status_code=400, detail="You must complete all phases and pass their tests before generating a certificate.")

    # 3. Get student name
    cur.execute("SELECT name FROM student_profiles WHERE user_id = ?", (user_id,))
    profile = cur.fetchone()
    student_name = profile["name"] if profile and profile["name"] else "Graduate"

    # Get last phase completion date
    cur.execute("""
        SELECT completed_at FROM test_attempts 
        WHERE phase_id IN (SELECT id FROM phases WHERE learning_plan_id = ?) AND status = 'passed'
        ORDER BY id DESC LIMIT 1
    """, (plan_id,))
    test_attempt = cur.fetchone()
    completed_at = test_attempt["completed_at"] if test_attempt and test_attempt["completed_at"] else date.today().isoformat()

    # Generate unique certificate verification code on-the-fly
    import hashlib
    h = hashlib.sha256(f"{user_id}-{plan_id}-{completed_at}".encode())
    cert_code = f"TR-{h.hexdigest()[:12].upper()}"

    conn.close()
    return CertificateResponse(
        student_name=student_name,
        career_name=plan["career_name"],
        completed_at=completed_at[:10],
        certificate_code=cert_code,
    )


# =========================================================================
# LEADERBOARD
# =========================================================================

@app.get("/api/leaderboard", response_model=LeaderboardResponse, tags=["Leaderboard"])
def get_leaderboard(user_id: int = Depends(get_current_user_id)):
    """
    Ranks all students by a simple points formula: streak days + (badges x 5)
    + (completed phases x 10). Top 20 shown; the caller is flagged with
    is_you even if they fall outside the top 20 is not included -- only
    ranks within the returned list are marked.
    """
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT
            sp.user_id,
            COALESCE(sp.name, u.name) AS name,
            COALESCE(sp.current_streak, 0) AS current_streak,
            COALESCE(sp.longest_streak, 0) AS longest_streak,
            (SELECT COUNT(*) FROM badges b WHERE b.user_id = sp.user_id) AS badge_count,
            (SELECT COUNT(*) FROM phases p WHERE p.user_id = sp.user_id AND p.status = 'completed') AS phases_completed
        FROM student_profiles sp
        JOIN users u ON u.id = sp.user_id
    """)
    rows = cur.fetchall()
    conn.close()

    scored = []
    for r in rows:
        points = r["current_streak"] + r["badge_count"] * 5 + r["phases_completed"] * 10
        scored.append({
            "user_id": r["user_id"], "name": r["name"], "current_streak": r["current_streak"],
            "longest_streak": r["longest_streak"], "badge_count": r["badge_count"],
            "phases_completed": r["phases_completed"], "points": points,
        })
    scored.sort(key=lambda x: x["points"], reverse=True)

    entries = [
        LeaderboardEntry(
            rank=i + 1, name=s["name"] or "Student", current_streak=s["current_streak"],
            longest_streak=s["longest_streak"], badge_count=s["badge_count"],
            phases_completed=s["phases_completed"], points=s["points"], is_you=(s["user_id"] == user_id),
        )
        for i, s in enumerate(scored[:20])
    ]
    return LeaderboardResponse(entries=entries)


# =========================================================================
# MENTOR / TEACHER DASHBOARD
# =========================================================================

@app.post("/api/mentor/link", tags=["Mentor"])
def link_to_mentor(payload: MentorLinkRequest, user_id: int = Depends(get_current_user_id)):
    """A student enters their mentor's code to join that mentor's cohort view."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT id FROM users WHERE mentor_code = ? AND role = 'mentor'", (payload.mentor_code.upper(),))
    mentor = cur.fetchone()
    if not mentor:
        conn.close()
        raise HTTPException(status_code=404, detail="No mentor found with that code.")

    cur.execute("SELECT id FROM student_profiles WHERE user_id = ?", (user_id,))
    if not cur.fetchone():
        conn.close()
        raise HTTPException(status_code=400, detail="Complete your student profile before linking to a mentor.")

    cur.execute("UPDATE student_profiles SET mentor_id = ? WHERE user_id = ?", (mentor["id"], user_id))
    conn.commit()
    conn.close()
    return {"message": "Linked to mentor successfully."}


@app.get("/api/mentor/dashboard", response_model=MentorDashboardResponse, tags=["Mentor"])
def mentor_dashboard(user_id: int = Depends(get_current_mentor_id)):
    """Mentor-only: lists every student who has linked to this mentor's code, with progress summaries."""
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("SELECT mentor_code FROM users WHERE id = ?", (user_id,))
    mentor_code = cur.fetchone()["mentor_code"] or ""

    cur.execute("""
        SELECT sp.user_id, COALESCE(sp.name, u.name) AS name, u.email, sp.career_goal,
               COALESCE(sp.current_streak, 0) AS current_streak, COALESCE(sp.longest_streak, 0) AS longest_streak,
               sp.last_activity_date
        FROM student_profiles sp
        JOIN users u ON u.id = sp.user_id
        WHERE sp.mentor_id = ?
    """, (user_id,))
    student_rows = cur.fetchall()

    students = []
    for s in student_rows:
        cur.execute("SELECT COUNT(*) c FROM progress WHERE user_id = ?", (s["user_id"],))
        total_tasks = cur.fetchone()["c"]
        cur.execute("SELECT COUNT(*) c FROM progress WHERE user_id = ? AND is_completed = 1", (s["user_id"],))
        done_tasks = cur.fetchone()["c"]
        pct = round((done_tasks / total_tasks) * 100, 1) if total_tasks else 0.0

        cur.execute("SELECT COUNT(*) c FROM phases WHERE user_id = ? AND status = 'completed'", (s["user_id"],))
        phases_completed = cur.fetchone()["c"]

        students.append(MentorStudentSummary(
            user_id=s["user_id"], name=s["name"] or "Student", email=s["email"], career_goal=s["career_goal"],
            progress_percentage=pct, current_streak=s["current_streak"], longest_streak=s["longest_streak"],
            phases_completed=phases_completed, last_activity_date=s["last_activity_date"],
        ))

    conn.close()
    return MentorDashboardResponse(mentor_code=mentor_code, students=students)


# =========================================================================
# STATIC FRONTEND (serves the ../frontend folder)
# =========================================================================

FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "..", "frontend")

if os.path.isdir(FRONTEND_DIR):
    app.mount("/css", StaticFiles(directory=os.path.join(FRONTEND_DIR, "css")), name="css")
    app.mount("/js", StaticFiles(directory=os.path.join(FRONTEND_DIR, "js")), name="js")

    @app.get("/", tags=["Frontend"])
    def serve_home():
        return FileResponse(os.path.join(FRONTEND_DIR, "index.html"))

    @app.get("/{page_name}.html", tags=["Frontend"])
    def serve_page(page_name: str):
        file_path = os.path.join(FRONTEND_DIR, f"{page_name}.html")
        if os.path.isfile(file_path):
            return FileResponse(file_path)
        raise HTTPException(status_code=404, detail="Page not found.")
