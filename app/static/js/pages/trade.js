import { api } from "../api.js";
import { escapeHtml, posPill, fmtNum, formatLabel, debounce, toast } from "../util.js";

const state = {
  format: "ppr",
  showRosterContext: false,
  aSends: [], bSends: [], aRoster: [], bRoster: [],
  leagues: [],       // imported leagues (summaries)
  leagueKey: "",     // selected league key ("" = manual mode)
  league: null,      // full league detail
  teamA: "", teamB: "",
};

export async function renderTrade(container) {
  try { state.leagues = (await api.listLeagues()).leagues; } catch (_) { state.leagues = []; }

  container.innerHTML = `
    <h1>Trade Analyzer</h1>
    <p class="subtitle">
      Compare projected value on both sides of a trade. Import your league (Import tab) to pick real
      teams — rosters attach automatically so you see each side's lineup grade before and after.
    </p>

    <div class="card">
      <div class="controls">
        <label>League
          <select id="tr-league">
            <option value="">Manual (no league)</option>
            ${state.leagues.map((l) => `<option value="${l.key}" ${l.key === state.leagueKey ? "selected" : ""}>${escapeHtml(l.name || l.league_id)} (${l.platform.toUpperCase()})</option>`).join("")}
          </select>
        </label>
        <label>Scoring format
          <select id="tr-format">
            ${["standard", "half_ppr", "ppr"].map((f) => `<option value="${f}" ${f === state.format ? "selected" : ""}>${formatLabel(f)}</option>`).join("")}
          </select>
        </label>
        <label id="tr-context-label" style="${state.leagueKey ? "display:none;" : ""}"><input type="checkbox" id="tr-context" ${state.showRosterContext ? "checked" : ""}> Show roster impact (add each team's full roster)</label>
      </div>

      <div id="league-teams" class="controls" style="${state.leagueKey ? "" : "display:none;"}">
        <label>Team A
          <select id="tr-team-a"></select>
        </label>
        <label style="color:var(--accent);">trades with</label>
        <label>Team B
          <select id="tr-team-b"></select>
        </label>
        <button class="secondary" id="tr-suggest" style="align-self:flex-end;">✨ Suggest trades for Team A</button>
      </div>
      <div id="tr-matches"></div>

      <div class="grid-2">
        ${sideHtml("a", "Team A sends", "aSends")}
        ${sideHtml("b", "Team B sends", "bSends")}
      </div>

      <div id="context-panel" class="grid-2" style="margin-top:10px;${state.showRosterContext && !state.leagueKey ? "" : "display:none;"}">
        ${sideHtml("a-roster", "Team A full roster (optional)", "aRoster")}
        ${sideHtml("b-roster", "Team B full roster (optional)", "bRoster")}
      </div>

      <button id="tr-analyze" style="margin-top:14px;">Analyze Trade</button>
    </div>

    <div id="trade-results"></div>
  `;

  container.querySelector("#tr-format").addEventListener("change", (e) => { state.format = e.target.value; });
  container.querySelector("#tr-context").addEventListener("change", (e) => {
    state.showRosterContext = e.target.checked;
    container.querySelector("#context-panel").style.display = state.showRosterContext ? "" : "none";
  });
  container.querySelector("#tr-league").addEventListener("change", async (e) => {
    state.leagueKey = e.target.value;
    state.league = null;
    state.teamA = state.teamB = "";
    state.aSends = []; state.bSends = [];
    await renderTrade(container);
  });

  wireSide(container, "a", "aSends");
  wireSide(container, "b", "bSends");
  wireSide(container, "a-roster", "aRoster");
  wireSide(container, "b-roster", "bRoster");

  if (state.leagueKey) {
    await setupLeagueMode(container);
    container.querySelector("#tr-suggest")?.addEventListener("click", () => suggestTrades(container));
  }

  container.querySelector("#tr-analyze").addEventListener("click", async () => {
    if (!state.aSends.length || !state.bSends.length) {
      toast("Both sides need at least one player.", "error");
      return;
    }
    const body = {
      team_a_sends: state.aSends.map((p) => p.id),
      team_b_sends: state.bSends.map((p) => p.id),
      format: state.format,
    };
    if (state.leagueKey && state.league) {
      const teamA = state.league.teams.find((t) => t.team_id === state.teamA);
      const teamB = state.league.teams.find((t) => t.team_id === state.teamB);
      if (teamA) body.team_a_roster = teamA.players;
      if (teamB) body.team_b_roster = teamB.players;
    } else if (state.showRosterContext) {
      if (state.aRoster.length) body.team_a_roster = state.aRoster.map((p) => p.id);
      if (state.bRoster.length) body.team_b_roster = state.bRoster.map((p) => p.id);
    }
    const data = await api.analyzeTrade(body);
    renderResults(container, data);
  });
}

