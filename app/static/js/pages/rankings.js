import { api } from "../api.js";
import { escapeHtml, posPill, fmtNum, formatLabel, playerCell, avatar, tierBadge } from "../util.js";

const POSITIONS = ["ALL", "QB", "RB", "WR", "TE", "K", "DEF"];

const COLUMNS = [
  { key: "rank_a", label: "Rank", numeric: true },
  { key: "name", label: "Player", numeric: false },
  { key: "pos_rank", label: "Pos Rank", numeric: false },
  { key: "rank_b", label: "Rank", numeric: true },
  { key: "value_score", label: "Value", numeric: true },
  { key: "proj_points", label: "Proj Pts", numeric: true },
  { key: "perf_rank", label: "Last-Yr Rank", numeric: true },
];

const state = {
  format: "ppr",
  position: "ALL",
  // Default to the app's core question: where is ESPN's board wrong vs consensus?
  srcA: "espn_rank",   // source family (or imported set id)
  srcB: null,          // resolved after sources load: ECR if present, else projections
  sortKey: "rank_a",
  sortDir: 1,
  rows: [],
  sets: [],
  sources: [],         // [{id, name}] — format-agnostic
  rookiesOnly: false,
};

const FAMILY_RE = /^(adp|sleeper_adp|sleeper_dynasty|espn_rank|espn_adp|fp_ecr|proj|computed)_(standard|half_ppr|ppr)$/;

function buildSources() {
  const seen = new Set();
  const out = [];
  for (const s of state.sets) {
    const m = s.id.match(FAMILY_RE);
    if (m) {
      if (!seen.has(m[1])) {
        seen.add(m[1]);
        out.push({ id: m[1], name: s.name.replace(/\s*\((Standard|Half-PPR|PPR)\)\s*$/, "") });
      }
    } else {
      out.push({ id: s.id, name: s.name });
    }
  }
  state.sources = out;
}

function resolveSetId(src) {
  // Family sources resolve against the current format; imported ids pass through.
  return /^(adp|sleeper_adp|sleeper_dynasty|espn_rank|espn_adp|fp_ecr|proj|computed)$/.test(src) ? `${src}_${state.format}` : src;
}

function sourceName(src) {
  return state.sources.find((s) => s.id === src)?.name || src;
}

function cellValue(row, key) {
  if (key === "proj_points") return row.proj_points?.[state.format];
  if (key === "pos_rank") return row.pos_rank;
  return row[key];
}

function sortRows() {
  const { sortKey, sortDir } = state;
  const col = COLUMNS.find((c) => c.key === sortKey);
  state.rows.sort((a, b) => {
    const va = cellValue(a, sortKey);
    const vb = cellValue(b, sortKey);
    if (va === null || va === undefined) return 1;
    if (vb === null || vb === undefined) return -1;
    if (col?.numeric) return (va - vb) * sortDir;
    return String(va).localeCompare(String(vb), undefined, { numeric: true }) * sortDir;
  });
}

function setOptions(selected) {
  return state.sources.map((s) =>
    `<option value="${s.id}" ${s.id === selected ? "selected" : ""}>${escapeHtml(s.name)}</option>`
  ).join("");
}

