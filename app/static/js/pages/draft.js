import { api } from "../api.js";
import { escapeHtml, posPill, fmtNum, formatLabel, debounce, avatar, toast, availabilityChip, confirmModal } from "../util.js";

let draft = null;
let gradeData = null;
let viewingHistory = false; // true when showing an archived draft's report card
const boardFilters = { position: "ALL", search: "" };
let roomViewSet = "";       // "" = the room's own draft board; else a site family/id
let roomSources = [];       // [{id, name}] ranking families for the in-room switcher

// Mobile draft-room tab (module state so it survives the re-render that
// happens after every pick).
let roomMobileTab = "suggest";
const ROOM_MOBILE_TABS = [
  { id: "suggest", label: "Suggest" },
  { id: "board", label: "Board" },
  { id: "team", label: "My Team" },
  { id: "players", label: "Players" },
];

let topbarSyncBound = false;
function syncTopbarOffset() {
  const topbar = document.querySelector("header.topbar");
  if (topbar) document.documentElement.style.setProperty("--topbar-h", `${topbar.offsetHeight}px`);
}

const RANK_FAMILY_RE = /^(adp|sleeper_adp|sleeper_dynasty|espn_rank|espn_adp|fp_ecr|proj|computed)$/;

function rankingFamilies(sets) {
  const families = [];
  const seen = new Set();
  for (const s of sets) {
    const m = s.id.match(/^(adp|sleeper_adp|sleeper_dynasty|espn_rank|espn_adp|fp_ecr|proj|computed)_(standard|half_ppr|ppr)$/);
    if (m) {
      if (!seen.has(m[1])) {
        seen.add(m[1]);
        families.push({ id: m[1], name: s.name.replace(/\s*\((Standard|Half-PPR|PPR)\)\s*$/, "") });
      }
    } else {
      families.push({ id: s.id, name: s.name });
    }
  }
  return families;
}

function resolveViewSet(id) {
  if (!id) return null;
  return RANK_FAMILY_RE.test(id) ? `${id}_${draft.format}` : id;
}

const SETUP_KEY = "ffl_draft_setup";

function loadSetup() {
  try {
    return JSON.parse(localStorage.getItem(SETUP_KEY)) || {};
  } catch (_) { return {}; }
}

function saveSetup(setup) {
  try { localStorage.setItem(SETUP_KEY, JSON.stringify(setup)); } catch (_) { /* ignore */ }
}

export async function renderDraft(container) {
  if (!draft) {
    await renderSetup(container);
  } else if (draft.complete) {
    await renderGradeView(container);
  } else {
    try {
      await renderRoom(container);
    } catch (err) {
      // A live draft only exists in server memory; if it's gone (e.g. the
      // server restarted), drop back to setup instead of stranding the user.
      if (String(err.message || err).includes("draft not found")) {
        draft = null;
        gradeData = null;
        await renderSetup(container);
        return;
      }
      throw err;
    }
  }
}

/* ------------------------------------------------------------ setup */