async function setupLeagueMode(container) {
  state.league = await api.getLeague(state.leagueKey);
  const teams = state.league.teams;
  if (!state.teamA) state.teamA = teams[0]?.team_id || "";
  if (!state.teamB) state.teamB = teams[1]?.team_id || "";

  const selA = container.querySelector("#tr-team-a");
  const selB = container.querySelector("#tr-team-b");
  const fill = (sel, selected) => {
    sel.innerHTML = teams.map((t) => `<option value="${t.team_id}" ${t.team_id === selected ? "selected" : ""}>${escapeHtml(t.name)}</option>`).join("");
  };
  fill(selA, state.teamA);
  fill(selB, state.teamB);

  const refreshRosters = async () => {
    await showTeamRoster(container, "a", state.teamA);
    await showTeamRoster(container, "b", state.teamB);
  };
  selA.addEventListener("change", async (e) => { state.teamA = e.target.value; state.aSends = []; await refreshRosters(); });
  selB.addEventListener("change", async (e) => { state.teamB = e.target.value; state.bSends = []; await refreshRosters(); });
  await refreshRosters();
}

async function suggestTrades(container) {
  const panel = container.querySelector("#tr-matches");
  const btn = container.querySelector("#tr-suggest");
  btn.disabled = true;
  btn.textContent = "Finding matches…";
  panel.innerHTML = `<div class="loading">Scanning the league for complementary rosters&hellip;</div>`;
  try {
    const data = await api.tradeMatches({ league_key: state.leagueKey, team_id: state.teamA, format: state.format });
    const needStr = Object.keys(data.my_needs).join(", ") || "none obvious";
    if (!data.proposals.length) {
      panel.innerHTML = `<div class="empty-state">No clean positional matches found — ${escapeHtml(data.my_team_name)}'s needs (${escapeHtml(needStr)}) don't line up with another team's surplus right now.</div>`;
      return;
    }
    panel.innerHTML = `
      <div class="card" style="margin-top:12px;">
        <h3>Suggested trades for ${escapeHtml(data.my_team_name)} <span class="tag-note" style="font-weight:400;">you need: ${escapeHtml(needStr)}</span></h3>
        ${data.proposals.map((p, i) => `
          <div class="match-card">
            <div style="flex:1;min-width:0;">
              <div style="font-weight:700;margin-bottom:3px;">vs ${escapeHtml(p.partner_team_name)}
                <span class="delta-chip ${p.winner_side === "Team B" ? "delta-neg" : "delta-pos"}" style="font-size:11px;">${escapeHtml(p.verdict_label)}</span>
              </div>
              <div style="font-size:13.5px;">
                You send <strong>${escapeHtml(p.you_send.player.name)}</strong> (${p.you_send.position})
                → get <strong>${escapeHtml(p.you_receive.player.name)}</strong> (${p.you_receive.position})
              </div>
              <div class="tag-note">${escapeHtml(p.rationale)}${p.your_grade_before ? ` · your team ${p.your_grade_before} → ${p.your_grade_after}` : ""}</div>
            </div>
            <button data-match="${i}">Load</button>
          </div>
        `).join("")}
      </div>
    `;
    panel.querySelectorAll("button[data-match]").forEach((b) => {
      b.addEventListener("click", () => {
        const p = data.proposals[Number(b.dataset.match)];
        state.teamB = p.partner_team_id;
        const selB = container.querySelector("#tr-team-b");
        if (selB) selB.value = p.partner_team_id;
        state.aSends = [{ id: p.you_send.player.id, name: p.you_send.player.name, position: p.you_send.position }];
        state.bSends = [{ id: p.you_receive.player.id, name: p.you_receive.player.name, position: p.you_receive.position }];
        showTeamRoster(container, "a", state.teamA);
        showTeamRoster(container, "b", state.teamB);
        container.querySelector("#tr-analyze").click();
      });
    });
  } catch (err) {
    panel.innerHTML = `<div class="error-state">${escapeHtml(err.message)}</div>`;
  } finally {
    btn.disabled = false;
    btn.textContent = "✨ Suggest trades for Team A";
  }
}

