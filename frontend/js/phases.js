/* =========================================================================
   phases.js
   Powers phases.html:
     - Loads / generates the phased roadmap (GET/POST /api/phases)
     - Renders phase cards with status-driven actions
     - Project submission + AI review modal
     - Proctored phase-end test (fullscreen + tab-switch detection)
     - "Focus Mode" tab-switch distraction nudges
   ========================================================================= */

const STATUS_LABELS = {
  locked: "Locked",
  active: "In progress",
  project_review: "Needs revision",
  project_approved: "Project approved — test unlocked",
  test_failed: "Test failed — retake available",
  completed: "Completed",
};
const STATUS_BADGE_CLASS = {
  locked: "b-locked",
  active: "b-active",
  project_review: "b-warn",
  project_approved: "b-completed",
  test_failed: "b-warn",
  completed: "b-completed",
};

let currentLearningPlanId = null;

document.addEventListener("DOMContentLoaded", async () => {
  Auth.requireLogin();
  await loadPhasesPage();
  setupSubmitModal();
  setupFocusMode();
});

async function loadPhasesPage() {
  const noPlanState = document.getElementById("noPlanState");
  const noPhasesState = document.getElementById("noPhasesState");
  const phasesList = document.getElementById("phasesList");
  const focusCard = document.getElementById("focusModeCard");

  noPlanState.classList.add("hidden");
  noPhasesState.classList.add("hidden");
  focusCard.classList.add("hidden");

  try {
    const dash = await apiRequest("/api/dashboard");
    if (!dash.learning_plan) {
      noPlanState.classList.remove("hidden");
      return;
    }
    currentLearningPlanId = dash.learning_plan.id;

    const phases = await apiRequest("/api/phases");
    if (!phases || phases.length === 0) {
      noPhasesState.classList.remove("hidden");
      document.getElementById("generatePhasesBtn").onclick = generatePhases;
      return;
    }
    focusCard.classList.remove("hidden");
    renderPhases(phases);

    const allCompleted = phases.length > 0 && phases.every((p) => p.status === "completed");
    const certCard = document.getElementById("certificateCard");
    if (certCard) {
      if (allCompleted) {
        document.getElementById("viewCertificateBtn").href = `certificate.html?plan_id=${currentLearningPlanId}`;
        certCard.classList.remove("hidden");
      } else {
        certCard.classList.add("hidden");
      }
    }
  } catch (err) {
    noPlanState.classList.remove("hidden");
  }
}

async function generatePhases() {
  const btn = document.getElementById("generatePhasesBtn");
  btn.disabled = true;
  btn.textContent = "Generating your roadmap...";
  try {
    const phases = await apiRequest("/api/phases/generate", {
      method: "POST",
      body: { learning_plan_id: currentLearningPlanId },
    });
    document.getElementById("noPhasesState").classList.add("hidden");
    document.getElementById("focusModeCard").classList.remove("hidden");
    renderPhases(phases);
  } catch (err) {
    btn.disabled = false;
    btn.textContent = "Generate phased roadmap";
    alert("Could not generate roadmap: " + err.message);
  }
}

