import { api } from "../api.js";
import { escapeHtml } from "../util.js";

const FEATURES = [
  ["🎯", "Cross-platform value finder", "Weighted deltas vs consensus (ECR) surface the most mis-ranked players on ESPN, Sleeper, Yahoo & more."],
  ["🏈", "Mock draft war room", "Live ADP boards, per-position value picks, and a graded report card the moment you finish."],
  ["🔁", "League-aware trades", "Import your ESPN/Sleeper league and get win-win trade matches built from real roster needs."],
  ["📈", "Season-long tools", "Roster grades, start/sit and waiver help, and player news — one home for the whole season."],
];

// Renders the full-screen sign-in / sign-up gate. Calls onAuthed(user) once
// the user successfully logs in or creates an account.
export function renderAuthGate(onAuthed) {
  const app = document.getElementById("app");
  document.body.classList.add("auth-mode");
  let mode = "login"; // or "signup"

  function draw() {
    const isLogin = mode === "login";
    app.innerHTML = `
      <div class="auth-hero">
        <div class="auth-pitch">
          <div class="auth-logo"><span class="dot">&#9679;</span> Fantasy Football Lab</div>
          <h1 class="auth-headline">Find the values.<br><span class="accent">Dodge the landmines.</span></h1>
          <p class="auth-sub">Your one-stop shop from preseason research to draft day to every Sunday of the season.</p>
          <ul class="auth-features">
            ${FEATURES.map(([icon, title, desc]) => `
              <li>
                <span class="af-icon">${icon}</span>
                <span><strong>${title}</strong><span class="af-desc">${desc}</span></span>
              </li>`).join("")}
          </ul>
        </div>

        <div class="auth-panel">
          <div class="auth-card">
            <h2 style="margin-bottom:4px;">${isLogin ? "Welcome back" : "Create your profile"}</h2>
            <p class="tag-note" style="margin:0 0 18px;">${isLogin ? "Sign in to pick up where you left off." : "Free — your drafts, leagues, and trades save to your profile."}</p>
            <div class="controls" style="flex-direction:column;align-items:stretch;gap:13px;">
              ${isLogin ? "" : `
                <label>Display name (optional)
                  <input type="text" id="au-display" placeholder="How your name shows up">
                </label>`}
              <label>Username
                <input type="text" id="au-username" autocomplete="username" placeholder="At least 3 characters">
              </label>
              <label>Password
                <input type="password" id="au-password" autocomplete="${isLogin ? "current-password" : "new-password"}" placeholder="At least 6 characters">
              </label>
              <button id="au-submit" style="margin-top:4px;padding:12px;">${isLogin ? "Sign in" : "Create profile"}</button>
            </div>
            <div id="au-error" class="error-state" style="display:none;margin-top:12px;"></div>
            <p class="tag-note" style="margin-top:16px;text-align:center;">
              ${isLogin ? "New here?" : "Already have a profile?"}
              <a href="#" id="au-toggle">${isLogin ? "Create a profile" : "Sign in"}</a>
            </p>
            <p class="tag-note" style="text-align:center;opacity:0.65;margin-top:4px;">
              Stays signed in on this device.
            </p>
          </div>
        </div>
      </div>
    `;

    const errEl = app.querySelector("#au-error");
    const showErr = (msg) => { errEl.style.display = "block"; errEl.textContent = msg; };

    app.querySelector("#au-toggle").addEventListener("click", (e) => {
      e.preventDefault();
      mode = isLogin ? "signup" : "login";
      draw();
    });

    const submit = async () => {
      const username = app.querySelector("#au-username").value.trim();
      const password = app.querySelector("#au-password").value;
      const btn = app.querySelector("#au-submit");
      if (!username || !password) { showErr("Enter a username and password."); return; }
      btn.disabled = true;
      btn.textContent = isLogin ? "Signing in…" : "Creating…";
      try {
        const user = isLogin
          ? await api.login({ username, password })
          : await api.signup({ username, password, display_name: app.querySelector("#au-display")?.value.trim() || null });
        document.body.classList.remove("auth-mode");
        onAuthed(user);
      } catch (err) {
        showErr(err.message || "Something went wrong.");
        btn.disabled = false;
        btn.textContent = isLogin ? "Sign in" : "Create profile";
      }
    };

    app.querySelector("#au-submit").addEventListener("click", submit);
    app.querySelector("#au-password").addEventListener("keydown", (e) => {
      if (e.key === "Enter") submit();
    });
    app.querySelector("#au-username").focus();
  }

  draw();
}