export async function renderRankings(container) {
  if (!state.sets.length) {
    try {
      state.sets = (await api.listRankingSets()).sets;
    } catch (_) { state.sets = []; }
    buildSources();
  }
  if (!state.srcB) {
    state.srcB = state.sources.some((s) => s.id === "ecr") ? "ecr" : "proj";
  }

  container.innerHTML = `
    <h1>Rankings Comparison</h1>
    <p class="subtitle">
      Pick any two ranking systems and see where they disagree — that's where draft values live.
      Value scores are weighted by board position, so a rank 10-vs-18 disagreement screams while a
      237-vs-250 one whispers. Click column headers to sort.
    </p>
    <div class="card">
      <div class="controls">
        <label>Rankings A (row order)
          <select id="set-a-select">${setOptions(state.srcA)}</select>
        </label>
        <label style="color:var(--accent);">vs</label>
        <label>Rankings B (compare against)
          <select id="set-b-select">${setOptions(state.srcB)}</select>
        </label>
        <label>Format
          <select id="format-select">
            ${["standard", "half_ppr", "ppr"].map((f) => `<option value="${f}" ${f === state.format ? "selected" : ""}>${formatLabel(f)}</option>`).join("")}
          </select>
        </label>
        <label>Position
          <select id="position-select">
            ${POSITIONS.map((p) => `<option value="${p}" ${p === state.position ? "selected" : ""}>${p}</option>`).join("")}
          </select>
        </label>
        <label style="flex-direction:row;align-items:center;gap:8px;">
          <input type="checkbox" id="rookies-only-check" ${state.rookiesOnly ? "checked" : ""}>
          Rookies only
        </label>
      </div>
      <div id="rankings-table"><div class="loading">Loading&hellip;</div></div>
    </div>
  `;

  container.querySelector("#set-a-select").addEventListener("change", (e) => {
    state.srcA = e.target.value;
    loadTable(container);
  });
  container.querySelector("#set-b-select").addEventListener("change", (e) => {
    state.srcB = e.target.value;
    loadTable(container);
  });
  container.querySelector("#format-select").addEventListener("change", (e) => {
    state.format = e.target.value;
    loadTable(container);
  });
  container.querySelector("#position-select").addEventListener("change", (e) => {
    state.position = e.target.value;
    loadTable(container);
  });
  container.querySelector("#rookies-only-check").addEventListener("change", (e) => {
    state.rookiesOnly = e.target.checked;
    renderTable(container);
  });

  await loadTable(container);
}

async function loadTable(container) {
  const target = container.querySelector("#rankings-table");
  target.innerHTML = `<div class="loading">Loading&hellip;</div>`;

  const params = {
    format: state.format,
    limit: "300",
    set: resolveSetId(state.srcA),
    compare: resolveSetId(state.srcB),
  };
  if (state.position !== "ALL") params.position = state.position;

  const data = await api.compareRankings(params);
  state.rows = data.players;
  renderTable(container);
}

function valueChip(score, delta) {
  if (score === null || score === undefined) return "<span class='tag-note'>&mdash;</span>";
  const pct = Math.round(score * 100);
  if (pct === 0) return `<span class="delta-chip delta-zero">0%</span>`;
  const cls = pct > 0 ? "delta-pos" : "delta-neg";
  const magnitude = Math.abs(score) >= 0.3 ? " delta-big" : "";
  const spots = delta !== null && delta !== undefined ? `<div class="tag-note" style="margin:2px 0 0;">${delta > 0 ? "+" : ""}${delta} spots</div>` : "";
  return `<span class="delta-chip ${cls}${magnitude}">${pct > 0 ? "+" : ""}${pct}%</span>${spots}`;
}

function rowTint(score) {
  if (score === null || score === undefined) return "";
  if (score >= 0.25) return "value-row-pos";
  if (score <= -0.25) return "value-row-neg";
  return "";
}

function summaryStrip(nameA, nameB, rows) {
  // Draftable pool only, so deep-list noise can't crowd out real edges.
  const eligible = rows.filter((r) => r.value_score !== null && r.value_score !== undefined && r.rank_a && r.rank_a <= 180);
  const best = [...eligible].sort((a, b) => b.value_score - a.value_score).slice(0, 5).filter((r) => r.value_score > 0);
  const worst = [...eligible].sort((a, b) => a.value_score - b.value_score).slice(0, 5).filter((r) => r.value_score < 0);

  const rowHtml = (p) => `
    <div class="player-search-row">
      <div class="row-main">
        ${avatar(p, 26)}
        <span style="min-width:0;">
          <strong>${escapeHtml(p.name)}</strong>
          <span class="pill pos-${escapeHtml(p.position)}">${escapeHtml(p.pos_rank ?? p.position)}</span>
          <div class="tag-note">${nameA} #${p.rank_a} · ${nameB} #${p.rank_b}</div>
        </span>
      </div>
      ${valueChip(p.value_score, null)}
    </div>
  `;

  // Collapsed by default on mobile so the sortable table lands within ~1 screen; open on desktop.
  const openAttr = window.matchMedia("(max-width:760px)").matches ? "" : " open";

  return `
    <details class="rankings-summary-details"${openAttr}>
      <summary>💎 Top values &amp; landmines (tap to toggle)</summary>
      <div class="grid-2" style="margin-bottom:16px;">
        <div class="suggestion-card" style="border-left:3px solid var(--accent);">
          <h3 style="color:var(--accent);">💎 Best Values on ${nameA}</h3>
          ${best.map(rowHtml).join("") || `<div class="tag-note">No significant values found.</div>`}
        </div>
        <div class="suggestion-card" style="border-left:3px solid var(--danger);">
          <h3 style="color:var(--danger);">💣 Landmines on ${nameA}</h3>
          ${worst.map(rowHtml).join("") || `<div class="tag-note">No significant landmines found.</div>`}
        </div>
      </div>
    </details>
  `;
}

