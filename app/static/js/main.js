import { registerRoute, startRouter } from "./router.js";
import { api } from "./api.js";
import { renderRankings } from "./pages/rankings.js";
import { renderDraft } from "./pages/draft.js";
import { renderRoster } from "./pages/roster.js";
import { renderTrade } from "./pages/trade.js";
import { renderImport } from "./pages/import.js";
import { renderSeason } from "./pages/season.js";
import { initPlayerDetail } from "./player_detail.js";
import { getDeviceId, setDeviceId } from "./identity.js";

registerRoute("rankings", renderRankings);
registerRoute("draft", renderDraft);
registerRoute("season", renderSeason);
registerRoute("roster", renderRoster);
registerRoute("trade", renderTrade);
registerRoute("import", renderImport);

function renderIdentityChip() {
  const seasonTag = document.getElementById("season-tag");
  let chip = document.getElementById("account-chip");
  if (!chip) {
    chip = document.createElement("div");
    chip.id = "account-chip";
    chip.className = "account-chip";
    seasonTag.after(chip);
  }
  const id = getDeviceId();
  chip.innerHTML = `
    <span class="avatar-initials" title="Your device ID">${id.slice(0, 2).toUpperCase()}</span>
    <button class="logout-btn" id="id-menu-btn" title="${id}">ID: ${id.slice(0, 6)}&hellip;</button>
  `;
  chip.querySelector("#id-menu-btn").addEventListener("click", () => openIdentityPanel());
}

function openIdentityPanel() {
  const id = getDeviceId();
  const existing = document.getElementById("id-overlay");
  if (existing) existing.remove();

  const overlay = document.createElement("div");
  overlay.id = "id-overlay";
  overlay.className = "pd-overlay";
  overlay.innerHTML = `
    <div class="pd-modal" role="dialog" aria-modal="true" style="max-width:440px;">
      <div class="pd-body">
        <div class="pd-header">
          <div class="pd-id"><div><div class="pd-name">Your Device ID</div>
            <div class="tag-note">This is what keeps your drafts, leagues, and trades private to you &mdash; no password needed.</div>
          </div></div>
          <button class="pd-x" aria-label="Close">&times;</button>
        </div>
        <div class="controls" style="flex-direction:column;align-items:stretch;margin-top:14px;">
          <label>Your ID
            <input type="text" id="id-display" value="${id}" readonly style="font-family:monospace;">
          </label>
          <button id="id-copy">Copy ID</button>
          <p class="tag-note" style="margin-top:10px;">
            To use the same data on another device or browser, open this app there and paste your ID below.
          </p>
          <label>Switch to a different ID
            <input type="text" id="id-input" placeholder="Paste an ID to switch to it">
          </label>
          <button class="secondary" id="id-switch">Switch</button>
          <div id="id-error" class="error-state" style="display:none;margin-top:4px;"></div>
        </div>
      </div>
    </div>
  `;
  document.body.appendChild(overlay);
  overlay.addEventListener("click", (e) => { if (e.target === overlay) overlay.remove(); });
  overlay.querySelector(".pd-x").addEventListener("click", () => overlay.remove());
  overlay.querySelector("#id-copy").addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(id);
      const btn = overlay.querySelector("#id-copy");
      btn.textContent = "Copied!";
      setTimeout(() => { btn.textContent = "Copy ID"; }, 1500);
    } catch (_) { /* clipboard may be unavailable; the field is selectable */ }
  });
  overlay.querySelector("#id-switch").addEventListener("click", () => {
    const errEl = overlay.querySelector("#id-error");
    try {
      setDeviceId(overlay.querySelector("#id-input").value);
      window.location.reload();
    } catch (err) {
      errEl.style.display = "block";
      errEl.textContent = err.message;
    }
  });
}

function showUnreachable(retry) {
  document.querySelector("header.topbar").style.display = "none";
  document.getElementById("app").innerHTML = `
    <div class="auth-shell"><div class="auth-card" style="text-align:center;">
      <div class="auth-brand" style="align-items:center;"><span class="dot">&#9679;</span> Fantasy Football Lab</div>
      <h2>Can't reach the server</h2>
      <p class="tag-note" style="margin:6px 0 18px;">The app is installed, but the backend isn't responding. Make sure the server is running (or the site is deployed), then retry.</p>
      <button id="retry-btn">Retry</button>
    </div></div>`;
  document.getElementById("retry-btn").addEventListener("click", retry);
}

function setupBackToTop() {
  if (document.getElementById("back-to-top")) return;
  const btn = document.createElement("button");
  btn.id = "back-to-top";
  btn.setAttribute("aria-label", "Back to top");
  btn.textContent = "↑";
  document.body.appendChild(btn);
  btn.addEventListener("click", () => window.scrollTo({ top: 0, behavior: "smooth" }));
  window.addEventListener("scroll", () => {
    btn.classList.toggle("visible", window.scrollY > 600);
  }, { passive: true });
}

function mountApp(meta) {
  document.querySelector("header.topbar").style.display = "";
  renderIdentityChip();

  const seasonTag = document.getElementById("season-tag");
  seasonTag.textContent = meta
    ? `${meta.projection_season || "—"} projections · ${meta.season} stats · ${meta.player_count} players`
    : "";

  initPlayerDetail();
  setupBackToTop();
  startRouter();
}

// A quick GET confirms the backend is reachable before we start routing —
// if it's down, show a clear retry screen instead of a half-loaded page.
api.getMeta()
  .then((meta) => mountApp(meta))
  .catch((err) => {
    if (err && err.isNetwork) {
      showUnreachable(() => window.location.reload());
    } else {
      mountApp(null); // server responded (even with an error) — it's reachable
    }
  });
