import { api } from "../api.js";
import { escapeHtml, posPill, fmtNum, formatLabel } from "../util.js";

const state = { leagues: [], leagueKey: "", league: null, teamId: "", format: "ppr", tab: "dashboard", week: "" };

const MY_TEAMS_KEY = "ffl_my_teams";
function loadMyTeams() {
  try { return JSON.parse(localStorage.getItem(MY_TEAMS_KEY)) || {}; } catch (_) { return {}; }
}
function saveMyTeams(map) {
  try { localStorage.setItem(MY_TEAMS_KEY, JSON.stringify(map)); } catch (_) { /* ignore */ }
}

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
      <div class="controls" id="se-controls" style="${state.tab === "dashboard" ? "display:none;" : ""}">
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
        <button class="seg ${state.tab === "dashboard" ? "active" : ""}" data-tab="dashboard">Dashboard</button>
        <button class="seg ${state.tab === "startsit" ? "active" : ""}" data-tab="startsit">Start / Sit</button>
        <button class="seg ${state.tab === "waivers" ? "active" : ""}" data-tab="waivers">Waiver Adds</button>
        <button class="seg ${state.tab === "byes" ? "active" : ""}" data-tab="byes">Bye Planner</button>
        <button class="seg ${state.tab === "playoffs" ? "active" : ""}" data-tab="playoffs">Playoffs</button>
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
    container.querySelector("#se-controls").style.display = state.tab === "dashboard" ? "none" : "";
    load(container);
  }));

  await loadTeams();
  await load(container);
}

async function load(container) {
  const body = container.querySelector("#se-body");
  if (state.tab === "dashboard") {
    await loadDashboard(container, body);
    return;
  }
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
    } else if (state.tab === "playoffs") {
      body.innerHTML = renderPlayoffOutlook(await api.playoffOutlook(base));
    } else {
      body.innerHTML = renderByes(await api.byePlanner(base));
    }
  } catch (err) {
    body.innerHTML = `<div class="error-state">${escapeHtml(err.message || "Couldn't load")}</div>`;
  }
}

/* ------------------------------------------------------------ dashboard */

async function loadDashboard(container, body) {
  if (!state.leagues.length) {
    body.innerHTML = `<div class="card"><div class="empty-state">
      Import a league on the <a href="#/import">Import</a> tab to see your at-a-glance dashboard.
    </div></div>`;
    return;
  }

  const myTeams = loadMyTeams();
  body.innerHTML = `
    <div class="grid-2">
      ${state.leagues.map((l) => `
        <div class="card">
          <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:10px;">
            <div>
              <strong>${escapeHtml(l.name || l.league_id)}</strong>
              <div class="tag-note">${l.platform.toUpperCase()} · ${l.team_count} teams</div>
            </div>
            <select class="dash-team-select" data-league="${escapeHtml(l.key)}" style="max-width:170px;"></select>
          </div>
          <div class="dash-body" data-league-body="${escapeHtml(l.key)}" style="margin-top:10px;"><div class="loading">Loading&hellip;</div></div>
        </div>
      `).join("")}
    </div>
  `;

  // Each card loads (and re-loads) independently — a slow league can't block the rest.
  state.leagues.forEach((l) => loadDashboardCard(container, l, myTeams));
}

