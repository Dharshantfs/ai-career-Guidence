/* =========================================================================
   profile.js
   Loads any existing profile into the form (edit mode), and saves the
   form via POST /api/profile (which upserts on the backend). After a
   successful save with no career_goal set, sends the student to the
   Career Advisor; otherwise straight to the Learning Planner.
   ========================================================================= */

document.addEventListener("DOMContentLoaded", async () => {
  Auth.requireLogin();

  const currentUser = Auth.getUser();
  if (currentUser && currentUser.role === "mentor") {
    const card = document.getElementById("mentorLinkCard");
    if (card) card.classList.add("hidden");
  }

  const errorBanner = document.getElementById("errorBanner");
  const successBanner = document.getElementById("successBanner");
  const form = document.getElementById("profileForm");
  const submitBtn = document.getElementById("submitBtn");

  // Try to preload an existing profile so returning students can edit it
  try {
    const existing = await apiRequest("/api/profile");
    document.getElementById("name").value = existing.name || "";
    document.getElementById("education").value = existing.education || "";
    document.getElementById("department").value = existing.department || "";
    document.getElementById("college").value = existing.college || "";
    document.getElementById("current_year").value = existing.current_year || "";
    document.getElementById("skills").value = existing.skills || "";
    document.getElementById("interests").value = existing.interests || "";
    document.getElementById("daily_study_hours").value = existing.daily_study_hours || "";
    document.getElementById("career_goal").value = existing.career_goal || "";
  } catch (_) {
    // No profile yet - that's fine, the form just starts blank.
    const user = Auth.getUser();
    if (user) document.getElementById("name").value = user.name;
  }

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    hideBanner(errorBanner);
    hideBanner(successBanner);
    submitBtn.disabled = true;
    submitBtn.textContent = "Saving...";

    const payload = {
      name: document.getElementById("name").value.trim(),
      education: document.getElementById("education").value,
      department: document.getElementById("department").value.trim(),
      college: document.getElementById("college").value.trim(),
      current_year: document.getElementById("current_year").value,
      skills: document.getElementById("skills").value.trim(),
      interests: document.getElementById("interests").value.trim(),
      daily_study_hours: parseFloat(document.getElementById("daily_study_hours").value),
      career_goal: document.getElementById("career_goal").value.trim() || null,
    };

    try {
      const saved = await apiRequest("/api/profile", { method: "POST", body: payload });
      showBanner(successBanner, "Profile saved!");
      setTimeout(() => {
        window.location.href = saved.career_goal ? "learning-planner.html" : "career-advisor.html";
      }, 600);
    } catch (err) {
      showBanner(errorBanner, err.message);
      submitBtn.disabled = false;
      submitBtn.textContent = "Save profile & continue";
    }
  });

  const linkMentorBtn = document.getElementById("linkMentorBtn");
  const mentorLinkError = document.getElementById("mentorLinkError");
  const mentorLinkSuccess = document.getElementById("mentorLinkSuccess");
  if (linkMentorBtn) {
    linkMentorBtn.addEventListener("click", async () => {
      hideBanner(mentorLinkError);
      hideBanner(mentorLinkSuccess);
      const code = document.getElementById("mentorCode").value.trim();
      if (!code) { showBanner(mentorLinkError, "Enter a mentor code first."); return; }

      linkMentorBtn.disabled = true;
      try {
        await apiRequest("/api/mentor/link", { method: "POST", body: { mentor_code: code } });
        showBanner(mentorLinkSuccess, "Linked! Your mentor can now see your progress.");
      } catch (err) {
        showBanner(mentorLinkError, err.message);
      } finally {
        linkMentorBtn.disabled = false;
      }
    });
  }
});