function renderTable(container) {
  const target = container.querySelector("#rankings-table");
  sortRows();
  const rows = state.rookiesOnly ? state.rows.filter((r) => r.rookie) : state.rows;

  if (!rows.length) {
    target.innerHTML = `<div class="empty-state">No players match this filter.</div>`;
    return;
  }

  const nameA = escapeHtml(sourceName(state.srcA));
  const nameB = escapeHtml(sourceName(state.srcB));

  const header = COLUMNS.map((c) => {
    const arrow = state.sortKey === c.key ? `<span class="sort-arrow">${state.sortDir === 1 ? "▲" : "▼"}</span>` : "";
    let label = c.label;
    if (c.key === "rank_a") label = `${nameA} Rank`;
    if (c.key === "rank_b") label = `${nameB} Rank`;
    if (c.key === "proj_points") label = `Proj ${formatLabel(state.format)} Pts`;
    const cls = c.key === "perf_rank" ? ' class="col-hide-mobile"' : "";
    return `<th data-key="${c.key}"${cls}>${label} ${arrow}</th>`;
  }).join("");

  // Tier dividers only make sense while rows are in ascending rank_a order (the default).
  const showTiers =
    state.sortKey === "rank_a" &&
    state.sortDir === 1 &&
    rows.some((r) => r.tier !== null && r.tier !== undefined);

  let prevTier = null;
  const rowsHtml = rows.map((p) => {
    let divider = "";
    if (showTiers && p.tier !== null && p.tier !== undefined && p.tier !== prevTier) {
      divider = `<tr class="tier-divider"><td colspan="7">Tier ${escapeHtml(p.tier)}</td></tr>`;
      prevTier = p.tier;
    }
    return `${divider}
    <tr class="${rowTint(p.value_score)}">
      <td style="font-weight:800;color:var(--text-dim);">${p.rank_a ?? "&mdash;"}</td>
      <td>${playerCell(p, `${escapeHtml(p.team)}${p.rookie ? " · <span style='color:var(--warning)'>Rookie</span>" : ""}`)}</td>
      <td><span class="pill pos-${escapeHtml(p.position)}">${escapeHtml(p.pos_rank ?? p.position)}</span>${tierBadge(p.tier)}</td>
      <td style="font-weight:700;">${p.rank_b ?? "&mdash;"}</td>
      <td>${valueChip(p.value_score, p.delta)}</td>
      <td>${fmtNum(p.proj_points?.[state.format])}</td>
      <td class="col-hide-mobile">${p.perf_rank ? "#" + p.perf_rank : "&mdash;"}</td>
    </tr>
  `;
  }).join("");

  target.innerHTML = `
    ${summaryStrip(nameA, nameB, rows)}
    <div class="table-wrap">
      <table>
        <thead><tr>${header}</tr></thead>
        <tbody>${rowsHtml}</tbody>
      </table>
    </div>
    <p class="tag-note">
      Value = (${nameA} rank − ${nameB} rank) ÷ ${nameB} rank, so disagreements at the top of the
      board weigh far more than the same gap deep in the list (rank 18 vs 10 = +80%; rank 250 vs 237 = +5%).
      <span class="delta-chip delta-pos" style="font-size:10px;">+%</span> ${nameA} ranks them worse than
      ${nameB} says they're worth — a value when drafting on ${nameA}.
      <span class="delta-chip delta-neg" style="font-size:10px;">-%</span> ${nameA} is paying more than
      ${nameB} justifies — a landmine. Proj Pts = projected ${formatLabel(state.format)} points.
    </p>
  `;

  target.querySelectorAll("th[data-key]").forEach((th) => {
    th.addEventListener("click", () => {
      const key = th.dataset.key;
      if (state.sortKey === key) {
        state.sortDir *= -1;
      } else {
        state.sortKey = key;
        state.sortDir = 1;
      }
      renderTable(container);
    });
  });
}