async function renderSetup(container) {
  let sets = [];
  try { sets = (await api.listRankingSets()).sets; } catch (_) { /* ignore */ }
  // Collapse per-format variants: the scoring-format selector picks the variant.
  const families = rankingFamilies(sets);

  const saved = loadSetup();
  const savedTeams = [8, 10, 12, 14, 16].includes(saved.teams) ? saved.teams : 12;
  const savedFormat = ["standard", "half_ppr", "ppr"].includes(saved.format) ? saved.format : "ppr";
  const savedSrc = families.some((f) => f.id === saved.src) ? saved.src : "adp";
  const DEFAULT_ROSTER = { QB: 1, RB: 2, WR: 2, TE: 1, FLEX: 1, SUPERFLEX: 0, K: 1, DEF: 1, BENCH: 6 };
  const roster = { ...DEFAULT_ROSTER, ...(saved.roster || {}) };
  const ROSTER_ROWS = [
    ["QB", "QB"], ["RB", "RB"], ["WR", "WR"], ["TE", "TE"],
    ["FLEX", "FLEX (R/W/T)"], ["SUPERFLEX", "SUPERFLEX (Q/R/W/T)"],
    ["K", "K"], ["DEF", "DEF"], ["BENCH", "Bench"],
  ];

  container.innerHTML = `
    <h1>Mock Draft Simulator</h1>
    <p class="subtitle">
      Snake draft against need-aware AI opponents drafting off live preseason ADP
      (or any ranking set you import). Your last setup is remembered.
    </p>
    <div class="grid-2" style="align-items:start;">
      <div class="card" style="max-width:480px;margin-bottom:0;">
        <div class="controls" style="flex-direction:column;align-items:stretch;">
          <label>Number of teams
            <select id="ds-teams">
              ${[8, 10, 12, 14, 16].map((n) => `<option value="${n}" ${n === savedTeams ? "selected" : ""}>${n} teams</option>`).join("")}
            </select>
          </label>
          <label>Your draft slot
            <select id="ds-slot"></select>
          </label>
          <label>Scoring format
            <select id="ds-format">
              ${["standard", "half_ppr", "ppr"].map((f) => `<option value="${f}" ${f === savedFormat ? "selected" : ""}>${formatLabel(f)}</option>`).join("")}
            </select>
          </label>
          <label>AI draft logic
            <select id="ds-set">
              ${families.map((f) => `<option value="${f.id}" ${f.id === savedSrc ? "selected" : ""}>${escapeHtml(f.name)}</option>`).join("")}
            </select>
          </label>
          <p class="tag-note" style="margin:-4px 0 6px;">The board the AI opponents draft from. Inside the room you can toggle your own view between any rankings to spot steals &amp; landmines.</p>

          <details class="roster-config" ${saved.roster ? "open" : ""}>
            <summary>Roster settings <span class="tag-note" id="rc-summary"></span></summary>
            <div class="rc-grid">
              ${ROSTER_ROWS.map(([key, label]) => `
                <label class="rc-row">${label}
                  <input type="number" min="0" max="10" id="rc-${key}" value="${roster[key]}">
                </label>`).join("")}
            </div>
            <p class="tag-note">Starters per position + bench. Drives lineup slots, AI need logic, and grading. <a href="#" id="rc-reset">Reset to standard</a></p>
          </details>

          <button id="ds-start" style="margin-top:8px;">Start Mock Draft</button>
        </div>
      </div>
      <div>
        <div class="card">
          <h2>🔴 Live Draft Assist</h2>
          <p class="tag-note" style="margin:0 0 10px;">
            Drafting for real on Sleeper? Paste the draft ID from your draft-room URL
            (sleeper.com/draft/nfl/<strong>&lt;id&gt;</strong>) and get live best-available and
            steal alerts vs consensus while you're on the clock.
          </p>
          <div class="controls" style="margin-bottom:0;">
            <input type="text" id="la-id" placeholder="Sleeper draft ID" style="flex:1;min-width:180px;" value="${escapeHtml(saved.liveId || "")}">
            <button id="la-go">Assist</button>
          </div>
        </div>
        <div class="card" style="margin-bottom:0;">
          <h2>Past Drafts</h2>
          <div id="draft-history"><div class="loading">Loading&hellip;</div></div>
        </div>
      </div>
    </div>
  `;

  container.querySelector("#la-go").addEventListener("click", () => {
    const id = container.querySelector("#la-id").value.trim();
    if (!id) return;
    saveSetup({ ...loadSetup(), liveId: id });
    renderLiveAssist(container, id, container.querySelector("#ds-format").value);
  });

  const rosterInputs = () => Object.fromEntries(
    ROSTER_ROWS.map(([k]) => [k, Math.max(0, Math.min(10, Number(container.querySelector(`#rc-${k}`).value) || 0))])
  );
  const updateRosterSummary = () => {
    const r = rosterInputs();
    const starters = r.QB + r.RB + r.WR + r.TE + r.FLEX + r.SUPERFLEX + r.K + r.DEF;
    container.querySelector("#rc-summary").textContent = `· ${starters} starters + ${r.BENCH} bench = ${starters + r.BENCH} rounds`;
  };
  ROSTER_ROWS.forEach(([k]) => container.querySelector(`#rc-${k}`).addEventListener("input", updateRosterSummary));
  updateRosterSummary();
  container.querySelector("#rc-reset").addEventListener("click", (e) => {
    e.preventDefault();
    ROSTER_ROWS.forEach(([k]) => { container.querySelector(`#rc-${k}`).value = DEFAULT_ROSTER[k]; });
    updateRosterSummary();
  });

  const teamsSelect = container.querySelector("#ds-teams");
  const slotSelect = container.querySelector("#ds-slot");
  const fillSlots = (preferred) => {
    const n = Number(teamsSelect.value);
    const target = preferred && preferred >= 1 && preferred <= n ? preferred : Math.ceil(n / 2);
    slotSelect.innerHTML = Array.from({ length: n }, (_, i) => i + 1)
      .map((i) => `<option value="${i}" ${i === target ? "selected" : ""}>Pick ${i}</option>`)
      .join("");
  };
  teamsSelect.addEventListener("change", () => fillSlots());
  fillSlots(saved.slot);

  loadHistory(container);

  container.querySelector("#ds-start").addEventListener("click", async () => {
    const btn = container.querySelector("#ds-start");
    btn.textContent = "Starting…";
    btn.disabled = true;
    const body = {
      teams: Number(teamsSelect.value),
      user_slot: Number(slotSelect.value),
      format: container.querySelector("#ds-format").value,
    };
    const src = container.querySelector("#ds-set").value;
    // Family sources resolve against the chosen format; imported ids pass through.
    body.ranking_set = /^(adp|sleeper_adp|sleeper_dynasty|espn_rank|espn_adp|fp_ecr|proj|computed)$/.test(src)
      ? `${src}_${body.format}`
      : src;
    const roster = rosterInputs();
    body.roster_config = roster;
    saveSetup({ teams: body.teams, slot: body.user_slot, format: body.format, src, roster });
    try {
      gradeData = null;
      viewingHistory = false;
      roomMobileTab = "suggest";
      draft = await api.startDraft(body);
      await renderDraft(container);
    } catch (err) {
      btn.textContent = "Start Mock Draft";
      btn.disabled = false;
      toast(err.message || "Failed to start draft", "error");
    }
  });
}

