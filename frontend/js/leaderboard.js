/* =========================================================================
   leaderboard.js
   Loads GET /api/leaderboard and renders the ranked table. Points formula
   (streak days + badges*5 + completed phases*10) is computed server-side;
   this file only displays what comes back.
   ========================================================================= */

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str == null ? "" : String(str);
  return div.innerHTML;
}

document.addEventListener("DOMContentLoaded", async () => {
  Auth.requireLogin();

  const emptyState = document.getElementById("emptyState");
  const boardCard = document.getElementById("boardCard");
  const tbody = document.getElementById("leaderboardBody");

  try {
    const data = await apiRequest("/api/leaderboard");
    if (!data.entries || data.entries.length === 0) {
      emptyState.classList.remove("hidden");
      return;
    }

    boardCard.classList.remove("hidden");
    tbody.innerHTML = data.entries.map((e) => `
      <tr style="border-bottom:1px solid var(--border,#eee);${e.is_you ? "background:rgba(204,107,60,0.08);font-weight:600;" : ""}">
        <td style="padding:10px 8px;">${e.rank}</td>
        <td style="padding:10px 8px;">${escapeHtml(e.name)}${e.is_you ? " (you)" : ""}</td>
        <td style="padding:10px 8px;">${e.current_streak}d</td>
        <td style="padding:10px 8px;">${e.longest_streak}d</td>
        <td style="padding:10px 8px;">${e.badge_count}</td>
        <td style="padding:10px 8px;">${e.phases_completed}</td>
        <td style="padding:10px 8px;">${e.points}</td>
      </tr>
    `).join("");
  } catch (err) {
    emptyState.classList.remove("hidden");
    emptyState.querySelector("h3").textContent = "Couldn't load the leaderboard";
    emptyState.querySelector("p").textContent = err.message;
  }
});
