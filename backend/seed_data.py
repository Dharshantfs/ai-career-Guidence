"""
seed_data.py
------------
Optional helper script that inserts one sample user + profile so you can
log in and explore the app immediately without registering first.

Run once, after the server has been started at least one time (so the
.db file and tables exist):

    python seed_data.py

Sample login created:
    email:    demo@student.com
    password: demo1234
"""

from database import init_db, get_connection
from auth_utils import hash_password

init_db()

conn = get_connection()
cur = conn.cursor()

cur.execute("SELECT id FROM users WHERE email = ?", ("demo@student.com",))
existing = cur.fetchone()

if existing:
    print("Demo user already exists (demo@student.com). Skipping seed.")
else:
    cur.execute(
        "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
        ("Demo Student", "demo@student.com", hash_password("demo1234")),
    )
    user_id = cur.lastrowid

    cur.execute("""
        INSERT INTO student_profiles
            (user_id, name, education, department, college, current_year,
             skills, interests, daily_study_hours, career_goal)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        user_id, "Demo Student", "B.Tech", "Information Technology",
        "Demo College of Engineering", "3rd Year",
        "HTML, CSS, JavaScript, Python, Basic SQL",
        "Web Development, Artificial Intelligence, Robotics",
        3.0, None,  # no career goal set -> AI advisor questions will trigger
    ))

    conn.commit()
    print("Seed complete!")
    print("Login with:  email = demo@student.com  |  password = demo1234")

conn.close()