function renderPhases(phases) {
  const wrap = document.getElementById("phasesList");
  wrap.innerHTML = "";

  phases.forEach((phase) => {
    const card = document.createElement("div");
    card.className = `phase-card status-${phase.status} ${phase.status === "locked" ? "locked" : ""}`;
    card.innerHTML = `
      <div class="phase-head">
        <div>
          <span class="phase-num">Phase ${phase.phase_order} · ${phase.duration_weeks} weeks</span>
          <h3 class="mt-0" style="margin-top:4px;">${escapeHtml(phase.phase_name)}</h3>
        </div>
        <span class="phase-badge ${STATUS_BADGE_CLASS[phase.status] || ""}">${STATUS_LABELS[phase.status] || phase.status}</span>
      </div>
      <p class="phase-meta">${escapeHtml(phase.description)}</p>
      <div>${(phase.focus_skills || []).map((s) => `<span class="skill-chip">${escapeHtml(s)}</span>`).join("")}</div>
      ${phase.status !== "locked" ? `
        <div class="phase-tasks">
          <div class="progress-track" style="margin-bottom:8px;"><div class="progress-fill" style="width:${phase.task_progress_percentage}%;"></div></div>
          <p class="hint" style="margin:0 0 10px;">${phase.task_progress_percentage}% of this phase's weekly tasks completed</p>
          <div class="task-group-tasks" data-phase-tasks="${phase.id}"></div>
        </div>
        <div class="project-feedback" data-feedback-slot="${phase.id}"></div>
        <div class="phase-actions" data-actions="${phase.id}"></div>
      ` : `<p class="hint" style="margin:10px 0 0;">Complete the previous phase's project and test to unlock this one.</p>`}
    `;
    wrap.appendChild(card);

    if (phase.status !== "locked") {
      renderTasks(card.querySelector(`[data-phase-tasks="${phase.id}"]`), phase.tasks);
      renderActions(card.querySelector(`[data-actions="${phase.id}"]`), phase);
      if (["project_review", "project_approved", "test_failed", "completed"].includes(phase.status)) {
        loadFeedback(phase.id, card.querySelector(`[data-feedback-slot="${phase.id}"]`));
      }
    }
  });
}

function renderTasks(container, tasks) {
  if (!tasks || tasks.length === 0) {
    container.innerHTML = `<p class="hint">No weekly tasks yet.</p>`;
    return;
  }
  container.innerHTML = tasks.map((t) => `
    <div class="task-item ${t.is_completed ? "completed" : ""}" data-task-id="${t.id}">
      <div class="task-checkbox">${t.is_completed ? checkmarkSvg() : ""}</div>
      <div class="task-text">${escapeHtml(t.task_name)}${t.due_date ? ` <span class="hint" style="display:inline;">— due ${t.due_date}</span>` : ""}</div>
    </div>
  `).join("");
  container.querySelectorAll(".task-item").forEach((item) => {
    item.addEventListener("click", () => toggleTask(item));
  });
}

async function toggleTask(itemEl) {
  const taskId = parseInt(itemEl.getAttribute("data-task-id"));
  const willComplete = !itemEl.classList.contains("completed");
  itemEl.classList.toggle("completed", willComplete);
  itemEl.querySelector(".task-checkbox").innerHTML = willComplete ? checkmarkSvg() : "";
  try {
    await apiRequest("/api/progress/update", { method: "POST", body: { progress_id: taskId, is_completed: willComplete } });
    await loadPhasesPage();
  } catch (err) {
    itemEl.classList.toggle("completed", !willComplete);
    itemEl.querySelector(".task-checkbox").innerHTML = !willComplete ? checkmarkSvg() : "";
    alert("Could not update task: " + err.message);
  }
}

function renderActions(container, phase) {
  let html = "";
  const allTasksDone = phase.tasks.length === 0 || phase.task_progress_percentage >= 100;

  if (phase.status === "active") {
    if (allTasksDone) {
      html += `<button class="btn btn-primary" data-open-submit="${phase.id}">Submit project</button>`;
    } else {
      html += `<button class="btn btn-primary" disabled title="Tick off every weekly task above first">Submit project</button>
                <p class="hint" style="margin:6px 0 0;">Tick off all of this phase's weekly tasks to unlock project submission.</p>`;
    }
  }
  if (phase.status === "project_review") {
    html += `<button class="btn btn-primary" data-open-submit="${phase.id}">Resubmit project</button>`;
  }
  if (phase.status === "project_approved" || phase.status === "test_failed") {
    html += `<button class="btn btn-dark" data-start-test="${phase.id}">${phase.status === "test_failed" ? "Retake test" : "Start phase test"}</button>`;
  }
  container.innerHTML = html;

  const submitBtn = container.querySelector(`[data-open-submit]`);
  if (submitBtn) submitBtn.addEventListener("click", () => openSubmitModal(phase));

  const testBtn = container.querySelector(`[data-start-test]`);
  if (testBtn) testBtn.addEventListener("click", () => startTest(phase));
}

async function loadFeedback(phaseId, slot) {
  try {
    const sub = await apiRequest(`/api/projects/${phaseId}`);
    if (!sub) return;
    const approved = sub.status === "approved";
    slot.innerHTML = `
      <div class="review-summary ${approved ? "approved" : "needs-revision"}">
        <strong>${approved ? "Approved" : "Needs revision"}</strong> (score: ${sub.ai_score}/100) — ${escapeHtml(sub.ai_summary)}
      </div>
      ${!approved && sub.ai_errors && sub.ai_errors.length ? sub.ai_errors.map((e) => `
        <div class="error-item">
          <div class="err-issue">⚠ ${escapeHtml(e.issue)}</div>
          <div class="err-why">Why: ${escapeHtml(e.why)}</div>
          <div class="err-fix">Fix: ${escapeHtml(e.fix)}</div>
        </div>
      `).join("") : ""}
    `;
  } catch (err) { /* no submission yet */ }
}

/* ---------------- Project submission modal ---------------- */

let submitPhaseContext = null;

