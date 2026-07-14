/* =========================================================================
   api.js
   Shared helper for every page: talks to the FastAPI backend, stores the
   login token, and provides small utilities pages reuse (auth guard,
   logout, showing errors). Loaded first, before any page-specific script.
   ========================================================================= */

const API_BASE = ""; // same origin as the FastAPI server (empty = relative URLs)

const Auth = {
  getToken() {
    return localStorage.getItem("alp_token");
  },
  getUser() {
    const raw = localStorage.getItem("alp_user");
    return raw ? JSON.parse(raw) : null;
  },
  setSession(token, user) {
    localStorage.setItem("alp_token", token);
    localStorage.setItem("alp_user", JSON.stringify(user));
  },
  clearSession() {
    localStorage.removeItem("alp_token");
    localStorage.removeItem("alp_user");
  },
  isLoggedIn() {
    return !!this.getToken();
  },
  /* Call at the top of any page that requires login. Redirects to login.html if not authenticated. */
  requireLogin() {
    if (!this.isLoggedIn()) {
      window.location.href = "login.html";
    }
  },
  logout() {
    this.clearSession();
    window.location.href = "login.html";
  },
};

/**
 * Wrapper around fetch() that:
 *  - prefixes the API base URL
 *  - attaches the Bearer token automatically (unless skipAuth is true)
 *  - parses JSON and throws a readable Error on non-2xx responses
 */
async function apiRequest(path, { method = "GET", body = null, skipAuth = false } = {}) {
  const headers = { "Content-Type": "application/json" };
  if (!skipAuth) {
    const token = Auth.getToken();
    if (token) headers["Authorization"] = `Bearer ${token}`;
  }

  const response = await fetch(`${API_BASE}${path}`, {
    method,
    headers,
    body: body ? JSON.stringify(body) : undefined,
  });

  let data = null;
  try {
    data = await response.json();
  } catch (_) {
    /* no JSON body, e.g. 204 responses */
  }

  if (!response.ok) {
    let message = `Request failed (${response.status})`;
    if (data && data.detail) {
      if (typeof data.detail === "string") {
        message = data.detail;
      } else if (Array.isArray(data.detail)) {
        // FastAPI/Pydantic validation errors come back as a list of {msg, loc, ...} objects.
        message = data.detail.map((e) => (e && e.msg) ? e.msg : JSON.stringify(e)).join(" ");
      } else {
        message = JSON.stringify(data.detail);
      }
    }
    // A 401 usually means the session token expired -> send back to login
    if (response.status === 401) {
      Auth.clearSession();
    }
    throw new Error(message);
  }

  return data;
}

/**
 * Like apiRequest, but sends a multipart/form-data body (for file uploads).
 * formData is a native FormData instance built by the caller.
 */
async function apiUpload(path, formData) {
  const headers = {};
  const token = Auth.getToken();
  if (token) headers["Authorization"] = `Bearer ${token}`;

  const response = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers,          // no Content-Type: the browser sets the multipart boundary itself
    body: formData,
  });

  let data = null;
  try {
    data = await response.json();
  } catch (_) {}

  if (!response.ok) {
    const message = (data && data.detail) || `Request failed (${response.status})`;
    if (response.status === 401) Auth.clearSession();
    throw new Error(typeof message === "string" ? message : JSON.stringify(message));
  }
  return data;
}

/* Small helper to show/hide the shared error and success banners used on forms */
function showBanner(el, message) {
  if (!el) return;
  el.textContent = message;
  el.classList.add("visible");
}
function hideBanner(el) {
  if (!el) return;
  el.classList.remove("visible");
}

/* Highlights the current page's nav link, if present */
document.addEventListener("DOMContentLoaded", () => {
  const current = window.location.pathname.split("/").pop() || "index.html";
  document.querySelectorAll(".nav-links a").forEach((link) => {
    if (link.getAttribute("href") === current) link.classList.add("active");
  });

  const nameSlot = document.querySelector("[data-user-name]");
  const user = Auth.getUser();
  if (nameSlot && user) nameSlot.textContent = user.name;

  const mentorNavLink = document.getElementById("mentorNavLink");
  if (mentorNavLink && user && user.role === "mentor") mentorNavLink.classList.remove("hidden");

  const logoutBtn = document.querySelector("[data-logout]");
  if (logoutBtn) logoutBtn.addEventListener("click", (e) => { e.preventDefault(); Auth.logout(); });

  initNotificationBell();
});

/* =========================================================================
   Notification bell — shown in the nav on every authenticated page.
   Surfaces missed-deadline alerts, phase/test updates, and focus-mode
   distraction nudges (GET /api/notifications).
   ========================================================================= */
function initNotificationBell() {
  const navLinks = document.querySelector(".nav-links");
  const logoutLi = document.querySelector("[data-logout]")?.closest("li");
  if (!navLinks || !logoutLi || !Auth.isLoggedIn()) return;

  initBrowserNotificationPrompt(navLinks, logoutLi);

  const bellLi = document.createElement("li");
  bellLi.className = "notif-bell-wrap";
  bellLi.innerHTML = `
    <button class="notif-bell-btn" id="notifBellBtn" aria-label="Notifications">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"/>
        <path d="M13.73 21a2 2 0 0 1-3.46 0"/>
      </svg>
      <span class="notif-badge hidden" id="notifBadge">0</span>
    </button>
    <div class="notif-dropdown" id="notifDropdown">
      <div class="notif-dropdown-head">Notifications</div>
      <div id="notifRows"><div class="notif-empty">Loading...</div></div>
    </div>
  `;
  navLinks.insertBefore(bellLi, logoutLi);

  const btn = document.getElementById("notifBellBtn");
  const dropdown = document.getElementById("notifDropdown");
  btn.addEventListener("click", async (e) => {
    e.stopPropagation();
    const willOpen = !dropdown.classList.contains("open");
    dropdown.classList.toggle("open", willOpen);
    if (willOpen) await refreshNotifications();
  });
  document.addEventListener("click", (e) => {
    if (!bellLi.contains(e.target)) dropdown.classList.remove("open");
  });

  refreshNotifications();
  setInterval(refreshNotifications, 60000); // poll every minute so deadline/test alerts show up without a page reload
}

