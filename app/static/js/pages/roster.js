import { api } from "../api.js";
import { escapeHtml, posPill, fmtNum, formatLabel, debounce, injuryBadge, avatar } from "../util.js";

const state = { format: "ppr", mode: "manual", roster: [] }; // roster: [{id,name,position,team}]

export async function renderRoster(container) {
  container.innerHTML = `
    <h1>Roster / Team Analysis</h1>
    <p class="subtitle">Build a roster manually or pull one live from a real Sleeper league, and get a grade, starter holes, and recommendations.</p>

    <div class="card">
      <div class="controls">
        <label>Scoring format
          <select id="ra-format">
            ${["standard", "half_ppr", "ppr"].map((f) => `<option value="${f}" ${f === state.format ? "selected" : ""}>${formatLabel(f)}</option>`).join("")}
          </select>
        </label>
        <div style="display:flex;gap:4px;">
          <button class="${state.mode === "manual" ? "" : "secondary"}" id="mode-manual">Build Manually</button>
          <button class="${state.mode === "sleeper" ? "" : "secondary"}" id="mode-sleeper">Import from Sleeper</button>
        </div>
      </div>
      <div id="mode-panel"></div>
    </div>

    <div id="roster-results"></div>
  `;

  container.querySelector("#ra-format").addEventListener("change", (e) => {
    state.format = e.target.value;
  });
  container.querySelector("#mode-manual").addEventListener("click", () => { state.mode = "manual"; renderRoster(container); });
  container.querySelector("#mode-sleeper").addEventListener("click", () => { state.mode = "sleeper"; renderRoster(container); });

  if (state.mode === "manual") {
    renderManualPanel(container);
  } else {
    renderSleeperPanel(container);
  }
}

function renderManualPanel(container) {
  const panel = container.querySelector("#mode-panel");
  panel.innerHTML = `
    <div class="controls">
      <input type="text" id="ra-search" placeholder="Search players to add…" style="min-width:260px;">
    </div>
    <div id="search-results"></div>
    <div id="roster-chips" style="margin:12px 0;"></div>
    <button id="ra-analyze" ${state.roster.length ? "" : "disabled"}>Analyze Roster (${state.roster.length})</button>
  `;

  renderChips(container);

  const search = panel.querySelector("#ra-search");
  const doSearch = debounce(async () => {
    const q = search.value.trim();
    const resultsEl = panel.querySelector("#search-results");
    if (!q) { resultsEl.innerHTML = ""; return; }
    const data = await api.listPlayers({ search: q, limit: "8", format: state.format });
    resultsEl.innerHTML = data.players.map((p) => `
      <div class="player-search-row">
        <div>${posPill(p.position)} <strong>${escapeHtml(p.name)}</strong> <span class="tag-note">${escapeHtml(p.team)}</span></div>
        <button data-pid="${p.id}" data-name="${escapeHtml(p.name)}" data-pos="${p.position}" data-team="${escapeHtml(p.team)}">Add</button>
      </div>
    `).join("") || `<div class="empty-state">No matches.</div>`;

    resultsEl.querySelectorAll("button[data-pid]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const id = btn.dataset.pid;
        if (state.roster.some((p) => p.id === id)) return;
        state.roster.push({ id, name: btn.dataset.name, position: btn.dataset.pos, team: btn.dataset.team });
        renderChips(container);
        panel.querySelector("#ra-analyze").disabled = false;
        panel.querySelector("#ra-analyze").textContent = `Analyze Roster (${state.roster.length})`;
      });
    });
  }, 250);
  search.addEventListener("input", doSearch);

  panel.querySelector("#ra-analyze").addEventListener("click", async () => {
    const data = await api.analyzeRoster({ player_ids: state.roster.map((p) => p.id), format: state.format });
    renderResults(container, data);
  });
}

