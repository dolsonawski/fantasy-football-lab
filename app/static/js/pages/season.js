import { api } from "../api.js";
import { escapeHtml, posPill, fmtNum, formatLabel } from "../util.js";

const state = { leagues: [], leagueKey: "", league: null, teamId: "", format: "ppr", tab: "startsit", week: "" };

export async function renderSeason(container) {
  try { state.leagues = (await api.listLeagues()).leagues; } catch (_) { state.leagues = []; }

  if (!state.leagues.length) {
    container.innerHTML = `
      <h1>Season Tools</h1>
      <p class="subtitle">Start/sit calls and waiver-wire adds for your team, all season long.</p>
      <div class="card"><div class="empty-state">
        Import your ESPN or Sleeper league on the <a href="#/import">Import</a> tab first —
        then your teams show up here for start/sit and waiver help.
      </div></div>`;
    return;
  }

  container.innerHTML = `
    <h1>Season Tools</h1>
    <p class="subtitle">Optimal lineups and the best available adds for your team, powered by projections and your league's rosters.</p>
    <div class="card">
      <div class="controls">
        <label>League
          <select id="se-league">
            ${state.leagues.map((l) => `<option value="${l.key}" ${l.key === state.leagueKey ? "selected" : ""}>${escapeHtml(l.name || l.league_id)} (${l.platform.toUpperCase()})</option>`).join("")}
          </select>
        </label>
        <label>Your team
          <select id="se-team"></select>
        </label>
        <label>Format
          <select id="se-format">
            ${["standard", "half_ppr", "ppr"].map((f) => `<option value="${f}" ${f === state.format ? "selected" : ""}>${formatLabel(f)}</option>`).join("")}
          </select>
        </label>
        <label id="se-week-wrap" style="${state.tab === "startsit" ? "" : "display:none;"}">Week
          <select id="se-week">
            <option value="">Season-long</option>
            ${Array.from({ length: 18 }, (_, i) => i + 1).map((w) => `<option value="${w}" ${String(w) === state.week ? "selected" : ""}>Week ${w}</option>`).join("")}
          </select>
        </label>
      </div>
      <div class="seg-tabs">
        <button class="seg ${state.tab === "startsit" ? "active" : ""}" data-tab="startsit">Start / Sit</button>
        <button class="seg ${state.tab === "waivers" ? "active" : ""}" data-tab="waivers">Waiver Adds</button>
        <button class="seg ${state.tab === "byes" ? "active" : ""}" data-tab="byes">Bye Planner</button>
      </div>
    </div>
    <div id="se-body"></div>
  `;

  const leagueSel = container.querySelector("#se-league");
  const teamSel = container.querySelector("#se-team");
  const fmtSel = container.querySelector("#se-format");

  if (!state.leagueKey) state.leagueKey = state.leagues[0].key;
  leagueSel.value = state.leagueKey;

  async function loadTeams() {
    state.league = await api.getLeague(state.leagueKey);
    teamSel.innerHTML = state.league.teams.map((t) => `<option value="${t.team_id}">${escapeHtml(t.name)}</option>`).join("");
    if (!state.league.teams.some((t) => t.team_id === state.teamId)) {
      state.teamId = state.league.teams[0]?.team_id || "";
    }
    teamSel.value = state.teamId;
  }

  leagueSel.addEventListener("change", async (e) => { state.leagueKey = e.target.value; state.teamId = ""; await loadTeams(); load(container); });
  teamSel.addEventListener("change", (e) => { state.teamId = e.target.value; load(container); });
  fmtSel.addEventListener("change", (e) => { state.format = e.target.value; load(container); });
  container.querySelector("#se-week").addEventListener("change", (e) => { state.week = e.target.value; load(container); });
  container.querySelectorAll(".seg").forEach((b) => b.addEventListener("click", () => {
    state.tab = b.dataset.tab;
    container.querySelectorAll(".seg").forEach((x) => x.classList.toggle("active", x === b));
    container.querySelector("#se-week-wrap").style.display = state.tab === "startsit" ? "" : "none";
    load(container);
  }));

  await loadTeams();
  await load(container);
}

async function load(container) {
  const body = container.querySelector("#se-body");
  if (!state.teamId) { body.innerHTML = ""; return; }
  body.innerHTML = `<div class="loading">Crunching projections&hellip;</div>`;
  try {
    const base = { league_key: state.leagueKey, team_id: state.teamId, format: state.format };
    if (state.tab === "startsit") {
      const params = { ...base };
      if (state.week) params.week = state.week;
      body.innerHTML = renderStartSit(await api.startSit(params));
    } else if (state.tab === "waivers") {
      body.innerHTML = renderWaivers(await api.waivers(base));
    } else {
      body.innerHTML = renderByes(await api.byePlanner(base));
    }
  } catch (err) {
    body.innerHTML = `<div class="error-state">${escapeHtml(err.message || "Couldn't load")}</div>`;
  }
}

