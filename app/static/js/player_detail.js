import { api } from "./api.js";
import { escapeHtml, posPill, fmtNum, avatar } from "./util.js";

// A single shared modal, opened by clicking any element carrying a
// data-player-id (and optional data-player-format). Set up once at startup.
let overlay = null;
let currentFormat = "ppr";

function ensureOverlay() {
  if (overlay) return overlay;
  overlay = document.createElement("div");
  overlay.className = "pd-overlay";
  overlay.style.display = "none";
  overlay.innerHTML = `<div class="pd-modal" role="dialog" aria-modal="true"><div class="pd-body"></div></div>`;
  overlay.addEventListener("click", (e) => { if (e.target === overlay) closeDetail(); });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeDetail(); });
  document.body.appendChild(overlay);
  return overlay;
}

function closeDetail() {
  if (overlay) overlay.style.display = "none";
}

function timeAgo(iso) {
  if (!iso) return "";
  const d = (Date.now() - new Date(iso).getTime()) / 1000;
  if (d < 3600) return `${Math.max(1, Math.round(d / 60))}m ago`;
  if (d < 86400) return `${Math.round(d / 3600)}h ago`;
  return `${Math.round(d / 86400)}d ago`;
}

export async function openPlayerDetail(id, format = currentFormat) {
  const ov = ensureOverlay();
  const body = ov.querySelector(".pd-body");
  body.innerHTML = `<div class="loading">Loading player&hellip;</div>`;
  ov.style.display = "flex";

  let d;
  try {
    d = await api.playerDetail(id, format);
  } catch (err) {
    body.innerHTML = `<div class="error-state">${escapeHtml(err.message || "Couldn't load player")}</div>
      <div style="text-align:right;margin-top:12px;"><button class="secondary pd-close">Close</button></div>`;
    body.querySelector(".pd-close").addEventListener("click", closeDetail);
    return;
  }

  const proj = d.proj_points ? fmtNum(d.proj_points[d.format]) : "—";
  const ranksHtml = d.ranks.map((r) => `
    <div class="pd-rank">
      <div class="pd-rank-label">${escapeHtml(r.label)}</div>
      <div class="pd-rank-val">${r.rank != null ? "#" + r.rank : "&mdash;"}</div>
    </div>`).join("");

  const newsHtml = d.news.length
    ? d.news.map((n) => `
        <a class="pd-news" href="${escapeHtml(n.link || "#")}" target="_blank" rel="noopener">
          ${n.image ? `<img src="${escapeHtml(n.image)}" alt="" loading="lazy">` : ""}
          <div>
            <div class="pd-news-head">${escapeHtml(n.headline)}</div>
            <div class="tag-note">${timeAgo(n.published)}${n.description ? " · " + escapeHtml(n.description.slice(0, 90)) : ""}</div>
          </div>
        </a>`).join("")
    : `<p class="tag-note">No recent national headlines mention ${escapeHtml(d.name)}. Use the links below for the latest reports.</p>`;

  const playoffSos = d.playoff_sos
    ? `<div class="tag-note">Playoff SOS (Wks 15&ndash;17) ${"★".repeat(d.playoff_sos.stars)}${"☆".repeat(5 - d.playoff_sos.stars)}
        &mdash; vs ${d.playoff_sos.opponents.map((o, i) => `Wk${15 + i}: ${o ? escapeHtml(o) : "BYE"}`).join(", ")}</div>`
    : "";

  const linksHtml = d.links.map((l) =>
    `<a class="pd-link" href="${escapeHtml(l.url)}" target="_blank" rel="noopener">${escapeHtml(l.label)} ↗</a>`).join("");

  const t = d.trending || {};
  const hasTrend = t.add != null || t.drop != null;
  const trendHtml = `
    <div class="pd-trend">
      <div class="pd-trend-stat add"><div class="pd-stat-v">${t.add != null ? "+" + t.add.toLocaleString() : "—"}</div><div class="pd-stat-l">Added (24h)</div></div>
      <div class="pd-trend-stat drop"><div class="pd-stat-v">${t.drop != null ? "−" + t.drop.toLocaleString() : "—"}</div><div class="pd-stat-l">Dropped (24h)</div></div>
    </div>
    <p class="tag-note">${hasTrend
      ? "Live add/drop momentum across Sleeper leagues — how the market is moving on him right now."
      : "No add/drop movement in the last 24h (quiet, or offseason). Check the live chatter:"}</p>
    <div class="pd-links">${(d.social || []).map((l) =>
      `<a class="pd-link" href="${escapeHtml(l.url)}" target="_blank" rel="noopener">${escapeHtml(l.label)} ↗</a>`).join("")}</div>`;

  body.innerHTML = `
    <div class="pd-header">
      <div class="pd-id">
        ${avatar(d, 48)}
        <div>
          <div class="pd-name">${escapeHtml(d.name)}</div>
          <div class="tag-note">${posPill(d.position || "?")} ${escapeHtml(d.team || "")}${d.bye ? ` · Bye ${d.bye}` : ""}${d.sos ? ` · SOS ${"★".repeat(d.sos)}${"☆".repeat(5 - d.sos)}` : ""}${d.injury_status ? ` · <span class="value-neg">${escapeHtml(d.injury_status)}</span>` : ""}${d.rookie ? " · Rookie" : ""}</div>
          ${playoffSos}
        </div>
      </div>
      <button class="pd-x" aria-label="Close">&times;</button>
    </div>

    <div class="pd-stats">
      <div class="pd-stat"><div class="pd-stat-v">${proj}</div><div class="pd-stat-l">Proj ${d.format.toUpperCase().replace("_", "-")}</div></div>
      <div class="pd-stat"><div class="pd-stat-v">${d.proj_pos_rank ? d.position + d.proj_pos_rank : "—"}</div><div class="pd-stat-l">Proj Pos Rank</div></div>
      <div class="pd-stat"><div class="pd-stat-v">${d.perf_rank ? "#" + d.perf_rank : "—"}</div><div class="pd-stat-l">Last-Yr Rank</div></div>
    </div>

    <h3 style="margin-top:16px;">Where each platform ranks him</h3>
    <div class="pd-ranks">${ranksHtml}</div>

    <h3 style="margin-top:18px;">Trending &amp; chatter</h3>
    ${trendHtml}

    <h3 style="margin-top:18px;">Latest news &amp; reports</h3>
    <div class="pd-news-list">${newsHtml}</div>
    <div class="pd-links">${linksHtml}</div>
  `;
  body.querySelector(".pd-x").addEventListener("click", closeDetail);
}

export function initPlayerDetail(getFormat) {
  ensureOverlay();
  document.addEventListener("click", (e) => {
    const el = e.target.closest("[data-player-id]");
    if (!el) return;
    // Don't hijack clicks on buttons/links inside a player row.
    if (e.target.closest("button, a")) return;
    e.preventDefault();
    const fmt = el.dataset.playerFormat || (getFormat && getFormat()) || currentFormat;
    currentFormat = fmt;
    openPlayerDetail(el.dataset.playerId, fmt);
  });
}