function setupSubmitModal() {
  document.getElementById("cancelSubmitBtn").addEventListener("click", closeSubmitModal);
  document.getElementById("submissionType").addEventListener("change", (e) => {
    const isFile = e.target.value === "file";
    document.getElementById("submissionContentField").classList.toggle("hidden", isFile);
    document.getElementById("submissionFileField").classList.toggle("hidden", !isFile);
    document.getElementById("submissionContentLabel").textContent = e.target.value === "link" ? "Your GitHub / live link" : "Your code";
    document.getElementById("submissionContent").placeholder = e.target.value === "link"
      ? "https://github.com/you/your-project"
      : "Paste your project code here...";
  });
  document.getElementById("submitProjectBtn").addEventListener("click", submitProject);
}

function openSubmitModal(phase) {
  submitPhaseContext = phase;
  document.getElementById("submitModalTitle").textContent = `Submit project — ${phase.phase_name}`;
  document.getElementById("submitModalBrief").textContent = phase.project_brief;
  document.getElementById("submissionContent").value = "";
  hideBanner(document.getElementById("submitError"));
  document.getElementById("submitModalOverlay").classList.remove("hidden");
}

function closeSubmitModal() {
  document.getElementById("submitModalOverlay").classList.add("hidden");
  submitPhaseContext = null;
}

async function submitProject() {
  const type = document.getElementById("submissionType").value;
  const errBanner = document.getElementById("submitError");
  const btn = document.getElementById("submitProjectBtn");

  if (type === "file") {
    const fileInput = document.getElementById("submissionFile");
    const file = fileInput.files[0];
    if (!file) { showBanner(errBanner, "Please choose a file to upload."); return; }

    const formData = new FormData();
    formData.append("phase_id", submitPhaseContext.id);
    formData.append("file", file);

    btn.disabled = true;
    btn.textContent = "Reviewing with AI...";
    try {
      await apiUpload("/api/projects/submit-file", formData);
      closeSubmitModal();
      await loadPhasesPage();
    } catch (err) {
      showBanner(errBanner, err.message);
    } finally {
      btn.disabled = false;
      btn.textContent = "Submit for review";
    }
    return;
  }

  const content = document.getElementById("submissionContent").value.trim();
  if (!content) { showBanner(errBanner, "Please add your code or a link before submitting."); return; }

  btn.disabled = true;
  btn.textContent = "Reviewing with AI...";
  try {
    await apiRequest("/api/projects/submit", { method: "POST", body: { phase_id: submitPhaseContext.id, submission_type: type, content } });
    closeSubmitModal();
    await loadPhasesPage();
  } catch (err) {
    showBanner(errBanner, err.message);
  } finally {
    btn.disabled = false;
    btn.textContent = "Submit for review";
  }
}

/* ---------------- Proctored phase test ---------------- */

let testState = null;

async function startTest(phase) {
  try {
    const data = await apiRequest("/api/tests/start", { method: "POST", body: { phase_id: phase.id } });
    testState = { attemptId: data.attempt_id, answers: {}, violations: 0, ended: false };

    document.getElementById("testTitle").textContent = `${data.phase_name} — Phase Test (${data.total_marks} marks)`;
    document.getElementById("testWarningBanner").innerHTML = data.instructions.map((i) => `⚠ ${escapeHtml(i)}`).join("<br>");
    updateViolationDisplay();
    renderTestQuestions(data.questions);

    document.getElementById("testOverlay").classList.remove("hidden");
    document.getElementById("submitTestBtn").onclick = () => finishTest(false);

    document.documentElement.requestFullscreen?.().catch(() => {});
    document.addEventListener("visibilitychange", onTestVisibilityChange);
    document.addEventListener("fullscreenchange", onTestFullscreenChange);
  } catch (err) {
    alert("Could not start test: " + err.message);
  }
}

function renderTestQuestions(questions) {
  const wrap = document.getElementById("testQuestions");
  wrap.innerHTML = questions.map((q) => `
    <div class="test-question-card">
      <span class="q-index">Question ${q.index + 1}</span>
      <p style="color:var(--ink);margin-bottom:12px;">${escapeHtml(q.question)}</p>
      <div data-qwrap="${q.index}">
        ${q.options.map((opt, i) => `
          <div class="test-option" data-q="${q.index}" data-opt="${i}">${escapeHtml(opt)}</div>
        `).join("")}
      </div>
    </div>
  `).join("");

  wrap.querySelectorAll(".test-option").forEach((opt) => {
    opt.addEventListener("click", () => {
      const q = opt.getAttribute("data-q");
      const o = parseInt(opt.getAttribute("data-opt"));
      testState.answers[q] = o;
      wrap.querySelectorAll(`[data-qwrap="${q}"] .test-option`).forEach((el) => el.classList.remove("selected"));
      opt.classList.add("selected");
    });
  });
}

async function onTestVisibilityChange() {
  if (document.hidden && testState && !testState.ended) {
    await reportTestViolation();
  }
}

