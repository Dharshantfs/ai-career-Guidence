"""
database.py
------------
Handles the SQLite connection and creates all tables used by the app.

Tables:
    users             -> login credentials
    student_profiles  -> the profile form each student fills in
    careers           -> AI-recommended careers for a student (top 3 + the chosen one)
    learning_plans    -> the AI-generated study plan tied to a chosen career
    progress          -> individual checklist tasks a student can tick off
"""

import sqlite3
import os

# The .db file lives next to this script, inside backend/
DB_PATH = os.path.join(os.path.dirname(__file__), "learning_planner.db")


def get_connection():
    """
    Open a new SQLite connection.
    check_same_thread=False lets FastAPI use the same connection object
    across the async request-handling threads used by uvicorn's threadpool.
    row_factory lets us access columns by name (row["name"]) instead of index.
    """
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    """
    Creates all tables if they do not already exist.
    Safe to call every time the app starts.
    """
    conn = get_connection()
    cur = conn.cursor()

    # ---------- USERS ----------
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            created_at TEXT DEFAULT (datetime('now'))
        )
    """)

    # ---------- STUDENT PROFILES ----------
    cur.execute("""
        CREATE TABLE IF NOT EXISTS student_profiles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL UNIQUE,
            name TEXT,
            education TEXT,
            department TEXT,
            college TEXT,
            current_year TEXT,
            skills TEXT,
            interests TEXT,
            daily_study_hours REAL,
            career_goal TEXT,
            current_streak INTEGER DEFAULT 0,
            longest_streak INTEGER DEFAULT 0,
            last_activity_date TEXT,
            updated_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
    """)

    # ---------- CAREERS (AI recommendations + the one the student picks) ----------
    cur.execute("""
        CREATE TABLE IF NOT EXISTS careers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            career_name TEXT NOT NULL,
            description TEXT,
            required_skills TEXT,
            future_scope TEXT,
            reason TEXT,
            is_selected INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
    """)

    # ---------- LEARNING PLANS ----------
    cur.execute("""
        CREATE TABLE IF NOT EXISTS learning_plans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            career_id INTEGER,
            career_name TEXT,
            daily_plan TEXT,       -- JSON text
            weekly_plan TEXT,      -- JSON text
            monthly_roadmap TEXT,  -- JSON text
            skills_to_learn TEXT,  -- JSON text
            resources TEXT,        -- JSON text
            practice_project TEXT, -- JSON text
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY (career_id) REFERENCES careers(id) ON DELETE SET NULL
        )
    """)

    # ---------- PROGRESS (checklist items derived from a learning plan) ----------
    cur.execute("""
        CREATE TABLE IF NOT EXISTS progress (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            learning_plan_id INTEGER NOT NULL,
            task_name TEXT NOT NULL,
            task_type TEXT,          -- 'daily' | 'weekly' | 'monthly' | 'skill' | 'project'
            is_completed INTEGER DEFAULT 0,
            completed_at TEXT,
            phase_id INTEGER,        -- NULL for legacy/non-phased tasks
            due_date TEXT,           -- ISO date string; used by the deadline-alert job
            notified INTEGER DEFAULT 0,  -- prevents duplicate overdue notifications
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY (learning_plan_id) REFERENCES learning_plans(id) ON DELETE CASCADE
        )
    """)

    # ---------- PHASES (multi-month roadmap: Basics -> Intermediate -> Advanced ...) ----------
    cur.execute("""
        CREATE TABLE IF NOT EXISTS phases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            learning_plan_id INTEGER NOT NULL,
            phase_order INTEGER NOT NULL,       -- 1, 2, 3...
            phase_name TEXT NOT NULL,
            description TEXT,
            duration_weeks INTEGER NOT NULL,
            focus_skills TEXT,                  -- JSON array
            weekly_tasks TEXT,                  -- JSON array; materialized into `progress` rows on activation
            project_brief TEXT,                 -- what the phase-end project should demonstrate
            start_date TEXT,
            end_date TEXT,
            status TEXT DEFAULT 'locked',       -- locked | active | project_review | project_approved | test_failed | completed
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY (learning_plan_id) REFERENCES learning_plans(id) ON DELETE CASCADE
        )
    """)

    # ---------- PROJECT SUBMISSIONS (one phase can have several attempts) ----------
    cur.execute("""
        CREATE TABLE IF NOT EXISTS project_submissions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            phase_id INTEGER NOT NULL,
            submission_type TEXT,       -- 'code' | 'link'
            content TEXT NOT NULL,      -- pasted code OR a GitHub/live link
            status TEXT DEFAULT 'pending',   -- pending | needs_revision | approved
            ai_summary TEXT,
            ai_errors TEXT,             -- JSON array of {issue, why, fix}
            ai_score INTEGER,           -- 0-100 quality score from the reviewer
            submitted_at TEXT DEFAULT (datetime('now')),
            reviewed_at TEXT,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY (phase_id) REFERENCES phases(id) ON DELETE CASCADE
        )
    """)

    # ---------- TEST ATTEMPTS (proctored 25-mark phase-end test) ----------
    cur.execute("""
        CREATE TABLE IF NOT EXISTS test_attempts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            phase_id INTEGER NOT NULL,
            questions TEXT NOT NULL,      -- JSON array (with correct answers, server-side only)
            answers TEXT,                 -- JSON array of the student's picks
            total_marks INTEGER DEFAULT 25,
            score INTEGER,
            violations INTEGER DEFAULT 0, -- count of tab-switch / minimize / blur events
            status TEXT DEFAULT 'in_progress',  -- in_progress | passed | failed | auto_submitted
            started_at TEXT DEFAULT (datetime('now')),
            completed_at TEXT,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY (phase_id) REFERENCES phases(id) ON DELETE CASCADE
        )
    """)

    # ---------- NOTIFICATIONS (deadline alerts + focus-mode distraction nudges) ----------
    cur.execute("""
        CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            type TEXT NOT NULL,        -- 'deadline' | 'distraction' | 'test' | 'phase'
            message TEXT NOT NULL,
            is_read INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
    """)

    # ---------- BADGES (streak achievements, completion trophies) ----------
    cur.execute("""
        CREATE TABLE IF NOT EXISTS badges (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            badge_code TEXT NOT NULL,
            badge_name TEXT NOT NULL,
            description TEXT,
            awarded_at TEXT DEFAULT (datetime('now')),
            UNIQUE(user_id, badge_code),
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
    """)

    # ---------- PASSWORD RESET TOKENS (forgot-password flow) ----------
    cur.execute("""
        CREATE TABLE IF NOT EXISTS password_reset_tokens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            token TEXT NOT NULL UNIQUE,
            expires_at TEXT NOT NULL,
            used INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
    """)

    # ---------- SKILL GAP ANALYSES (current skills vs a target career's required skills) ----------
    cur.execute("""
        CREATE TABLE IF NOT EXISTS skill_gaps (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            career_id INTEGER,
            career_name TEXT NOT NULL,
            matched_skills TEXT,     -- JSON array: skills the student already has
            missing_skills TEXT,     -- JSON array: skills still needed for the target career
            summary TEXT,            -- short plain-English readout of the gap
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY (career_id) REFERENCES careers(id) ON DELETE SET NULL
        )
    """)

    # ---------- COURSE RECOMMENDATIONS (generated per missing skill, tied to a skill_gaps run) ----------
    cur.execute("""
        CREATE TABLE IF NOT EXISTS course_recommendations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            skill_gap_id INTEGER NOT NULL,
            skill_name TEXT NOT NULL,
            title TEXT NOT NULL,
            provider TEXT,
            resource_type TEXT,     -- 'course' | 'tutorial' | 'certification'
            url TEXT,
            description TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY (skill_gap_id) REFERENCES skill_gaps(id) ON DELETE CASCADE
        )
    """)

    # ---------- MENTOR/TEACHER support on users ----------
    existing_user_cols = {row["name"] for row in cur.execute("PRAGMA table_info(users)").fetchall()}
    for col, ddl in [
        ("role", "ALTER TABLE users ADD COLUMN role TEXT DEFAULT 'student'"),
        ("mentor_code", "ALTER TABLE users ADD COLUMN mentor_code TEXT"),
    ]:
        if col not in existing_user_cols:
            cur.execute(ddl)

    # student_profiles gets a pointer to the mentor a student has linked to
    existing_profile_cols_pre = {row["name"] for row in cur.execute("PRAGMA table_info(student_profiles)").fetchall()}
    if "mentor_id" not in existing_profile_cols_pre:
        cur.execute("ALTER TABLE student_profiles ADD COLUMN mentor_id INTEGER REFERENCES users(id)")

    # ---------- project_submissions: file upload support ----------
    existing_submission_cols = {row["name"] for row in cur.execute("PRAGMA table_info(project_submissions)").fetchall()}
    for col, ddl in [
        ("file_path", "ALTER TABLE project_submissions ADD COLUMN file_path TEXT"),
        ("file_name", "ALTER TABLE project_submissions ADD COLUMN file_name TEXT"),
    ]:
        if col not in existing_submission_cols:
            cur.execute(ddl)

    # ---------- Lightweight migration for DBs created before this update ----------
    existing_cols = {row["name"] for row in cur.execute("PRAGMA table_info(progress)").fetchall()}
    for col, ddl in [
        ("phase_id", "ALTER TABLE progress ADD COLUMN phase_id INTEGER"),
        ("due_date", "ALTER TABLE progress ADD COLUMN due_date TEXT"),
        ("notified", "ALTER TABLE progress ADD COLUMN notified INTEGER DEFAULT 0"),
    ]:
        if col not in existing_cols:
            cur.execute(ddl)

    existing_profile_cols = {row["name"] for row in cur.execute("PRAGMA table_info(student_profiles)").fetchall()}
    for col, ddl in [
        ("current_streak", "ALTER TABLE student_profiles ADD COLUMN current_streak INTEGER DEFAULT 0"),
        ("longest_streak", "ALTER TABLE student_profiles ADD COLUMN longest_streak INTEGER DEFAULT 0"),
        ("last_activity_date", "ALTER TABLE student_profiles ADD COLUMN last_activity_date TEXT"),
        ("last_reminder_date", "ALTER TABLE student_profiles ADD COLUMN last_reminder_date TEXT"),
    ]:
        if col not in existing_profile_cols:
            cur.execute(ddl)

    conn.commit()
    conn.close()
    print(f"[database] SQLite ready at {DB_PATH}")