async function loadHistory(container) {
  const target = container.querySelector("#draft-history");
  if (!target) return;
  let drafts = [];
  try { drafts = (await api.draftHistory()).drafts; } catch (_) { /* ignore */ }

  if (!drafts.length) {
    target.innerHTML = `<div class="empty-state">No completed drafts yet — finish a mock and its report card is saved here.</div>`;
    return;
  }

  target.innerHTML = `
    <div style="max-height:420px;overflow-y:auto;">
      ${drafts.map((d) => {
        const when = d.completed_at ? new Date(d.completed_at * 1000).toLocaleString([], { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }) : "";
        const gradeCls = d.grade && (d.grade.startsWith("C") || d.grade.startsWith("D")) ? "grade-D" : "";
        return `
          <div class="player-search-row">
            <div class="row-main">
              <span class="grade-badge ${gradeCls}" style="width:38px;height:38px;font-size:15px;border-radius:10px;flex-shrink:0;">${d.grade || "?"}</span>
              <span style="min-width:0;">
                <strong>${d.teams}-Team ${formatLabel(d.format)}</strong> · Pick ${d.user_slot}
                <div class="tag-note">${when}${d.league_rank ? ` · finished #${d.league_rank}/${d.teams}` : ""}</div>
              </span>
            </div>
            <div style="display:flex;gap:6px;flex-shrink:0;">
              <button class="secondary" data-view="${d.id}">View</button>
              <button class="danger" data-del="${d.id}">&times;</button>
            </div>
          </div>`;
      }).join("")}
    </div>
  `;

  target.querySelectorAll("button[data-view]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const record = await api.draftHistoryDetail(btn.dataset.view);
      draft = record.state;
      gradeData = record.grade;
      viewingHistory = true;
      await renderDraft(container);
    });
  });
  target.querySelectorAll("button[data-del]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      if (!(await confirmModal("Delete this draft from history?"))) return;
      await api.deleteDraftHistory(btn.dataset.del);
      await loadHistory(container);
    });
  });
}

/* ------------------------------------------------------------ snake board */

function pickNoFor(round, column, teams) {
  // Odd rounds go left→right, even rounds snake back.
  return round % 2 === 1
    ? (round - 1) * teams + column
    : (round - 1) * teams + (teams - column + 1);
}

function snakeBoardHtml(maxRounds = null) {
  const teams = draft.teams;
  const rounds = maxRounds || draft.rounds;
  const byPickNo = {};
  draft.picks.forEach((p) => { byPickNo[p.pick_no] = p; });
  const currentPickNo = draft.complete ? -1 : draft.current_pick_index + 1;

  let cells = `<div class="snake-round"></div>`;
  for (let t = 1; t <= teams; t++) {
    const you = t === draft.user_slot;
    cells += `<div class="snake-head ${you ? "you" : ""}">${you ? "You" : "T" + t}</div>`;
  }

  for (let r = 1; r <= rounds; r++) {
    cells += `<div class="snake-round">R${r}</div>`;
    for (let t = 1; t <= teams; t++) {
      const pickNo = pickNoFor(r, t, teams);
      const pick = byPickNo[pickNo];
      const isUserCol = t === draft.user_slot;
      if (pick) {
        const last = pick.name.split(" ").slice(-1)[0];
        const first = pick.name.split(" ")[0];
        const short = pick.name.length > 15 ? `${first[0]}. ${last}` : pick.name;
        cells += `
          <div class="snake-cell pos-${pick.position} player-clickable ${isUserCol ? "user-col" : ""}" data-player-id="${pick.player_id}" data-player-format="${draft.format}" title="${escapeHtml(pick.name)} — pick ${pick.pick_no} (rank #${pick.draft_rank})">
            <span class="c-name">${escapeHtml(short)}</span>
            <span class="c-meta">${pick.position} · ${escapeHtml(pick.nfl_team)} · #${pick.pick_no}</span>
          </div>`;
      } else {
        const onClock = pickNo === currentPickNo;
        cells += `<div class="snake-cell ${isUserCol ? "user-col" : ""} ${onClock ? "on-clock" : ""}">${onClock ? `<span class="c-meta" style="color:var(--accent);font-weight:800;">ON THE CLOCK</span>` : `<span class="c-meta" style="opacity:.4;">#${pickNo}</span>`}</div>`;
      }
    }
  }

  return `
    <div class="snake-wrap">
      <div class="snake-grid" style="grid-template-columns: 34px repeat(${teams}, minmax(86px, 1fr));">
        ${cells}
      </div>
    </div>
  `;
}

