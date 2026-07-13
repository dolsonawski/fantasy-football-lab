import { registerRoute, startRouter } from "./router.js";
import { api } from "./api.js";
import { renderRankings } from "./pages/rankings.js";
import { renderDraft } from "./pages/draft.js";
import { renderRoster } from "./pages/roster.js";
import { renderTrade } from "./pages/trade.js";
import { renderImport } from "./pages/import.js";
import { renderSeason } from "./pages/season.js";
import { renderAuthGate } from "./pages/auth.js";
import { initPlayerDetail } from "./player_detail.js";

registerRoute("rankings", renderRankings);
registerRoute("draft", renderDraft);
registerRoute("season", renderSeason);
registerRoute("roster", renderRoster);
registerRoute("trade", renderTrade);
registerRoute("import", renderImport);

let routerStarted = false;

function initials(name) {
  return (name || "?").trim().split(/\s+/).map((w) => w[0]).slice(0, 2).join("").toUpperCase();
}

function mountApp(user) {
  const topbar = document.querySelector("header.topbar");
  const nav = document.getElementById("nav-tabs");
  const seasonTag = document.getElementById("season-tag");
  topbar.style.display = "";
  nav.style.display = "";

  // User chip + logout in the top-right, replacing the plain season tag slot.
  let account = document.getElementById("account-chip");
  if (!account) {
    account = document.createElement("div");
    account.id = "account-chip";
    account.className = "account-chip";
    seasonTag.after(account);
  }
  account.innerHTML = `
    <span class="avatar-initials" title="${user.display_name}">${initials(user.display_name)}</span>
    <span class="account-name">${user.display_name}</span>
    <button class="logout-btn" id="logout-btn">Sign out</button>
  `;
  account.querySelector("#logout-btn").addEventListener("click", async () => {
    try { await api.logout(); } catch (_) { /* ignore */ }
    window.location.hash = "#/rankings";
    window.location.reload();
  });

  api.getMeta()
    .then((meta) => {
      seasonTag.textContent =
        `${meta.projection_season || "—"} projections · ${meta.season} stats · ${meta.player_count} players`;
    })
    .catch(() => {});

  if (!routerStarted) {
    routerStarted = true;
    initPlayerDetail();
    startRouter();
  } else {
    if (!window.location.hash) window.location.hash = "#/rankings";
    window.dispatchEvent(new HashChangeEvent("hashchange"));
  }
}

function showGate() {
  // Hide the chrome while the sign-in gate is up.
  document.querySelector("header.topbar").style.display = "none";
  renderAuthGate((user) => mountApp(user));
}

function showUnreachable() {
  document.querySelector("header.topbar").style.display = "none";
  document.getElementById("app").innerHTML = `
    <div class="auth-shell"><div class="auth-card" style="text-align:center;">
      <div class="auth-brand" style="align-items:center;"><span class="dot">&#9679;</span> Fantasy Football Lab</div>
      <h2>Can't reach the server</h2>
      <p class="tag-note" style="margin:6px 0 18px;">The app is installed, but the backend isn't responding. Make sure the server is running (or the site is deployed), then retry.</p>
      <button id="retry-btn">Retry</button>
    </div></div>`;
  document.getElementById("retry-btn").addEventListener("click", () => window.location.reload());
}

api.me()
  .then((user) => mountApp(user))
  .catch((err) => {
    if (err && err.isNetwork) showUnreachable();
    else showGate();
  });
