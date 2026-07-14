/* =========================================================================
   auth.js
   Handles the register.html and login.html forms. Whichever form exists
   on the current page is the one wired up (the other stays untouched).
   ========================================================================= */

document.addEventListener("DOMContentLoaded", () => {
  // If already logged in, no need to see the auth pages again
  if (Auth.isLoggedIn()) {
    window.location.href = "dashboard.html";
    return;
  }

  const errorBanner = document.getElementById("errorBanner");

  const registerForm = document.getElementById("registerForm");
  if (registerForm) {
    registerForm.addEventListener("submit", async (e) => {
      e.preventDefault();
      hideBanner(errorBanner);
      const submitBtn = document.getElementById("submitBtn");
      submitBtn.disabled = true;
      submitBtn.textContent = "Creating account...";

      try {
        const data = await apiRequest("/api/register", {
          method: "POST",
          skipAuth: true,
          body: {
            name: document.getElementById("name").value.trim(),
            email: document.getElementById("email").value.trim(),
            password: document.getElementById("password").value,
            role: document.getElementById("role") ? document.getElementById("role").value : "student",
          },
        });
        Auth.setSession(data.access_token, {
          user_id: data.user_id, name: data.name, email: data.email,
          role: data.role, mentor_code: data.mentor_code,
        });
        window.location.href = data.role === "mentor" ? "mentor-dashboard.html" : "profile.html";
      } catch (err) {
        showBanner(errorBanner, err.message);
        submitBtn.disabled = false;
        submitBtn.textContent = "Create account";
      }
    });
  }

  const forgotPasswordForm = document.getElementById("forgotPasswordForm");
  if (forgotPasswordForm) {
    const successBanner = document.getElementById("successBanner");
    const devLinkBox = document.getElementById("devLinkBox");
    const devLinkAnchor = document.getElementById("devLinkAnchor");

    forgotPasswordForm.addEventListener("submit", async (e) => {
      e.preventDefault();
      hideBanner(errorBanner);
      hideBanner(successBanner);
      devLinkBox.classList.add("hidden");
      const submitBtn = document.getElementById("submitBtn");
      submitBtn.disabled = true;
      submitBtn.textContent = "Sending...";

      try {
        const data = await apiRequest("/api/auth/forgot-password", {
          method: "POST",
          skipAuth: true,
          body: { email: document.getElementById("email").value.trim() },
        });
        showBanner(successBanner, data.message);
        if (data.reset_link) {
          devLinkAnchor.textContent = data.reset_link;
          devLinkAnchor.href = data.reset_link;
          devLinkBox.classList.remove("hidden");
        }
        forgotPasswordForm.reset();
      } catch (err) {
        showBanner(errorBanner, err.message);
      } finally {
        submitBtn.disabled = false;
        submitBtn.textContent = "Send reset link";
      }
    });
  }

  const resetPasswordForm = document.getElementById("resetPasswordForm");
  if (resetPasswordForm) {
    const successBanner = document.getElementById("successBanner");
    const params = new URLSearchParams(window.location.search);
    const token = params.get("token");
    if (!token) {
      showBanner(errorBanner, "This reset link is missing its token. Please request a new one from the Forgot Password page.");
      resetPasswordForm.querySelectorAll("input, button").forEach((el) => (el.disabled = true));
    }

    resetPasswordForm.addEventListener("submit", async (e) => {
      e.preventDefault();
      hideBanner(errorBanner);
      hideBanner(successBanner);
      const newPassword = document.getElementById("new_password").value;
      const confirmPassword = document.getElementById("confirm_password").value;
      if (newPassword !== confirmPassword) {
        showBanner(errorBanner, "Passwords don't match.");
        return;
      }
      const submitBtn = document.getElementById("submitBtn");
      submitBtn.disabled = true;
      submitBtn.textContent = "Resetting...";

      try {
        const data = await apiRequest("/api/auth/reset-password", {
          method: "POST",
          skipAuth: true,
          body: { token, new_password: newPassword },
        });
        showBanner(successBanner, `${data.message} Redirecting to log in...`);
        resetPasswordForm.reset();
        setTimeout(() => { window.location.href = "login.html"; }, 2000);
      } catch (err) {
        showBanner(errorBanner, err.message);
        submitBtn.disabled = false;
        submitBtn.textContent = "Reset password";
      }
    });
  }

  const loginForm = document.getElementById("loginForm");
  if (loginForm) {
    loginForm.addEventListener("submit", async (e) => {
      e.preventDefault();
      hideBanner(errorBanner);
      const submitBtn = document.getElementById("submitBtn");
      submitBtn.disabled = true;
      submitBtn.textContent = "Logging in...";

      try {
        const data = await apiRequest("/api/login", {
          method: "POST",
          skipAuth: true,
          body: {
            email: document.getElementById("email").value.trim(),
            password: document.getElementById("password").value,
          },
        });
        Auth.setSession(data.access_token, {
          user_id: data.user_id, name: data.name, email: data.email,
          role: data.role, mentor_code: data.mentor_code,
        });
        window.location.href = data.role === "mentor" ? "mentor-dashboard.html" : "dashboard.html";
      } catch (err) {
        showBanner(errorBanner, err.message);
        submitBtn.disabled = false;
        submitBtn.textContent = "Log in";
      }
    });
  }
});
