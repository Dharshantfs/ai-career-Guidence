-- =============================================================================
-- AI Learning Planner & Career Advisor — Database Schema (SQLite)
--
-- This file documents the schema for reference. In practice, the tables are
-- created automatically by backend/database.py's init_db() function the
-- first time the FastAPI server starts, so you do NOT need to run this
-- file manually. It's included here so the schema is easy to review,
-- and can be run manually against a fresh .db file if you ever want to
-- recreate the database by hand:
--
--   sqlite3 backend/learning_planner.db < database/schema.sql
-- =============================================================================

PRAGMA foreign_keys = ON;

-- Login credentials
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    created_at TEXT DEFAULT (datetime('now'))
);

-- One profile per student (1:1 with users)
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
    updated_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

-- AI-recommended careers. is_selected=1 marks the one the student chose.
CREATE TABLE IF NOT EXISTS careers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    career_name TEXT NOT NULL,
    description TEXT,
    required_skills TEXT,   -- JSON array, stored as text
    future_scope TEXT,
    reason TEXT,
    is_selected INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

-- One generated learning plan per (user, career) combo, most recent wins
CREATE TABLE IF NOT EXISTS learning_plans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    career_id INTEGER,
    career_name TEXT,
    daily_plan TEXT,        -- JSON array, stored as text
    weekly_plan TEXT,       -- JSON array, stored as text
    monthly_roadmap TEXT,   -- JSON array, stored as text
    skills_to_learn TEXT,   -- JSON array, stored as text
    resources TEXT,         -- JSON array, stored as text
    practice_project TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (career_id) REFERENCES careers(id) ON DELETE SET NULL
);

-- Individual checklist items generated from a learning plan's sections
CREATE TABLE IF NOT EXISTS progress (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    learning_plan_id INTEGER NOT NULL,
    task_name TEXT NOT NULL,
    task_type TEXT,          -- 'daily' | 'weekly' | 'monthly' | 'skill' | 'project'
    is_completed INTEGER DEFAULT 0,
    completed_at TEXT,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (learning_plan_id) REFERENCES learning_plans(id) ON DELETE CASCADE
);