async function loadDashboardCard(container, l, myTeams) {
  const cardBody = container.querySelector(`[data-league-body="${l.key}"]`);
  const teamSelect = container.querySelector(`select[data-league="${l.key}"]`);
  if (!cardBody || !teamSelect) return;

  let league;
  try {
    league = await api.getLeague(l.key);
  } catch (err) {
    cardBody.innerHTML = `<div class="error-state">${escapeHtml(err.message || "Couldn't load league")}</div>`;
    return;
  }
  teamSelect.innerHTML = league.teams.map((t) => `<option value="${t.team_id}">${escapeHtml(t.name)}</option>`).join("");
  let teamId = myTeams[l.key];
  if (!league.teams.some((t) => t.team_id === teamId)) teamId = league.teams[0]?.team_id || "";
  teamSelect.value = teamId;

  const renderCard = async (tid) => {
    if (!tid) { cardBody.innerHTML = `<div class="empty-state">No teams in this league.</div>`; return; }
    cardBody.innerHTML = `<div class="loading">Loading&hellip;</div>`;
    try {
      const base = { league_key: l.key, team_id: tid, format: state.format };
      const [startSit, waivers, byes] = await Promise.all([
        api.startSit(base),
        api.waivers(base),
        api.byePlanner(base),
      ]);
      const injured = startSit.injuries || [];
      const emptySlots = startSit.empty_slots || [];
      const topAdd = (waivers.best_adds || [])[0];
      const worstWeek = byes.worst_week;

      cardBody.innerHTML = `
        ${injured.length
          ? `<div class="tag-note" style="color:var(--warning);">⚠ ${injured.map((p) => escapeHtml(p.name)).join(", ")}</div>`
          : `<div class="tag-note">No injured starters.</div>`}
        <div class="tag-note">${emptySlots.length ? `Open slots: <strong>${emptySlots.join(", ")}</strong>` : "No open starter slots."}</div>
        <div class="tag-note">Top waiver add: ${topAdd ? `<strong>${escapeHtml(topAdd.name)}</strong> <span class="delta-chip delta-pos" style="font-size:10.5px;">+${fmtNum(topAdd.upgrade_vbd)} VBD</span>` : "none available"}</div>
        <div class="tag-note">Worst bye week: ${worstWeek ? `Week ${worstWeek}` : "&mdash;"}</div>
        <button class="secondary" id="dash-details-${escapeHtml(l.key)}" style="margin-top:8px;">Details &rarr;</button>
      `;
      cardBody.querySelector(`#dash-details-${CSS.escape(l.key)}`).addEventListener("click", () => {
        state.leagueKey = l.key;
        state.teamId = tid;
        state.tab = "startsit";
        renderSeason(container);
      });
    } catch (err) {
      cardBody.innerHTML = `<div class="error-state">${escapeHtml(err.message || "Couldn't load")}</div>`;
    }
  };

  teamSelect.addEventListener("change", (e) => {
    const tid = e.target.value;
    const map = loadMyTeams();
    map[l.key] = tid;
    saveMyTeams(map);
    renderCard(tid);
  });

  await renderCard(teamId);
  const map = loadMyTeams();
  if (!map[l.key]) { map[l.key] = teamId; saveMyTeams(map); }
}

function playerRow(p, right) {
  // Weekly opponent chip: only present on start-sit starters when a
  // specific week is selected (see season.py start_sit's opponent fields).
  const oppChip = p.opponent
    ? ` <span class="delta-chip ${p.opponent_difficulty === "tough" ? "delta-neg" : p.opponent_difficulty === "easy" ? "delta-pos" : "delta-zero"}" style="font-size:10px;padding:2px 7px;">${escapeHtml(p.opponent)}</span>`
    : "";
  return `
    <div class="player-search-row" data-player-id="${p.id}" data-player-format="${state.format}" style="cursor:pointer;">
      <div class="row-main">
        ${posPill(p.position)}
        <span style="min-width:0;">
          <strong>${escapeHtml(p.name)}</strong>${oppChip}
          <span class="tag-note">${escapeHtml(p.team || "")}${p.proj_pos_rank ? ` · ${p.position}${p.proj_pos_rank}` : ""}${p.injury_status ? ` · <span class="value-neg">${escapeHtml(p.injury_status)}</span>` : ""}</span>
        </span>
      </div>
      <span style="text-align:right;flex-shrink:0;">${right}</span>
    </div>`;
}

function renderPlayoffOutlook(d) {
  if (!d.schedule_available) {
    return `<div class="card"><div class="empty-state">Playoff schedule data isn't available right now — check back once the NFL schedule loads.</div></div>`;
  }
  const warn = d.tough_starters.length ? `
    <div class="verdict-banner verdict-lopsided">
      ⚠️ Tough playoff schedules (weeks 15&ndash;17) among your starters:
      ${d.tough_starters.map((p) => `${escapeHtml(p.name)} (${"★".repeat(p.playoff_sos.stars)}${"☆".repeat(5 - p.playoff_sos.stars)})`).join(", ")}
    </div>` : "";

  const rows = d.players.map((p) => {
    const sos = p.playoff_sos;
    const starsHtml = sos ? `${"★".repeat(sos.stars)}${"☆".repeat(5 - sos.stars)}` : "&mdash;";
    const opps = sos ? sos.opponents.map((o, i) => `Wk${15 + i}: ${o ? escapeHtml(o) : "BYE"}`).join(", ") : "no schedule data";
    const starClass = sos && sos.stars <= 2 ? "value-neg" : sos && sos.stars >= 4 ? "value-pos" : "";
    return `
      <div class="player-search-row">
        <div class="row-main">
          ${posPill(p.position)}
          <span style="min-width:0;">
            <strong>${escapeHtml(p.name)}</strong> <span class="tag-note">${p.is_starter ? "starter" : "bench"}</span>
            <div class="tag-note">${escapeHtml(p.team || "")} · ${opps}</div>
          </span>
        </div>
        <span class="${starClass}" style="flex-shrink:0;">${starsHtml}</span>
      </div>`;
  }).join("");

  return `
    ${warn}
    <div class="card">
      <h2>Playoff Schedule Outlook <span class="tag-note" style="font-weight:400;">weeks 15&ndash;17</span></h2>
      <p class="tag-note">Roster sorted by projected points. Stars rate that player's NFL team playoff schedule (5 = easiest).</p>
      ${rows}
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