function playerRow(p, right) {
  return `
    <div class="player-search-row" data-player-id="${p.id}" data-player-format="${state.format}" style="cursor:pointer;">
      <div class="row-main">
        ${posPill(p.position)}
        <span style="min-width:0;">
          <strong>${escapeHtml(p.name)}</strong>
          <span class="tag-note">${escapeHtml(p.team || "")}${p.proj_pos_rank ? ` · ${p.position}${p.proj_pos_rank}` : ""}${p.injury_status ? ` · <span class="value-neg">${escapeHtml(p.injury_status)}</span>` : ""}</span>
        </span>
      </div>
      <span style="text-align:right;flex-shrink:0;">${right}</span>
    </div>`;
}

function renderByes(d) {
  if (!d.weeks.length) {
    return `<div class="card"><div class="empty-state">No bye-week data yet — byes publish with the NFL schedule and flow in automatically.</div></div>`;
  }
  const weekCard = (w) => `
    <div class="card" style="${w.crunch ? "border-color:rgba(255,107,107,0.5);" : ""}">
      <h2>Week ${w.week} ${w.crunch ? '<span class="delta-chip delta-neg" style="font-size:11px;">⚠️ ' + w.starters_out + " starters out</span>" : `<span class="tag-note">${w.starters_out} starter${w.starters_out === 1 ? "" : "s"} out</span>`}</h2>
      ${w.players.map((p) => playerRow(p, p.is_starter ? `<span class="delta-chip delta-neg" style="font-size:10.5px;">starter</span>` : `<span class="tag-note">bench</span>`)).join("")}
    </div>`;
  const worst = d.worst_week ? `<div class="verdict-banner ${d.weeks.find((w) => w.week === d.worst_week)?.crunch ? "verdict-lopsided" : "verdict-edge"}">
      Toughest bye week for ${escapeHtml(d.team_name)}: <strong>Week ${d.worst_week}</strong> — plan waiver adds or trades around it.</div>` : "";
  return `${worst}<div class="grid-2">${d.weeks.map(weekCard).join("")}</div>
    ${d.unknown_bye.length ? `<p class="tag-note">No bye data yet for: ${d.unknown_bye.map((p) => escapeHtml(p.name)).join(", ")}</p>` : ""}`;
}

function renderStartSit(d) {
  const weekNote = d.week
    ? `<div class="verdict-banner verdict-fair">Showing <strong>Week ${d.week}</strong> projections.</div>`
    : (state.week ? `<div class="verdict-banner verdict-edge">Week ${state.week} projections aren't published yet — showing season-long instead.</div>` : "");
  const starters = d.starters.map((s) =>
    playerRow(s, `<span class="slot-name" style="width:auto;">${s.slot}</span> <strong>${fmtNum(s.proj_points)}</strong>`)).join("");
  const empty = d.empty_slots.length
    ? `<p class="tag-note">Open starter slots (no one to fill them): <strong>${d.empty_slots.join(", ")}</strong></p>` : "";
  const bench = d.bench.length
    ? d.bench.map((p) => playerRow(p, `<span class="tag-note">${fmtNum(p.proj_points)}</span>`)).join("")
    : `<p class="tag-note">No bench players.</p>`;

  const calls = d.close_calls.length ? `
    <div class="card">
      <h2>⚖️ Close Calls</h2>
      <p class="tag-note">Bench players within striking distance of a starter — worth a second look based on matchup.</p>
      ${d.close_calls.map((c) => `
        <div class="slot-row">
          <span>${posPill(c.starter.position)} <strong>${escapeHtml(c.starter.name)}</strong> <span class="tag-note">start (${c.slot})</span></span>
          <span class="tag-note">only +${fmtNum(c.gap)} vs</span>
          <span>${posPill(c.bench.position)} <strong>${escapeHtml(c.bench.name)}</strong> <span class="tag-note">bench</span></span>
        </div>`).join("")}
    </div>` : "";

  const injuries = d.injuries.length ? `
    <div class="verdict-banner verdict-edge">⚠️ Injury watch in your lineup: ${d.injuries.map((p) => `${escapeHtml(p.name)} (${escapeHtml(p.injury_status)})`).join(", ")}</div>` : "";

  return `
    ${weekNote}
    ${injuries}
    <div class="grid-2">
      <div class="card">
        <h2>✅ Start</h2>
        ${starters}
        ${empty}
      </div>
      <div class="card">
        <h2>🪑 Sit / Bench</h2>
        ${bench}
      </div>
    </div>
    ${calls}
  `;
}

function renderWaivers(d) {
  const adds = d.best_adds.length
    ? d.best_adds.map((p) => playerRow(p, `<span class="delta-chip delta-pos">+${fmtNum(p.upgrade_vbd)}</span>`)).join("")
    : `<p class="tag-note">No free agent would crack your current starting lineup — you're in good shape.</p>`;
  const top = d.top_available.map((p) => playerRow(p, `<span class="tag-note">${fmtNum(p.proj_points)} proj</span>`)).join("");

  return `
    <div class="grid-2">
      <div class="card">
        <h2>🎯 Best Adds for ${escapeHtml(d.team_name)}</h2>
        <p class="tag-note">Free agents that would upgrade your starting lineup — the number is projected starter-value gained.</p>
        ${adds}
      </div>
      <div class="card">
        <h2>📋 Top Available Overall</h2>
        <p class="tag-note">${d.free_agent_count} unrostered players — the best regardless of your needs.</p>
        ${top}
      </div>
    </div>
  `;
}