async function showTeamRoster(container, key, teamId) {
  const team = state.league.teams.find((t) => t.team_id === teamId);
  const resultsEl = container.querySelector(`#results-${key}`);
  const searchEl = container.querySelector(`#search-${key}`);
  if (!team) { resultsEl.innerHTML = ""; return; }
  searchEl.style.display = "none";

  const data = await api.analyzeRoster({ player_ids: team.players, format: state.format });
  const roster = [...Object.values(data.starter_detail).filter(Boolean), ...data.bench, ...data.overflow];
  const stateKey = key === "a" ? "aSends" : "bSends";
  resultsEl.innerHTML = `
    <p class="tag-note" style="margin-bottom:6px;">Click players ${escapeHtml(team.name)} sends away:</p>
    <div style="max-height:260px;overflow-y:auto;">
      ${roster.map((p) => `
        <div class="player-search-row">
          <div>${posPill(p.position)} <span class="player-clickable" data-player-id="${p.id}" data-player-format="${state.format}">${escapeHtml(p.name)}</span> <span class="tag-note">${fmtNum(p.proj_points[state.format], 0)} proj</span></div>
          <button data-pid="${p.id}" data-name="${escapeHtml(p.name)}" data-pos="${p.position}">Send</button>
        </div>
      `).join("")}
    </div>
  `;
  resultsEl.querySelectorAll("button[data-pid]").forEach((btn) => {
    btn.addEventListener("click", () => {
      if (state[stateKey].some((p) => p.id === btn.dataset.pid)) return;
      state[stateKey].push({ id: btn.dataset.pid, name: btn.dataset.name, position: btn.dataset.pos });
      redrawChips(container, key, stateKey);
    });
  });
  redrawChips(container, key, stateKey);
}

function redrawChips(container, key, stateKey) {
  const chipsEl = container.querySelector(`#chips-${key}`);
  chipsEl.innerHTML = state[stateKey].map((p) => `
    <span class="chip">${posPill(p.position)} ${escapeHtml(p.name)}<button data-rm="${p.id}">&times;</button></span>
  `).join("");
  chipsEl.querySelectorAll("button[data-rm]").forEach((btn) => {
    btn.addEventListener("click", () => {
      state[stateKey] = state[stateKey].filter((p) => p.id !== btn.dataset.rm);
      redrawChips(container, key, stateKey);
    });
  });
}

function sideHtml(key, title, _stateKey) {
  return `
    <div class="trade-side">
      <h3>${title}</h3>
      <input type="text" id="search-${key}" placeholder="Search players…" style="width:100%;margin-bottom:8px;">
      <div id="results-${key}"></div>
      <div id="chips-${key}"></div>
    </div>
  `;
}

