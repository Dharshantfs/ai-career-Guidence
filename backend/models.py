"""
models.py
---------
Pydantic schemas used to validate incoming requests and shape outgoing
responses. Keeping these separate from database.py keeps validation logic
(what a valid request looks like) apart from storage logic (how it's saved).
"""

from pydantic import BaseModel, EmailStr, Field
from typing import Optional, List


# ---------------- AUTH ----------------

class RegisterRequest(BaseModel):
    name: str = Field(..., min_length=2, max_length=100)
    email: EmailStr
    password: str = Field(..., min_length=6, max_length=100)
    role: str = Field(default="student", pattern="^(student|mentor)$")


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ForgotPasswordResponse(BaseModel):
    message: str
    # Only populated when email sending isn't configured (local/dev use), so the
    # reset flow still works without an SMTP provider set up. Never sent once
    # EMAIL_ALERTS_ENABLED is true - see main.py.
    reset_link: Optional[str] = None


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str = Field(..., min_length=6, max_length=100)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: int
    name: str
    email: str
    role: str = "student"
    mentor_code: Optional[str] = None


# ---------------- STUDENT PROFILE ----------------

class ProfileRequest(BaseModel):
    name: str
    education: str
    department: str
    college: str
    current_year: str
    skills: str            # comma separated string, e.g. "Python, HTML, CSS"
    interests: str          # comma separated string, e.g. "Web Dev, AI, Robotics"
    daily_study_hours: float
    career_goal: Optional[str] = None   # optional - if empty, AI advisor kicks in


class ProfileResponse(ProfileRequest):
    user_id: int


# ---------------- CAREER ADVISOR ----------------

class CareerAdvisorQuestionsRequest(BaseModel):
    """Answers to the simple follow-up questions asked when career_goal is empty."""
    favorite_subjects: str
    strengths: str
    preferred_work_style: str   # e.g. "team-based", "independent", "research", "hands-on"


class CareerOption(BaseModel):
    career_name: str
    description: str
    required_skills: List[str]
    future_scope: str
    reason: str


class CareerRecommendationResponse(BaseModel):
    careers: List[CareerOption]


class SelectCareerRequest(BaseModel):
    career_id: int


# ---------------- SKILL GAP ANALYSIS ----------------

class SkillGapAnalyzeRequest(BaseModel):
    # Optional: analyze against a specific recommended career instead of the
    # currently-selected one (e.g. comparing before choosing).
    career_id: Optional[int] = None


class SkillGapResponse(BaseModel):
    id: int
    career_name: str
    matched_skills: List[str]
    missing_skills: List[str]
    summary: str
    created_at: str


class CourseRecommendationRequest(BaseModel):
    skill_gap_id: Optional[int] = None   # defaults to the most recent analysis


class CourseRecommendationItem(BaseModel):
    id: int
    skill_name: str
    title: str
    provider: str
    resource_type: str   # course | tutorial | certification
    url: str
    description: str


class CourseRecommendationResponse(BaseModel):
    skill_gap_id: int
    courses: List[CourseRecommendationItem]


# ---------------- LEARNING PLAN ----------------

class GeneratePlanRequest(BaseModel):
    career_id: Optional[int] = None
    career_name: Optional[str] = None   # allow generating directly from a known career goal


class LearningPlanResponse(BaseModel):
    id: int
    career_name: str
    daily_plan: List[str]
    weekly_plan: List[str]
    monthly_roadmap: List[str]
    skills_to_learn: List[str]
    resources: List[str]
    practice_project: str


# ---------------- PROGRESS ----------------

class UpdateProgressRequest(BaseModel):
    progress_id: int
    is_completed: bool


class ProgressItem(BaseModel):
    id: int
    task_name: str
    task_type: str
    is_completed: bool


# ---------------- DASHBOARD ----------------

class BadgeResponseItem(BaseModel):
    badge_code: str
    badge_name: str
    description: str
    awarded_at: str


