/* =========================================================================
   chat.js
   Powers chat.html: a simple free-form Q&A chat with the AI.
     - Keeps the conversation in memory for this page load (sent as
       `history` on each request so the AI has context).
     - POST /api/chat -> { reply }
   ========================================================================= */

document.addEventListener("DOMContentLoaded", () => {
  Auth.requireLogin();

  const errorBanner = document.getElementById("errorBanner");
  const chatWindow = document.getElementById("chatWindow");
  const chatEmpty = document.getElementById("chatEmpty");
  const chatForm = document.getElementById("chatForm");
  const chatInput = document.getElementById("chatInput");
  const chatSendBtn = document.getElementById("chatSendBtn");

  let history = []; // [{ role: "user" | "assistant", text: "..." }]

  function scrollToBottom() {
    chatWindow.scrollTop = chatWindow.scrollHeight;
  }

  function escapeHtml(str) {
    const div = document.createElement("div");
    div.textContent = str == null ? "" : String(str);
    return div.innerHTML;
  }

  function addBubble(role, text, { typing = false } = {}) {
    if (chatEmpty) chatEmpty.remove();
    const bubble = document.createElement("div");
    bubble.className = `chat-msg ${role}${typing ? " typing" : ""}`;
    bubble.innerHTML = escapeHtml(text).replace(/\n/g, "<br>");
    chatWindow.appendChild(bubble);
    scrollToBottom();
    return bubble;
  }

  chatForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    hideBanner(errorBanner);

    const message = chatInput.value.trim();
    if (!message) return;

    addBubble("user", message);
    history.push({ role: "user", text: message });
    chatInput.value = "";
    chatInput.style.height = "auto";

    chatSendBtn.disabled = true;
    chatInput.disabled = true;
    const typingBubble = addBubble("assistant", "Thinking...", { typing: true });

    try {
      const data = await apiRequest("/api/chat", {
        method: "POST",
        body: { message, history: history.slice(0, -1) }, // don't send the message twice
      });
      typingBubble.remove();
      addBubble("assistant", data.reply);
      history.push({ role: "assistant", text: data.reply });
    } catch (err) {
      typingBubble.remove();
      showBanner(errorBanner, err.message);
    } finally {
      chatSendBtn.disabled = false;
      chatInput.disabled = false;
      chatInput.focus();
    }
  });

  // Let Enter send, Shift+Enter add a newline; auto-grow the textarea a bit
  chatInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      chatForm.requestSubmit();
    }
  });
  chatInput.addEventListener("input", () => {
    chatInput.style.height = "auto";
    chatInput.style.height = Math.min(chatInput.scrollHeight, 140) + "px";
  });
});
