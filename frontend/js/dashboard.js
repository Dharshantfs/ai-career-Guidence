/* =========================================================================
   dashboard.js
   Powers dashboard.html. Pulls everything from a single endpoint,
   GET /api/dashboard, and renders:
     - profile summary
     - selected career (if any)
     - progress percentage + progress bar
     - a checklist of tasks (grouped by daily/weekly/monthly/skill/project)
       that toggle complete/incomplete via POST /api/progress/update.
   ========================================================================= */

const TASK_TYPE_LABELS = {
  daily: "Daily tasks",
  weekly: "Weekly tasks",
  monthly: "Monthly roadmap",
  skill: "Skills to learn",
  project: "Practice project",
};

document.addEventListener("DOMContentLoaded", async () => {
  Auth.requireLogin();

  const emptyState = document.getElementById("emptyState");
  const dashboardContent = document.getElementById("dashboardContent");

  try {
    const data = await apiRequest("/api/dashboard");

    if (!data.profile) {
      emptyState.classList.remove("hidden");
      return;
    }

    dashboardContent.classList.remove("hidden");
    renderProfile(data.profile);
    renderCareer(data.selected_career);
    renderProgressSummary(data.progress_percentage, data.progress);
    renderTasks(data.progress);
    updateCongratsCard(data);
    renderStreaksAndBadges(data);
  } catch (err) {
    emptyState.classList.remove("hidden");
  }

  function renderProfile(profile) {
    document.getElementById("profileName").textContent = profile.name;
    const details = document.getElementById("profileDetails");
    const rows = [
      ["Education", `${profile.education} — ${profile.department}`],
      ["College", profile.college],
      ["Current year", profile.current_year],
      ["Skills", profile.skills],
      ["Interests", profile.interests],
      ["Daily study hours", `${profile.daily_study_hours} hrs/day`],
    ];
    details.innerHTML = rows.map(([label, value]) => `
      <div class="dash-label">${label}</div>
      <div class="dash-value">${escapeHtml(value || "—")}</div>
    `).join("");
  }

  function renderCareer(career) {
    if (!career) {
      document.getElementById("noCareerCard").classList.remove("hidden");
      return;
    }
    document.getElementById("careerCard").classList.remove("hidden");
    document.getElementById("careerName").textContent = career.career_name;
    document.getElementById("careerDescription").textContent = career.description;
    document.getElementById("careerSkills").innerHTML = (career.required_skills || [])
      .map((s) => `<span class="skill-chip">${escapeHtml(s)}</span>`).join("");
  }

  function renderProgressSummary(percentage, progress) {
    document.getElementById("progressPercent").textContent = percentage || 0;
    document.getElementById("progressFill").style.width = `${percentage || 0}%`;
    const subtext = document.getElementById("progressSubtext");
    if (!progress || progress.length === 0) {
      subtext.textContent = "No tasks yet — generate a learning plan to get started";
    } else {
      const done = progress.filter((p) => p.is_completed).length;
      subtext.textContent = `${done} of ${progress.length} tasks completed`;
    }
  }

  function renderTasks(progress) {
    const wrap = document.getElementById("taskGroups");
    if (!progress || progress.length === 0) {
      document.getElementById("noPlanCard").classList.remove("hidden");
      return;
    }

    const grouped = {};
    progress.forEach((task) => {
      if (!grouped[task.task_type]) grouped[task.task_type] = [];
      grouped[task.task_type].push(task);
    });

    wrap.innerHTML = "";
    Object.keys(TASK_TYPE_LABELS).forEach((type) => {
      if (!grouped[type]) return;
      const group = document.createElement("div");
      group.className = "task-group";
      group.innerHTML = `
        <span class="task-group-label">${TASK_TYPE_LABELS[type]}</span>
        ${grouped[type].map((task) => `
          <div class="task-item ${task.is_completed ? "completed" : ""}" data-task-id="${task.id}">
            <div class="task-checkbox">${task.is_completed ? checkmarkSvg() : ""}</div>
            <div class="task-text">${escapeHtml(task.task_name)}</div>
          </div>
        `).join("")}
      `;
      wrap.appendChild(group);
    });

    wrap.querySelectorAll(".task-item").forEach((item) => {
      item.addEventListener("click", () => toggleTask(item));
    });
  }

  async function toggleTask(itemEl) {
    const taskId = parseInt(itemEl.getAttribute("data-task-id"));
    const willComplete = !itemEl.classList.contains("completed");

    // Optimistic UI update
    itemEl.classList.toggle("completed", willComplete);
    const checkbox = itemEl.querySelector(".task-checkbox");
    checkbox.innerHTML = willComplete ? checkmarkSvg() : "";

    try {
      await apiRequest("/api/progress/update", {
        method: "POST",
        body: { progress_id: taskId, is_completed: willComplete },
      });
      // Refresh the top progress summary from the server for accuracy
      const data = await apiRequest("/api/dashboard");
      renderProgressSummary(data.progress_percentage, data.progress);
      updateCongratsCard(data);
      renderStreaksAndBadges(data);
    } catch (err) {
      // Revert on failure
      itemEl.classList.toggle("completed", !willComplete);
      checkbox.innerHTML = !willComplete ? checkmarkSvg() : "";
      alert("Could not update progress: " + err.message);
    }
  }

  function checkmarkSvg() {
    return `<svg width="12" height="12" viewBox="0 0 24 24" fill="none"><path d="M5 13l4 4L19 7" stroke="white" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/></svg>`;
  }

  function escapeHtml(str) {
    const div = document.createElement("div");
    div.textContent = str == null ? "" : String(str);
    return div.innerHTML;
  }

  function updateCongratsCard(data) {
    const card = document.getElementById("congratsCard");
    if (!card) return;

    const progress = data.progress;
    if (!progress || progress.length === 0) {
      card.classList.add("hidden");
      return;
    }

    const done = progress.filter((p) => p.is_completed).length;
    const allDone = done === progress.length;

    if (allDone) {
      const titleEl = document.getElementById("congratsTitle");
      const textEl = document.getElementById("congratsText");
      const btnEl = document.getElementById("congratsBtn");

      if (data.has_phases) {
        titleEl.textContent = "Phase Tasks Completed! 🚀";
        textEl.textContent = "All weekly tasks for this phase are done! Head over to your Roadmap to submit your phase-end project and take the proctored test.";
        btnEl.textContent = "Go to my Roadmap";
        btnEl.href = "phases.html";
      } else {
        titleEl.textContent = "All Tasks Completed! 🎉";
        textEl.textContent = "Congratulations on finishing your learning plan! Take the next step and break it into a structured, multi-phase roadmap with projects and proctored tests.";
        btnEl.textContent = "Unlock Phased Roadmap";
        btnEl.href = "phases.html";
      }
      card.classList.remove("hidden");
    } else {
      card.classList.add("hidden");
    }
  }

  function renderStreaksAndBadges(data) {
    document.getElementById("currentStreakVal").textContent = `${data.current_streak || 0} day${data.current_streak === 1 ? "" : "s"}`;
    document.getElementById("longestStreakVal").textContent = data.longest_streak || 0;

    const badgesContainer = document.getElementById("badgesContainer");
    if (!badgesContainer) return;

    if (!data.badges || data.badges.length === 0) {
      badgesContainer.innerHTML = `<span class="hint">Earn streaks and complete phases to unlock badges!</span>`;
      return;
    }

    badgesContainer.innerHTML = data.badges.map((b) => `
      <div class="skill-chip" style="background:rgba(204,107,60,0.15); border:1px solid var(--accent); color:var(--accent); display:inline-flex; align-items:center; gap:5px; padding:6px 12px; font-weight:600;" title="${escapeHtml(b.description)}">
        🏅 ${escapeHtml(b.badge_name)}
      </div>
    `).join("");
  }
});