/* ------------------------------------------------------------ draft room */

function applyRoomMobileTab(container) {
  container.querySelectorAll(".room-pane").forEach((pane) => {
    pane.classList.toggle("active", pane.dataset.pane === roomMobileTab);
  });
  container.querySelectorAll("[data-mobile-tab]").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.mobileTab === roomMobileTab);
  });
}

async function renderRoom(container) {
  container.innerHTML = `
    <div class="room-header">
      <div class="room-title">
        <h1 style="margin:0;">Draft Room</h1>
        <span class="room-sub">${draft.teams}-Team ${formatLabel(draft.format)} · Round ${draft.current_round}/${draft.rounds} · Pick #${draft.current_pick_index + 1}</span>
      </div>
      <div class="room-status ${draft.is_user_turn ? "clock" : ""}">${draft.is_user_turn ? "⏱ You're on the clock" : "AI drafting…"}</div>
      <button class="secondary" id="new-draft-btn">New Draft</button>
    </div>

    <div class="seg-tabs room-mobile-tabs">
      ${ROOM_MOBILE_TABS.map((t) => `<button class="seg ${roomMobileTab === t.id ? "active" : ""}" data-mobile-tab="${t.id}">${t.label}</button>`).join("")}
    </div>

    <div class="draft-cockpit three">
      <div class="cockpit-col" style="min-width:0;">
        <div class="room-pane" data-pane="board">
          <div class="card">
            <h2>Draft Board</h2>
            ${snakeBoardHtml(Math.min(draft.rounds, Math.max(draft.current_round + 1, 4)))}
          </div>
        </div>
        <div class="room-pane" data-pane="players">
          <div class="card">
            <h2>All Available Players</h2>
            <div class="controls">
              <input type="text" id="avail-search" placeholder="Search players…" value="${escapeHtml(boardFilters.search)}" style="flex:1;max-width:300px;">
              <select id="avail-position">
                ${["ALL", "QB", "RB", "WR", "TE", "K", "DEF"].map((p) => `<option value="${p}" ${p === boardFilters.position ? "selected" : ""}>${p}</option>`).join("")}
              </select>
              <label style="flex-direction:row;align-items:center;gap:8px;">View by
                <select id="avail-view"><option value="">Draft board (${escapeHtml(draft.ranking_set)})</option></select>
              </label>
            </div>
            <div id="available-list" class="avail-grid cockpit-scroll"><div class="loading">Loading&hellip;</div></div>
          </div>
        </div>
      </div>

      <div class="room-pane" data-pane="suggest">
        <div class="card cockpit-scroll">
          <h2>Suggested Picks <span class="tag-note" style="font-weight:400;">values measured vs consensus (ECR)</span></h2>
          <div id="avail-note"></div>
          <div id="urgency-banner"></div>
          <div id="suggestions-panel" class="grid-3"><div class="loading">Loading&hellip;</div></div>
          <div id="position-values" style="margin-top:12px;"></div>
        </div>
      </div>

      <div class="room-pane" data-pane="team">
        <div class="card cockpit-scroll">
          <h2>Your Team</h2>
          <div id="lineup-panel"></div>
        </div>
      </div>
    </div>
  `;

  applyRoomMobileTab(container);
  container.querySelectorAll("[data-mobile-tab]").forEach((btn) => {
    btn.addEventListener("click", () => {
      roomMobileTab = btn.dataset.mobileTab;
      applyRoomMobileTab(container);
    });
  });

  syncTopbarOffset();
  if (!topbarSyncBound) {
    window.addEventListener("resize", syncTopbarOffset);
    topbarSyncBound = true;
  }

  container.querySelector("#new-draft-btn").addEventListener("click", async () => {
    draft = null;
    gradeData = null;
    roomMobileTab = "suggest";
    await renderDraft(container);
  });

  const search = container.querySelector("#avail-search");
  const posFilter = container.querySelector("#avail-position");
  const viewSel = container.querySelector("#avail-view");
  const debouncedReload = debounce(() => loadAvailable(container), 250);
  search.addEventListener("input", (e) => { boardFilters.search = e.target.value; debouncedReload(); });
  posFilter.addEventListener("change", (e) => { boardFilters.position = e.target.value; loadAvailable(container); });
  viewSel.addEventListener("change", (e) => { roomViewSet = e.target.value; loadAvailable(container); });

  // Populate the in-room ranking switcher (site ADP / rankings to view by).
  if (!roomSources.length) {
    try { roomSources = rankingFamilies((await api.listRankingSets()).sets); } catch (_) { roomSources = []; }
  }
  viewSel.innerHTML = `<option value="">Draft board (${escapeHtml(draft.ranking_set)})</option>` +
    roomSources.map((s) => `<option value="${s.id}" ${s.id === roomViewSet ? "selected" : ""}>${escapeHtml(s.name)}</option>`).join("");

  renderLineup(container.querySelector("#lineup-panel"));
  await Promise.all([loadSuggestions(container), loadAvailable(container)]);
}