function wireSide(container, key, stateKey) {
  const search = container.querySelector(`#search-${key}`);
  const resultsEl = container.querySelector(`#results-${key}`);
  const chipsEl = container.querySelector(`#chips-${key}`);

  function renderChips() {
    chipsEl.innerHTML = state[stateKey].map((p) => `
      <span class="chip">${posPill(p.position)} ${escapeHtml(p.name)}<button data-rm="${p.id}">&times;</button></span>
    `).join("");
    chipsEl.querySelectorAll("button[data-rm]").forEach((btn) => {
      btn.addEventListener("click", () => {
        state[stateKey] = state[stateKey].filter((p) => p.id !== btn.dataset.rm);
        renderChips();
      });
    });
  }
  renderChips();

  const doSearch = debounce(async () => {
    const q = search.value.trim();
    if (!q) { resultsEl.innerHTML = ""; return; }
    const data = await api.listPlayers({ search: q, limit: "6" });
    resultsEl.innerHTML = data.players.map((p) => `
      <div class="player-search-row">
        <div>${posPill(p.position)} <span class="player-clickable" data-player-id="${p.id}" data-player-format="${state.format}">${escapeHtml(p.name)}</span> <span class="tag-note">${escapeHtml(p.team)}</span></div>
        <button data-pid="${p.id}" data-name="${escapeHtml(p.name)}" data-pos="${p.position}">Add</button>
      </div>
    `).join("") || `<div class="empty-state">No matches.</div>`;

    resultsEl.querySelectorAll("button[data-pid]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const id = btn.dataset.pid;
        if (state[stateKey].some((p) => p.id === id)) return;
        state[stateKey].push({ id, name: btn.dataset.name, position: btn.dataset.pos });
        renderChips();
      });
    });
  }, 250);
  search.addEventListener("input", doSearch);
}

function verdictClass(data) {
  if (!data.winner) return "verdict-fair";
  return data.imbalance_pct >= 50 ? "verdict-lopsided" : "verdict-edge";
}

function sideValueBlock(label, players, value) {
  const rows = players.map((p) => `
    <div class="slot-row">
      <span>${posPill(p.position)} <span class="player-clickable" data-player-id="${p.id}" data-player-format="${state.format}">${escapeHtml(p.name)}</span></span>
      <span class="tag-note">${fmtNum(p.proj_points[value.__fmt])} proj pts &middot; ${fmtNum(p.proj_vbd[value.__fmt])} VBD</span>
    </div>
  `).join("");
  return `
    <div class="card">
      <h3>${label}</h3>
      ${rows}
      <p class="tag-note" style="margin-top:8px;">Total: ${fmtNum(value.points_total)} pts &middot; ${fmtNum(value.vbd_total)} VBD</p>
    </div>
  `;
}

function gradeImpactBlock(label, impact) {
  if (!impact) return "";
  return `
    <div class="card">
      <h3>${label} &mdash; Lineup Grade Impact</h3>
      <div style="display:flex;gap:20px;align-items:center;">
        <div style="text-align:center;">
          <div class="grade-badge">${impact.before.grade}</div>
          <div class="tag-note">Before</div>
        </div>
        <div style="font-size:20px;color:var(--text-faint);">&rarr;</div>
        <div style="text-align:center;">
          <div class="grade-badge">${impact.after.grade}</div>
          <div class="tag-note">After</div>
        </div>
        <div style="font-size:13px;color:var(--text-dim);">
          Missing before: ${impact.before.missing_starter_slots.join(", ") || "none"}<br>
          Missing after: ${impact.after.missing_starter_slots.join(", ") || "none"}
        </div>
      </div>
    </div>
  `;
}

function renderResults(container, data) {
  const target = container.querySelector("#trade-results");
  data.team_a_sends_value.__fmt = data.format;
  data.team_b_sends_value.__fmt = data.format;

  target.innerHTML = `
    <div class="verdict-banner ${verdictClass(data)}">${escapeHtml(data.verdict)}</div>
    <div class="grid-2">
      ${sideValueBlock("Team A sends (Team B receives)", data.team_a_sends, data.team_a_sends_value)}
      ${sideValueBlock("Team B sends (Team A receives)", data.team_b_sends, data.team_b_sends_value)}
    </div>
    <div class="grid-2">
      ${gradeImpactBlock("Team A", data.team_a_roster_impact)}
      ${gradeImpactBlock("Team B", data.team_b_roster_impact)}
    </div>
  `;
}