async function onTestFullscreenChange() {
  if (!document.fullscreenElement && testState && !testState.ended) {
    await reportTestViolation();
  }
}

async function reportTestViolation() {
  try {
    const answers = Object.keys(testState.answers).map((k) => ({ index: parseInt(k), selected_option: testState.answers[k] }));
    const res = await apiRequest("/api/tests/violation", { method: "POST", body: { attempt_id: testState.attemptId, answers } });
    testState.violations = res.violations;
    updateViolationDisplay();
    if (res.auto_submitted) {
      await finishTest(true, res);
    }
  } catch (err) { /* ignore transient errors during proctoring */ }
}

function updateViolationDisplay() {
  document.getElementById("violationCount").textContent = `Violations: ${testState.violations} / 3`;
}

async function finishTest(wasAutoSubmitted, autoResult) {
  if (!testState || testState.ended) return;
  testState.ended = true;
  document.removeEventListener("visibilitychange", onTestVisibilityChange);
  document.removeEventListener("fullscreenchange", onTestFullscreenChange);
  if (document.fullscreenElement) document.exitFullscreen?.().catch(() => {});

  document.getElementById("testOverlay").classList.add("hidden");

  if (wasAutoSubmitted) {
    const r = autoResult || {};
    const scoreLine = typeof r.score === "number" ? ` You scored ${r.score}/${r.total_marks} on the answers you'd selected.` : "";
    if (r.passed) {
      showTestResult(
        "Auto-submitted — but you passed! 🎉",
        `Too many tab-switches or minimizes were detected, so your test was auto-submitted.${scoreLine}${r.next_phase_unlocked ? " The next phase is now unlocked." : " That was the final phase — roadmap complete!"}`
      );
    } else {
      showTestResult(
        "Test auto-submitted",
        `Too many tab-switches or minimizes were detected, so your test was auto-submitted.${scoreLine} You can retake it once you're ready to stay focused for the full attempt.`
      );
    }
    await loadPhasesPage();
    return;
  }

  const answers = Object.keys(testState.answers).map((k) => ({ index: parseInt(k), selected_option: testState.answers[k] }));
  try {
    const result = await apiRequest("/api/tests/submit", { method: "POST", body: { attempt_id: testState.attemptId, answers } });
    if (result.passed) {
      showTestResult("You passed! 🎉", `Score: ${result.score}/${result.total_marks}.${result.next_phase_unlocked ? " The next phase is now unlocked." : " That was the final phase — roadmap complete!"}`);
    } else {
      showTestResult("Not quite there yet", `Score: ${result.score}/${result.total_marks}. Review this phase's material and retake the test when ready.`);
    }
  } catch (err) {
    showTestResult("Could not submit test", err.message);
  }
  await loadPhasesPage();
}

function showTestResult(title, body) {
  document.getElementById("testResultTitle").textContent = title;
  document.getElementById("testResultBody").textContent = body;
  document.getElementById("testResultOverlay").classList.remove("hidden");
  document.getElementById("closeTestResultBtn").onclick = () => {
    document.getElementById("testResultOverlay").classList.add("hidden");
  };
}

/* ---------------- Focus Mode (browser-tab-level distraction nudges) ---------------- */

let focusModeOn = false;
let focusHiddenTimer = null;
let lastPingAt = 0;

function setupFocusMode() {
  const btn = document.getElementById("focusToggleBtn");
  const status = document.getElementById("focusStatus");
  btn.addEventListener("click", () => {
    focusModeOn = !focusModeOn;
    status.textContent = focusModeOn ? "On" : "Off";
    status.classList.toggle("on", focusModeOn);
    btn.textContent = focusModeOn ? "Turn off" : "Turn on";
  });

  document.addEventListener("visibilitychange", () => {
    if (!focusModeOn) return;
    if (document.hidden) {
      focusHiddenTimer = setTimeout(async () => {
        const now = Date.now();
        if (now - lastPingAt < 60000) return; // throttle: at most one nudge per minute
        lastPingAt = now;
        try {
          const notif = await apiRequest("/api/notifications/distraction", { method: "POST", body: { site: "another tab" } });
          // best-effort toast; the notification bell will also pick this up
          console.log("[focus mode]", notif.message);
        } catch (err) { /* ignore */ }
      }, 5000); // only counts as a distraction if away for 5+ seconds
    } else if (focusHiddenTimer) {
      clearTimeout(focusHiddenTimer);
      focusHiddenTimer = null;
    }
  });
}

/* ---------------- small helpers ---------------- */

function checkmarkSvg() {
  return `<svg width="12" height="12" viewBox="0 0 24 24" fill="none"><path d="M5 13l4 4L19 7" stroke="white" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/></svg>`;
}
function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str == null ? "" : String(str);
  return div.innerHTML;
}