function renderChips(container) {
  const chipsEl = container.querySelector("#roster-chips");
  if (!chipsEl) return;
  chipsEl.innerHTML = state.roster.map((p) => `
    <span class="chip">${posPill(p.position)} ${escapeHtml(p.name)}<button data-rm="${p.id}">&times;</button></span>
  `).join("") || `<span class="tag-note">No players added yet.</span>`;

  chipsEl.querySelectorAll("button[data-rm]").forEach((btn) => {
    btn.addEventListener("click", () => {
      state.roster = state.roster.filter((p) => p.id !== btn.dataset.rm);
      renderChips(container);
      const analyzeBtn = container.querySelector("#ra-analyze");
      if (analyzeBtn) {
        analyzeBtn.disabled = state.roster.length === 0;
        analyzeBtn.textContent = `Analyze Roster (${state.roster.length})`;
      }
    });
  });
}

function renderSleeperPanel(container) {
  const panel = container.querySelector("#mode-panel");
  panel.innerHTML = `
    <div class="controls">
      <input type="text" id="sl-league" placeholder="Sleeper league_id">
      <input type="number" id="sl-roster" placeholder="roster_id (1, 2, 3…)" style="width:170px;">
      <button id="sl-load">Load &amp; Analyze</button>
    </div>
    <p class="tag-note">Find your league_id in the Sleeper app URL (sleeper.com/leagues/&lt;league_id&gt;). roster_id is the team slot number within that league.</p>
  `;
  panel.querySelector("#sl-load").addEventListener("click", async () => {
    const league_id = panel.querySelector("#sl-league").value.trim();
    const roster_id = panel.querySelector("#sl-roster").value.trim();
    if (!league_id || !roster_id) return;
    const resultsEl = container.querySelector("#roster-results");
    resultsEl.innerHTML = `<div class="loading">Loading&hellip;</div>`;
    try {
      const data = await api.analyzeSleeperRoster({ league_id, roster_id, format: state.format });
      renderResults(container, data);
    } catch (err) {
      resultsEl.innerHTML = `<div class="error-state">${escapeHtml(err.message)}</div>`;
    }
  });
}

function renderResults(container, data) {
  const target = container.querySelector("#roster-results");
  const gradeClass = data.grade.startsWith("A") ? "" : data.grade.startsWith("B") ? "" : "grade-D";

  const slotRowHtml = (slot, p) => `
    <div class="slot-row">
      <span class="slot-name">${slot}</span>
      ${p ? `
        <span class="slot-player">
          ${avatar(p, 24)}
          ${posPill(p.position)}
          <span class="p-name">${escapeHtml(p.name)}${injuryBadge(p.injury_status)}</span>
        </span>
        <span class="slot-pts">${fmtNum(p.proj_points[data.format], 0)} proj</span>
      ` : `<span class="empty">EMPTY</span>`}
    </div>
  `;

  const starterRows = Object.entries(data.starter_detail)
    .map(([slot, p]) => slotRowHtml(slot, p)).join("");
  const benchRows = data.bench.map((p, i) => slotRowHtml(`BE${i + 1}`, p)).join("")
    || `<p class="tag-note">No bench players.</p>`;

  const posStrength = Object.entries(data.position_strength).map(([pos, info]) => `
    <div class="slot-row">
      <span class="slot-name">${pos}</span>
      <span>${info.starters.join(", ") || "none"} <span class="tag-note">(VBD ${fmtNum(info.vbd)})</span></span>
    </div>
  `).join("");

  const recs = data.recommendations.map((r) => `<li>${escapeHtml(r)}</li>`).join("");

  target.innerHTML = `
    <div class="grid-2">
      <div class="card">
        <div style="display:flex;align-items:center;gap:14px;margin-bottom:10px;">
          <div class="grade-badge ${gradeClass}">${data.grade}</div>
          <div>
            <div style="font-weight:700;font-size:16px;">${formatLabel(data.format)} Roster Grade</div>
            <div class="tag-note">Starter value: ${fmtNum(data.starter_vbd)} VBD &middot; effective (hole-adjusted): ${fmtNum(data.effective_vbd)} VBD</div>
          </div>
        </div>
        <h3>Starting Lineup</h3>
        ${starterRows}
        <h3 style="margin-top:14px;">Bench</h3>
        ${benchRows}
      </div>
      <div class="card">
        <h3>Positional Strength</h3>
        ${posStrength}
        <h3 style="margin-top:14px;">Recommendations</h3>
        <ul class="rec-list">${recs}</ul>
      </div>
    </div>
  `;
}
