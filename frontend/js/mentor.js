/* =========================================================================
   mentor.js
   Loads GET /api/mentor/dashboard (mentor-role accounts only) and renders
   the mentor's code plus a table of linked students and their progress.
   ========================================================================= */

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str == null ? "" : String(str);
  return div.innerHTML;
}

document.addEventListener("DOMContentLoaded", async () => {
  Auth.requireLogin();

  const user = Auth.getUser();
  if (!user || user.role !== "mentor") {
    // Not a mentor account - this page isn't for them.
    window.location.href = "dashboard.html";
    return;
  }

  const emptyState = document.getElementById("emptyState");
  const studentsCard = document.getElementById("studentsCard");
  const studentsBody = document.getElementById("studentsBody");
  const codeDisplay = document.getElementById("mentorCodeDisplay");

  try {
    const data = await apiRequest("/api/mentor/dashboard");
    codeDisplay.textContent = data.mentor_code;

    if (!data.students || data.students.length === 0) {
      emptyState.classList.remove("hidden");
      return;
    }

    studentsCard.classList.remove("hidden");
    studentsBody.innerHTML = data.students.map((s) => `
      <tr style="border-bottom:1px solid var(--border,#eee);">
        <td style="padding:10px 8px;">${escapeHtml(s.name)}</td>
        <td style="padding:10px 8px;">${escapeHtml(s.email)}</td>
        <td style="padding:10px 8px;">${escapeHtml(s.career_goal || "—")}</td>
        <td style="padding:10px 8px;">${s.progress_percentage}%</td>
        <td style="padding:10px 8px;">${s.current_streak}d (best ${s.longest_streak}d)</td>
        <td style="padding:10px 8px;">${s.phases_completed}</td>
        <td style="padding:10px 8px;">${escapeHtml(s.last_activity_date || "—")}</td>
      </tr>
    `).join("");
  } catch (err) {
    codeDisplay.textContent = user.mentor_code || "";
    emptyState.classList.remove("hidden");
    emptyState.querySelector("h3").textContent = "Couldn't load your cohort";
    emptyState.querySelector("p").textContent = err.message;
  }
});