function suggestionCard(title, players, extra) {
  const rows = players.length
    ? players.map((p) => `
        <div class="player-search-row">
          <div class="row-main">
            <span class="rank-chip">#${p.draft_rank ?? "—"}</span>
            ${avatar(p, 26)}
            <span style="min-width:0;">
              <strong class="player-clickable" data-player-id="${p.id}" data-player-format="${draft.format}" title="Player detail & news">${escapeHtml(p.name)}</strong> ${posPill(p.position)}${availabilityChip(p.availability)}
              ${extra && extra(p) ? `<div class="tag-note">${escapeHtml(extra(p))}</div>` : ""}
            </span>
          </div>
          <button data-pid="${p.id}" ${draft.is_user_turn ? "" : "disabled"}>Draft</button>
        </div>
      `).join("")
    : `<div class="tag-note" style="padding:8px 0;">Nothing to suggest right now.</div>`;
  return `<div class="suggestion-card"><h3>${title}</h3>${rows}</div>`;
}

async function loadSuggestions(container) {
  const panel = container.querySelector("#suggestions-panel");
  if (!panel) return;
  const sug = await api.draftSuggestions(draft.id);
  if (sug.complete) { panel.innerHTML = ""; return; }

  const availNote = container.querySelector("#avail-note");
  if (availNote) {
    availNote.innerHTML = sug.picks_until_next > 0
      ? `<p class="tag-note" style="margin:2px 0 8px;">Availability = chance the player is still on the board at your next pick (~${sug.picks_until_next} picks away).</p>`
      : "";
  }

  const banner = container.querySelector("#urgency-banner");
  if (banner) {
    if (sug.urgent) {
      banner.innerHTML = `
        <div class="error-state" style="margin-bottom:12px;">
          ⚠️ ${sug.remaining_picks} pick${sug.remaining_picks === 1 ? "" : "s"} left and
          ${sug.open_starter_slots.length} open starter slot${sug.open_starter_slots.length === 1 ? "" : "s"}:
          <strong>${sug.open_starter_slots.join(", ")}</strong>. Suggestions are narrowed to what you still need —
          an empty starter slot scores zero every week.
        </div>`;
    } else if (sug.open_starter_slots?.length && sug.remaining_picks <= sug.open_starter_slots.length + 3) {
      banner.innerHTML = `
        <div class="tag-note" style="margin-bottom:10px;">
          Open starter slots: <strong>${sug.open_starter_slots.join(", ")}</strong> · ${sug.remaining_picks} picks remaining.
        </div>`;
    } else {
      banner.innerHTML = "";
    }
  }
  panel.innerHTML = [
    suggestionCard("Best Available", sug.best_available, null),
    suggestionCard("Values on the Board", sug.best_value, (p) => `ECR #${p.ref_rank} — fallen ${p.value_fall} spots${p.value_fall_pct ? ` (+${p.value_fall_pct}%)` : ""}`),
    suggestionCard("Best Fit for Your Team", sug.best_fit, (p) => p.fit_reason || ""),
  ].join("");
  panel.querySelectorAll("button[data-pid]").forEach((btn) => {
    btn.addEventListener("click", () => makePick(container, btn));
  });

  // Ideal value at every position, refreshed each pick.
  const posPanel = container.querySelector("#position-values");
  if (posPanel && sug.by_position?.length) {
    posPanel.innerHTML = `
      <h3>Ideal Value by Position</h3>
      <div class="pos-value-strip">
        ${sug.by_position.map((p) => {
          const chip = availabilityChip(p.availability);
          return `
          <div class="pos-value-card pos-border-${p.position}">
            <div style="display:flex;align-items:center;gap:8px;">
              ${avatar(p, 26)}
              <div style="min-width:0;">
                <div class="player-clickable" data-player-id="${p.id}" data-player-format="${draft.format}" title="Player detail & news" style="font-weight:750;font-size:12.5px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">${escapeHtml(p.name)}</div>
                <div class="tag-note" style="margin:0;">${posPill(p.position)} ECR #${p.ref_rank ?? "—"}${p.value_fall > 0 ? ` · <span class="value-pos">+${p.value_fall} value</span>` : ""}${chip ? ` · ${chip}` : ""}</div>
              </div>
            </div>
            <button data-pid="${p.id}" ${draft.is_user_turn ? "" : "disabled"}>Draft</button>
          </div>
          `;
        }).join("")}
      </div>
    `;
    posPanel.querySelectorAll("button[data-pid]").forEach((btn) => {
      btn.addEventListener("click", () => makePick(container, btn));
    });
  } else if (posPanel) {
    posPanel.innerHTML = "";
  }
}