class DashboardResponse(BaseModel):
    profile: Optional[dict]
    selected_career: Optional[dict]
    learning_plan: Optional[dict]
    progress: List[ProgressItem]
    progress_percentage: float
    has_phases: bool = False
    current_streak: int = 0
    longest_streak: int = 0
    badges: List[BadgeResponseItem] = Field(default_factory=list)


# ---------------- PHASED ROADMAP ----------------

class GeneratePhasesRequest(BaseModel):
    learning_plan_id: int


class PhaseTask(BaseModel):
    id: int
    task_name: str
    is_completed: bool
    due_date: Optional[str] = None


class PhaseResponse(BaseModel):
    id: int
    phase_order: int
    phase_name: str
    description: str
    duration_weeks: int
    focus_skills: List[str]
    project_brief: str
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    status: str
    tasks: List[PhaseTask] = Field(default_factory=list)
    task_progress_percentage: float = 0.0


# ---------------- PROJECT SUBMISSION & REVIEW ----------------

class ProjectSubmitRequest(BaseModel):
    phase_id: int
    submission_type: str = Field(..., pattern="^(code|link)$")
    content: str = Field(..., min_length=1, max_length=20000)


class ProjectError(BaseModel):
    issue: str
    why: str
    fix: str


class ProjectSubmissionResponse(BaseModel):
    id: int
    phase_id: int
    status: str
    ai_summary: str
    ai_errors: List[ProjectError]
    ai_score: int
    submitted_at: str
    file_name: Optional[str] = None


# ---------------- PROCTORED PHASE TEST ----------------

class TestStartRequest(BaseModel):
    phase_id: int


class TestQuestionForStudent(BaseModel):
    index: int
    question: str
    options: List[str]


class TestStartResponse(BaseModel):
    attempt_id: int
    phase_name: str
    total_marks: int
    questions: List[TestQuestionForStudent]
    instructions: List[str]


class TestAnswer(BaseModel):
    index: int
    selected_option: int


class TestViolationRequest(BaseModel):
    attempt_id: int
    reason: str = "tab_switch_or_minimize"
    # The student's currently-selected answers at the moment of the violation.
    # Sent so that if this violation triggers an auto-submit, grading reflects
    # what was actually answered instead of being forced to zero.
    answers: List[TestAnswer] = Field(default_factory=list)


class TestSubmitRequest(BaseModel):
    attempt_id: int
    answers: List[TestAnswer]


class TestResultResponse(BaseModel):
    attempt_id: int
    score: int
    total_marks: int
    passed: bool
    violations: int
    status: str
    next_phase_unlocked: bool


# ---------------- NOTIFICATIONS ----------------

class NotificationItem(BaseModel):
    id: int
    type: str
    message: str
    is_read: bool
    created_at: str


class DistractionPingRequest(BaseModel):
    site: str = Field(..., max_length=100)


# ---------------- AI CHAT ----------------

class ChatMessage(BaseModel):
    role: str    # "user" or "assistant"
    text: str


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000)
    history: List[ChatMessage] = Field(default_factory=list)


class ChatResponse(BaseModel):
    reply: str


# ---------------- CERTIFICATE ----------------

class CertificateResponse(BaseModel):
    student_name: str
    career_name: str
    completed_at: str
    certificate_code: str


# ---------------- LEADERBOARD ----------------

class LeaderboardEntry(BaseModel):
    rank: int
    name: str
    current_streak: int
    longest_streak: int
    badge_count: int
    phases_completed: int
    points: int
    is_you: bool = False


class LeaderboardResponse(BaseModel):
    entries: List[LeaderboardEntry]


# ---------------- MENTOR / TEACHER DASHBOARD ----------------

class MentorLinkRequest(BaseModel):
    mentor_code: str = Field(..., min_length=4, max_length=20)


class MentorStudentSummary(BaseModel):
    user_id: int
    name: str
    email: str
    career_goal: Optional[str] = None
    progress_percentage: float
    current_streak: int
    longest_streak: int
    phases_completed: int
    last_activity_date: Optional[str] = None


class MentorDashboardResponse(BaseModel):
    mentor_code: str
    students: List[MentorStudentSummary]