async function refreshNotifications() {
  try {
    const notifs = await apiRequest("/api/notifications");
    maybeShowBrowserNotifications(notifs);
    const badge = document.getElementById("notifBadge");
    const rows = document.getElementById("notifRows");
    if (!badge || !rows) return;

    const unread = notifs.filter((n) => !n.is_read).length;
    badge.textContent = unread;
    badge.classList.toggle("hidden", unread === 0);

    if (notifs.length === 0) {
      rows.innerHTML = `<div class="notif-empty">You're all caught up.</div>`;
      return;
    }
    rows.innerHTML = notifs.map((n) => `
      <div class="notif-row ${n.is_read ? "" : "unread"}" data-notif-id="${n.id}">
        <span class="notif-type">${n.type}</span>
        ${escapeHtmlGlobal(n.message)}
      </div>
    `).join("");
    rows.querySelectorAll(".notif-row").forEach((row) => {
      row.addEventListener("click", async () => {
        const id = row.getAttribute("data-notif-id");
        row.classList.remove("unread");
        try {
          await apiRequest(`/api/notifications/${id}/read`, { method: "POST" });
          const badgeEl = document.getElementById("notifBadge");
          const remaining = document.querySelectorAll(".notif-row.unread").length;
          badgeEl.textContent = remaining;
          badgeEl.classList.toggle("hidden", remaining === 0);
        } catch (err) { /* ignore */ }
      });
    });
  } catch (err) { /* not logged in / not on an authenticated page yet */ }
}

function escapeHtmlGlobal(str) {
  const div = document.createElement("div");
  div.textContent = str == null ? "" : String(str);
  return div.innerHTML;
}

/* =========================================================================
   Browser (OS-level) notifications — study reminders.
   The backend already creates in-app notifications (deadline alerts, phase
   updates, and a daily "study_reminder" nudge for anyone who hasn't logged
   activity yet today). If the student has granted browser notification
   permission, refreshNotifications() also fires a native OS notification for
   any notification it hasn't shown before, so a study reminder can reach the
   student even if the Trailhead tab isn't focused.
   ========================================================================= */

const SHOWN_NOTIF_IDS_KEY = "alp_shown_browser_notif_ids";
const NOTIF_PERMISSION_DISMISSED_KEY = "alp_notif_permission_dismissed";

function getShownNotifIds() {
  try {
    return new Set(JSON.parse(localStorage.getItem(SHOWN_NOTIF_IDS_KEY) || "[]"));
  } catch (_) {
    return new Set();
  }
}

function saveShownNotifIds(idSet) {
  // Cap stored history so this never grows unbounded
  const ids = Array.from(idSet).slice(-300);
  localStorage.setItem(SHOWN_NOTIF_IDS_KEY, JSON.stringify(ids));
}

const NOTIF_TYPE_TITLES = {
  study_reminder: "Study reminder",
  deadline: "Missed deadline",
  distraction: "Focus mode",
  test: "Phase test",
  phase: "Roadmap update",
};

function maybeShowBrowserNotifications(notifs) {
  if (!("Notification" in window) || Notification.permission !== "granted") return;
  if (!Array.isArray(notifs) || notifs.length === 0) return;

  const shown = getShownNotifIds();
  let changed = false;

  notifs.forEach((n) => {
    if (shown.has(n.id)) return;
    shown.add(n.id);
    changed = true;
    if (n.is_read) return; // don't push a native alert for something already read elsewhere

    try {
      new Notification(NOTIF_TYPE_TITLES[n.type] || "Trailhead", {
        body: n.message,
        tag: `alp-notif-${n.id}`, // de-duplicates if fired twice in the same session
      });
    } catch (_) { /* some browsers restrict Notification() outside a service worker; fail silently */ }
  });

  if (changed) saveShownNotifIds(shown);
}

/* Small nav prompt inviting the student to turn on study-reminder notifications. */
function initBrowserNotificationPrompt(navLinks, logoutLi) {
  if (!("Notification" in window)) return;
  if (Notification.permission !== "default") return; // already granted or denied, nothing to ask
  if (localStorage.getItem(NOTIF_PERMISSION_DISMISSED_KEY) === "1") return;

  const promptLi = document.createElement("li");
  promptLi.className = "notif-permission-prompt";
  promptLi.innerHTML = `
    <button class="btn-notif-enable" id="notifEnableBtn" title="Get a browser notification for study reminders and deadline alerts">
      Enable study reminders
    </button>
  `;
  navLinks.insertBefore(promptLi, logoutLi);

  document.getElementById("notifEnableBtn").addEventListener("click", async () => {
    try {
      const result = await Notification.requestPermission();
      if (result !== "default") {
        // granted or denied -- either way, the student made a choice, so stop asking
        localStorage.setItem(NOTIF_PERMISSION_DISMISSED_KEY, "1");
      }
    } finally {
      promptLi.remove();
    }
  });
}
