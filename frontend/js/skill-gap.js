/* =========================================================================
   skill-gap.js
   Powers skill-gap.html:
     1. Loads the student's selected career (via /api/dashboard).
     2. "Analyze" -> POST /api/skill-gap/analyze -> renders matched/missing
        skill chips + a plain-English summary.
     3. "Recommend courses" -> POST /api/skill-gap/courses -> renders one
        suggested course/tutorial/certification per missing skill.
     4. If an analysis (and courses) already exist, shows them immediately
        instead of making the student regenerate on every visit.
   ========================================================================= */

document.addEventListener("DOMContentLoaded", async () => {
  Auth.requireLogin();

  const noCareerState = document.getElementById("noCareerState");
  const analyzeCard = document.getElementById("analyzeCard");
  const careerNameText = document.getElementById("careerNameText");
  const errorBanner = document.getElementById("errorBanner");
  const analyzeBtn = document.getElementById("analyzeBtn");
  const reanalyzeBtn = document.getElementById("reanalyzeBtn");
  const loadingAnalysisCard = document.getElementById("loadingAnalysisCard");
  const resultsWrap = document.getElementById("resultsWrap");
  const resultCareerName = document.getElementById("resultCareerName");
  const summaryText = document.getElementById("summaryText");
  const matchedSkillsWrap = document.getElementById("matchedSkillsWrap");
  const missingSkillsWrap = document.getElementById("missingSkillsWrap");
  const getCoursesBtn = document.getElementById("getCoursesBtn");
  const loadingCoursesCard = document.getElementById("loadingCoursesCard");
  const courseList = document.getElementById("courseList");
  const allCaughtUpText = document.getElementById("allCaughtUpText");

  let currentSkillGapId = null;

  // Step 1: does the student have a selected career?
  let selectedCareerName = null;
  try {
    const dashboard = await apiRequest("/api/dashboard");
    if (dashboard.selected_career) {
      selectedCareerName = dashboard.selected_career.career_name;
    }
  } catch (_) { /* fall through to noCareerState below */ }

  if (!selectedCareerName) {
    noCareerState.classList.remove("hidden");
    return;
  }
  analyzeCard.classList.remove("hidden");
  careerNameText.textContent = selectedCareerName;

  // Step 2: has an analysis already been run? Show it immediately.
  try {
    const existing = await apiRequest("/api/skill-gap/latest");
    if (existing) {
      renderAnalysis(existing);
      // Also try to show any previously-generated course recommendations
      try {
        const courses = await apiRequest(`/api/skill-gap/courses/${existing.id}`);
        if (courses.courses && courses.courses.length > 0) renderCourses(courses);
      } catch (_) { /* none generated yet, that's fine */ }
    }
  } catch (_) { /* no analysis yet, that's fine */ }

  analyzeBtn.addEventListener("click", () => runAnalysis());
  reanalyzeBtn.addEventListener("click", () => runAnalysis());

  async function runAnalysis() {
    hideBanner(errorBanner);
    resultsWrap.classList.add("hidden");
    loadingAnalysisCard.classList.remove("hidden");
    analyzeBtn.disabled = true;
    reanalyzeBtn.disabled = true;

    try {
      const data = await apiRequest("/api/skill-gap/analyze", { method: "POST", body: {} });
      renderAnalysis(data);
    } catch (err) {
      showBanner(errorBanner, err.message);
    } finally {
      loadingAnalysisCard.classList.add("hidden");
      analyzeBtn.disabled = false;
      reanalyzeBtn.disabled = false;
    }
  }

  function renderAnalysis(data) {
    currentSkillGapId = data.id;
    resultCareerName.textContent = data.career_name;
    summaryText.textContent = data.summary;

    matchedSkillsWrap.innerHTML = data.matched_skills.length
      ? data.matched_skills.map((s) => `<span class="skill-chip skill-chip-matched">✓ ${escapeHtml(s)}</span>`).join("")
      : `<p class="hint" style="margin:0;">No matched skills yet — that's okay, everyone starts somewhere.</p>`;

    missingSkillsWrap.innerHTML = data.missing_skills.length
      ? data.missing_skills.map((s) => `<span class="skill-chip skill-chip-missing">${escapeHtml(s)}</span>`).join("")
      : `<p class="hint" style="margin:0;">None — you're covered on every required skill.</p>`;

    allCaughtUpText.classList.toggle("hidden", data.missing_skills.length !== 0);
    getCoursesBtn.classList.toggle("hidden", data.missing_skills.length === 0);
    courseList.innerHTML = "";
    resultsWrap.classList.remove("hidden");
  }

  getCoursesBtn.addEventListener("click", async () => {
    if (!currentSkillGapId) return;
    hideBanner(errorBanner);
    courseList.innerHTML = "";
    loadingCoursesCard.classList.remove("hidden");
    getCoursesBtn.disabled = true;

    try {
      const data = await apiRequest("/api/skill-gap/courses", {
        method: "POST",
        body: { skill_gap_id: currentSkillGapId },
      });
      renderCourses(data);
    } catch (err) {
      showBanner(errorBanner, err.message);
    } finally {
      loadingCoursesCard.classList.add("hidden");
      getCoursesBtn.disabled = false;
    }
  });

  function renderCourses(data) {
    if (!data.courses || data.courses.length === 0) {
      courseList.innerHTML = `<p class="hint">No course recommendations yet.</p>`;
      return;
    }
    courseList.innerHTML = data.courses.map((c) => `
      <div class="course-item">
        <div class="course-item-head">
          <span class="skill-chip skill-chip-missing">${escapeHtml(c.skill_name)}</span>
          <span class="phase-badge">${escapeHtml(c.resource_type)}</span>
        </div>
        <h4 class="mt-0" style="margin-bottom:2px;">${escapeHtml(c.title)}</h4>
        <p class="hint" style="margin-bottom:6px;">${escapeHtml(c.provider)}</p>
        <p style="margin-bottom:8px;">${escapeHtml(c.description)}</p>
        ${c.url ? `<a href="${escapeAttr(c.url)}" target="_blank" rel="noopener noreferrer" class="btn btn-secondary">Visit resource</a>` : ""}
      </div>
    `).join("");
  }

  function escapeHtml(str) {
    const div = document.createElement("div");
    div.textContent = str == null ? "" : String(str);
    return div.innerHTML;
  }
  function escapeAttr(str) {
    return escapeHtml(str).replace(/"/g, "&quot;");
  }
});