async function makePick(container, btn) {
  btn.disabled = true;
  btn.textContent = "…";
  try {
    draft = await api.makeDraftPick(draft.id, btn.dataset.pid);
    await renderDraft(container);
  } catch (err) {
    toast(err.message || "Pick failed", "error");
    await renderDraft(container);
  }
}

async function loadAvailable(container) {
  const target = container.querySelector("#available-list");
  if (!target) return;
  target.innerHTML = `<div class="loading">Loading&hellip;</div>`;

  const params = { limit: "60" };
  if (boardFilters.position !== "ALL") params.position = boardFilters.position;
  const viewSet = resolveViewSet(roomViewSet);
  if (viewSet) params.view_set = viewSet;
  let players = await api.availableInDraft(draft.id, params);
  if (boardFilters.search.trim()) {
    const needle = boardFilters.search.trim().toLowerCase();
    players = players.filter((p) => p.name.toLowerCase().includes(needle));
  }

  if (!players.length) {
    target.innerHTML = `<div class="empty-state">No available players match this filter.</div>`;
    return;
  }

  const viewName = roomViewSet ? (roomSources.find((s) => s.id === roomViewSet)?.name || "site") : null;
  target.innerHTML = players.map((p) => {
    const rank = viewSet ? p.view_rank : p.draft_rank;
    return `
    <div class="player-search-row">
      <div class="row-main">
        <span class="rank-chip">#${rank ?? "—"}</span>
        ${avatar(p, 26)}
        <span style="min-width:0;">
          <strong class="player-clickable" data-player-id="${p.id}" data-player-format="${draft.format}" title="Player detail & news">${escapeHtml(p.name)}</strong> ${posPill(p.position)}${availabilityChip(p.availability)}
          <span class="tag-note">${escapeHtml(p.team)}${p.rookie ? " · Rookie" : ""} · ${fmtNum(p.proj_points[draft.format])} proj${viewSet ? ` · board #${p.draft_rank ?? "—"}` : ""}</span>
        </span>
      </div>
      <button data-pid="${p.id}" ${draft.is_user_turn ? "" : "disabled"}>Draft</button>
    </div>`;
  }).join("");

  target.querySelectorAll("button[data-pid]").forEach((btn) => {
    btn.addEventListener("click", () => makePick(container, btn));
  });
}

function slotRow(slotName, p) {
  return `
    <div class="slot-row">
      <span class="slot-name">${slotName}</span>
      ${p ? `
        <span class="slot-player">
          ${avatar(p, 24)}
          ${posPill(p.position)}
          <span class="p-name player-clickable" data-player-id="${p.id}" data-player-format="${draft.format}" title="Player detail & news">${escapeHtml(p.name)}</span>
        </span>
        <span class="slot-pts">${fmtNum(p.proj_points[draft.format], 0)}</span>
      ` : `<span class="empty">empty</span>`}
    </div>
  `;
}

function renderLineup(target) {
  if (!draft.user_lineup) {
    target.innerHTML = `<div class="empty-state">No picks yet.</div>`;
    return;
  }
  const starterRows = Object.entries(draft.user_lineup.starters)
    .map(([slot, p]) => slotRow(slot, p)).join("");
  const benchRows = draft.user_lineup.bench
    .map((p, i) => slotRow(`BE${i + 1}`, p)).join("");
  const benchSize = draft.roster_config?.BENCH ?? 6;
  const emptyBench = Math.max(0, benchSize - draft.user_lineup.bench.length);
  const emptyBenchRows = Array.from({ length: emptyBench }, (_, i) =>
    slotRow(`BE${draft.user_lineup.bench.length + i + 1}`, null)).join("");

  target.innerHTML = `
    <h3>Starters</h3>
    ${starterRows}
    <h3 style="margin-top:14px;">Bench</h3>
    ${benchRows}${emptyBenchRows}
  `;
}

/* ------------------------------------------------------------ grade view */

async function renderGradeView(container) {
  container.innerHTML = `<div class="loading">Grading your draft&hellip;</div>`;
  if (!gradeData) {
    try {
      gradeData = await api.draftGrade(draft.id);
    } catch (err) {
      container.innerHTML = `<div class="error-state">Could not grade draft: ${escapeHtml(err.message)}</div>`;
      return;
    }
  }
  const g = gradeData;

  const leagueRows = g.league_table.map((row) => `
    <tr class="${row.is_user ? "user-row" : ""}">
      <td>${row.rank}</td>
      <td>Team ${row.team}${row.is_user ? " (you)" : ""}</td>
      <td>${fmtNum(row.starter_vbd)}</td>
      <td>${row.missing_starter_slots.length ? row.missing_starter_slots.join(", ") : "&mdash;"}</td>
    </tr>
  `).join("");

  const posRows = g.positional.map((p) => `
    <tr>
      <td>${posPill(p.position)}</td>
      <td>${fmtNum(p.your_vbd)}</td>
      <td>${fmtNum(p.league_avg_vbd)}</td>
      <td class="${p.diff > 0 ? "value-pos" : p.diff < 0 ? "value-neg" : ""}">${p.diff > 0 ? "+" : ""}${fmtNum(p.diff)}</td>
      <td>${p.verdict === "strength" ? "💪 Strength" : p.verdict === "weakness" ? "⚠️ Weakness" : "Average"}</td>
    </tr>
  `).join("");

  const slipRows = g.slips.length
    ? g.slips.map((s) => `
        <div class="slot-row" style="align-items:flex-start;">
          <span class="slot-name">R${s.round}</span>
          <span style="text-align:right;">
            Took <strong>${escapeHtml(s.picked)}</strong> (${s.picked_position}, ${s.picked_rank ? `ECR #${s.picked_rank}` : "unranked on ECR"})
            while <strong>${escapeHtml(s.better_option)}</strong> (${s.better_position}, ECR #${s.better_rank}) was on the board
            <span class="tag-note">&mdash; ${s.rank_diff} consensus spots earlier${s.vbd_diff > 0 ? `, worth +${fmtNum(s.vbd_diff)} projected VBD` : ""}</span>
          </span>
        </div>
      `).join("")
    : `<p class="tag-note">No significant reaches — clean draft.</p>`;

  container.innerHTML = `
    <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:10px;margin-bottom:14px;">
      <div>
        <h1 style="margin:0;">Draft Report Card</h1>
        ${viewingHistory ? `<span class="tag-note">Archived draft — completed ${draft.teams}-team ${formatLabel(draft.format)}</span>` : ""}
      </div>
      <button class="secondary" id="new-draft-btn">${viewingHistory ? "Back to Draft Setup" : "New Draft"}</button>
    </div>

    <div class="card">
      <div style="display:flex;align-items:center;gap:20px;flex-wrap:wrap;">
        <div class="grade-badge ${g.grade.startsWith("C") || g.grade.startsWith("D") ? "grade-D" : ""}" style="width:76px;height:76px;font-size:30px;">${g.grade}</div>
        <div style="flex:1;min-width:260px;">
          <div style="font-weight:800;font-size:17px;margin-bottom:4px;">#${g.league_rank} of ${g.teams} teams</div>
          <p style="margin:0;color:var(--text-dim);font-size:14px;">${escapeHtml(g.summary)}</p>
        </div>
      </div>
    </div>

    <div class="card">
      <details class="full-board-details" ${window.matchMedia("(max-width: 760px)").matches ? "" : "open"}>
        <summary>Show full draft board</summary>
        <div style="margin-top:12px;">${snakeBoardHtml()}</div>
      </details>
    </div>

    <div class="grid-2">
      <div>
        <div class="card">
          <h2>League Comparison</h2>
          <div class="table-wrap" style="max-height:420px;">
            <table>
              <thead><tr><th>Rank</th><th>Team</th><th>Starter VBD</th><th>Holes</th></tr></thead>
              <tbody>${leagueRows}</tbody>
            </table>
          </div>
        </div>
        <div class="card">
          <h2>Your Team</h2>
          <div id="final-lineup"></div>
        </div>
      </div>
      <div>
        <div class="card">
          <h2>Positional Strengths &amp; Weaknesses</h2>
          <div class="table-wrap">
            <table>
              <thead><tr><th>Pos</th><th>You</th><th>League Avg</th><th>Diff</th><th>Verdict</th></tr></thead>
              <tbody>${posRows}</tbody>
            </table>
          </div>
        </div>
        <div class="card">
          <h2>Where You Slipped</h2>
          ${slipRows}
          ${g.slips.length ? `<p class="tag-note" style="margin-top:10px;">Cleaner picks at these spots could have added roughly <strong>+${fmtNum(g.potential_vbd_gain)} VBD</strong> to your starting lineup${g.potential_vbd_gain > 60 ? " — likely a letter grade or more" : ""}.</p>` : ""}
        </div>
      </div>
    </div>
  `;

  renderLineup(container.querySelector("#final-lineup"));
  container.querySelector("#new-draft-btn").addEventListener("click", async () => {
    draft = null;
    gradeData = null;
    await renderDraft(container);
  });
}

/* ------------------------------------------------------------ live assist */

let liveTimer = null;

async function renderLiveAssist(container, draftId, fmt) {
  if (liveTimer) { clearInterval(liveTimer); liveTimer = null; }

  const draw = async () => {
    let d;
    try {
      d = await api.liveDraft(draftId, fmt);
    } catch (err) {
      if (liveTimer) { clearInterval(liveTimer); liveTimer = null; }
      container.innerHTML = `
        <div class="error-state">${escapeHtml(err.message || "Couldn't reach that draft")}</div>
        <button class="secondary" id="la-back" style="margin-top:12px;">Back</button>`;
      container.querySelector("#la-back").addEventListener("click", () => { draft = null; renderDraft(container); });
      return;
    }

    const statusChip = d.status === "complete"
      ? `<span class="delta-chip delta-zero">draft complete</span>`
      : `<span class="delta-chip delta-pos">LIVE · pick #${d.current_pick} (R${d.current_round})</span>`;

    const slimRow = (p, extra) => `
      <div class="player-search-row" data-player-id="${p.id}" data-player-format="${fmt}" style="cursor:pointer;">
        <div class="row-main">
          <span class="rank-chip">${p.ecr ? "#" + p.ecr : "—"}</span>
          ${posPill(p.position)}
          <span style="min-width:0;"><strong>${escapeHtml(p.name)}</strong>
            <span class="tag-note">${escapeHtml(p.team || "")} · ${fmtNum(p.proj_points)} proj${extra || ""}</span>
          </span>
        </div>
      </div>`;

    container.innerHTML = `
      <div class="room-header">
        <div class="room-title">
          <h1 style="margin:0;">Live Draft Assist</h1>
          <span class="room-sub">${d.teams || "?"}-team Sleeper draft · ${d.picks_made} picks made · values vs ${d.reference}</span>
        </div>
        ${statusChip}
        <button class="secondary" id="la-back">Exit</button>
      </div>

      <div class="grid-2" style="align-items:start;">
        <div>
          <div class="card">
            <h2>💎 Steals on the Board</h2>
            ${d.best_values.length
              ? d.best_values.map((p) => slimRow(p, ` · <span class="value-pos">fallen ${p.value_fall} past ECR</span>`)).join("")
              : `<p class="tag-note">No one has fallen meaningfully past consensus yet.</p>`}
          </div>
          <div class="card">
            <h2>Best Available by Position</h2>
            ${d.by_position.map((p) => slimRow(p)).join("")}
          </div>
        </div>
        <div>
          <div class="card">
            <h2>Best Available Overall (ECR)</h2>
            ${d.best_available.map((p) => slimRow(p)).join("")}
          </div>
          <div class="card">
            <h2>Recent Picks</h2>
            ${d.recent_picks.map((p) => `
              <div class="pick-item">
                <span class="pick-no">${p.pick_no ?? ""}</span>
                ${posPill(p.position || "?")}
                <span>${escapeHtml(p.name || "—")}</span>
                <span class="tag-note">R${p.round ?? "?"} · slot ${p.picked_by_slot ?? "?"}</span>
              </div>`).join("") || `<p class="tag-note">No picks yet.</p>`}
          </div>
        </div>
      </div>
      <p class="tag-note">Auto-refreshes every 10 seconds while the draft is live.</p>
    `;

    container.querySelector("#la-back").addEventListener("click", () => {
      if (liveTimer) { clearInterval(liveTimer); liveTimer = null; }
      draft = null;
      renderDraft(container);
    });

    if (d.status === "complete" && liveTimer) { clearInterval(liveTimer); liveTimer = null; }
  };

  await draw();
  liveTimer = setInterval(() => {
    // Stop polling if the user navigated away from this view.
    if (!document.querySelector("#la-back")) { clearInterval(liveTimer); liveTimer = null; return; }
    draw();
  }, 10000);
}
