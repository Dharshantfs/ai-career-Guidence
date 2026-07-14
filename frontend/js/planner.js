/* =========================================================================
   planner.js
   Powers learning-planner.html:
     - Figures out which career to plan for (selected career or profile's
       career_goal) using GET /api/dashboard.
     - If a plan already exists, renders it straight away.
     - Otherwise shows a "Generate" button that calls
       POST /api/learning-plan/generate and renders the result.
   ========================================================================= */

document.addEventListener("DOMContentLoaded", async () => {
  Auth.requireLogin();

  const noCareerState = document.getElementById("noCareerState");
  const generateCard = document.getElementById("generateCard");
  const loadingCard = document.getElementById("loadingCard");
  const planWrap = document.getElementById("planWrap");
  const errorBanner = document.getElementById("errorBanner");
  const generateBtn = document.getElementById("generateBtn");
  const regenerateBtn = document.getElementById("regenerateBtn");

  let careerName = null;
  let careerId = null;

  try {
    const dashboard = await apiRequest("/api/dashboard");

    if (dashboard.learning_plan) {
      renderPlan(dashboard.learning_plan);
      return;
    }

    if (dashboard.selected_career) {
      careerName = dashboard.selected_career.career_name;
      careerId = dashboard.selected_career.id;
    } else if (dashboard.profile && dashboard.profile.career_goal) {
      careerName = dashboard.profile.career_goal;
    }

    if (!careerName) {
      noCareerState.classList.remove("hidden");
      return;
    }

    document.getElementById("careerNameText").textContent = careerName;
    generateCard.classList.remove("hidden");
  } catch (err) {
    noCareerState.classList.remove("hidden");
    return;
  }

  async function generatePlan() {
    hideBanner(errorBanner);
    generateCard.classList.add("hidden");
    loadingCard.classList.remove("hidden");

    try {
      const plan = await apiRequest("/api/learning-plan/generate", {
        method: "POST",
        body: { career_id: careerId || undefined, career_name: careerId ? undefined : careerName },
      });
      renderPlan(plan);
    } catch (err) {
      generateCard.classList.remove("hidden");
      showBanner(errorBanner, err.message);
    } finally {
      loadingCard.classList.add("hidden");
    }
  }

  generateBtn.addEventListener("click", generatePlan);
  regenerateBtn.addEventListener("click", () => {
    planWrap.classList.add("hidden");
    generateCard.classList.remove("hidden");
  });

  function renderPlan(plan) {
    document.getElementById("planCareerName").textContent = plan.career_name;

    const trail = document.getElementById("planTrail");
    trail.innerHTML = ["Daily", "Weekly", "Monthly"].map((label, i) => `
      <div class="waypoint">
        <span class="wp-label">Stage ${i + 1}</span>
        <span class="wp-title">${label} focus</span>
      </div>
    `).join("");

    fillList("dailyList", plan.daily_plan);
    fillList("weeklyList", plan.weekly_plan);
    fillList("monthlyList", plan.monthly_roadmap);
    fillList("resourcesList", plan.resources);

    const chipsWrap = document.getElementById("skillsChips");
    chipsWrap.innerHTML = (plan.skills_to_learn || [])
      .map((s) => `<span class="skill-chip">${escapeHtml(s)}</span>`)
      .join("");

    document.getElementById("practiceProjectText").textContent = plan.practice_project || "";

    planWrap.classList.remove("hidden");
  }

  function fillList(elementId, items) {
    const el = document.getElementById(elementId);
    el.innerHTML = (items || []).map((item) => `<li style="margin-bottom:6px;">${escapeHtml(item)}</li>`).join("");
  }

  function escapeHtml(str) {
    const div = document.createElement("div");
    div.textContent = str == null ? "" : String(str);
    return div.innerHTML;
  }
});
