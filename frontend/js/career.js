/* =========================================================================
   career.js
   Powers career-advisor.html:
     1. Checks the student's profile - if a career_goal already exists,
        shows a shortcut card to the Learning Planner.
     2. Submits the questionnaire -> POST /api/career/recommend -> renders
        3 career cards.
     3. Selecting a card -> POST /api/career/select -> redirect to planner.
   ========================================================================= */

document.addEventListener("DOMContentLoaded", async () => {
  Auth.requireLogin();

  const errorBanner = document.getElementById("errorBanner");
  const questionForm = document.getElementById("questionForm");
  const submitBtn = document.getElementById("submitBtn");
  const loadingCard = document.getElementById("loadingCard");
  const resultsWrap = document.getElementById("resultsWrap");
  const careerList = document.getElementById("careerList");

  // Check profile for an existing career goal
  try {
    const profile = await apiRequest("/api/profile");
    if (profile.career_goal) {
      document.getElementById("goalKnownCard").classList.remove("hidden");
      document.getElementById("goalKnownText").textContent = profile.career_goal;
    }
  } catch (_) {
    // No profile saved yet -> send them there first
    window.location.href = "profile.html";
    return;
  }

  // Already-generated (not yet selected) recommendations? Show them immediately.
  try {
    const existingOptions = await apiRequest("/api/career/options");
    if (existingOptions && existingOptions.length > 0) {
      renderCareers(existingOptions);
    }
  } catch (_) { /* ignore - just means none generated yet */ }

  questionForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    hideBanner(errorBanner);
    submitBtn.disabled = true;
    submitBtn.textContent = "Thinking...";
    loadingCard.classList.remove("hidden");
    resultsWrap.classList.add("hidden");

    try {
      const data = await apiRequest("/api/career/recommend", {
        method: "POST",
        body: {
          favorite_subjects: document.getElementById("favorite_subjects").value.trim(),
          strengths: document.getElementById("strengths").value.trim(),
          preferred_work_style: document.getElementById("preferred_work_style").value,
        },
      });

      // Re-fetch with ids so we can select one
      const withIds = await apiRequest("/api/career/options");
      renderCareers(withIds.length ? withIds : data.careers);
    } catch (err) {
      showBanner(errorBanner, err.message);
    } finally {
      loadingCard.classList.add("hidden");
      submitBtn.disabled = false;
      submitBtn.textContent = "Get my 5 career recommendations";
    }
  });

  function renderCareers(careers) {
    careerList.innerHTML = "";
    careers.forEach((career) => {
      const skillsHtml = (career.required_skills || [])
        .map((s) => `<span class="skill-chip">${escapeHtml(s)}</span>`)
        .join("");

      const card = document.createElement("div");
      card.className = "career-card";
      card.innerHTML = `
        <span class="career-meta">AI Recommended</span>
        <h3>${escapeHtml(career.career_name)}</h3>
        <p>${escapeHtml(career.description)}</p>
        <p><strong>Required skills</strong></p>
        <div style="margin-bottom:14px;">${skillsHtml}</div>
        <p><strong>Future scope:</strong> ${escapeHtml(career.future_scope)}</p>
        <p><strong>Why this fits you:</strong> ${escapeHtml(career.reason)}</p>
        <button class="btn btn-primary" data-select-career="${career.id || ""}">Choose this career</button>
      `;
      careerList.appendChild(card);
    });
    resultsWrap.classList.remove("hidden");

    careerList.querySelectorAll("[data-select-career]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const careerId = btn.getAttribute("data-select-career");
        if (!careerId) {
          alert("This option can't be selected — please regenerate recommendations.");
          return;
        }
        btn.disabled = true;
        btn.textContent = "Selecting...";
        try {
          await apiRequest("/api/career/select", { method: "POST", body: { career_id: parseInt(careerId) } });
          window.location.href = "learning-planner.html";
        } catch (err) {
          alert(err.message);
          btn.disabled = false;
          btn.textContent = "Choose this career";
        }
      });
    });
  }

  function escapeHtml(str) {
    const div = document.createElement("div");
    div.textContent = str == null ? "" : String(str);
    return div.innerHTML;
  }
});
