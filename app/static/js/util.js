export function escapeHtml(str) {
  return String(str ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

export function posPill(position) {
  return `<span class="pill pos-${escapeHtml(position)}">${escapeHtml(position)}</span>`;
}

export function fmtNum(n, digits = 1) {
  if (n === null || n === undefined || Number.isNaN(n)) return "&mdash;";
  return Number(n).toFixed(digits);
}

export function signed(n, digits = 1) {
  if (n === null || n === undefined) return "&mdash;";
  const v = Number(n);
  const cls = v > 0 ? "value-pos" : v < 0 ? "value-neg" : "";
  const sign = v > 0 ? "+" : "";
  return `<span class="${cls}">${sign}${v.toFixed(digits)}</span>`;
}

export function debounce(fn, wait = 250) {
  let t;
  return (...args) => {
    clearTimeout(t);
    t = setTimeout(() => fn(...args), wait);
  };
}

export function injuryBadge(status) {
  if (!status) return "";
  return ` <span class="tag-note" style="color:var(--warning)">${escapeHtml(status)}</span>`;
}

export function formatLabel(fmt) {
  return { standard: "Standard", half_ppr: "Half-PPR", ppr: "PPR" }[fmt] || fmt;
}

export function avatar(p, size = 30) {
  const isDef = p.position === "DEF";
  const url = isDef
    ? `/api/img/team/${String(p.team || p.id).toLowerCase()}`
    : `/api/img/player/${p.id}`;
  return `<img class="avatar" src="${url}" width="${size}" height="${size}" decoding="async" alt=""
    style="width:${size}px;height:${size}px;" onerror="this.style.visibility='hidden'">`;
}

export function playerCell(p, sub = "") {
  return `
    <span class="player-cell player-clickable" data-player-id="${escapeHtml(p.id)}" title="View player detail & news">
      ${avatar(p)}
      <span>
        <span class="p-name">${escapeHtml(p.name)}</span>
        ${sub ? `<div class="p-sub">${sub}</div>` : ""}
      </span>
    </span>
  `;
}

// Floating toast notifications. Container is created lazily on first use.
export function toast(message, type = "error", ms = 4000) {
  let wrap = document.getElementById("toast-wrap");
  if (!wrap) {
    wrap = document.createElement("div");
    wrap.id = "toast-wrap";
    wrap.className = "toast-wrap";
    document.body.appendChild(wrap);
  }
  const el = document.createElement("div");
  const cls = ["error", "success", "info"].includes(type) ? type : "error";
  el.className = `toast ${cls}`;
  el.innerHTML = escapeHtml(message);
  const dismiss = () => {
    if (!el.isConnected) return;
    el.remove();
    if (!wrap.childElementCount) wrap.remove();
  };
  el.addEventListener("click", dismiss);
  wrap.appendChild(el);
  if (ms > 0) setTimeout(dismiss, ms);
  return el;
}

// Styled confirm dialog reusing the .pd-overlay/.pd-modal look. Resolves
// true on OK, false on cancel / backdrop click / Escape.
export function confirmModal(message, opts = {}) {
  const okLabel = opts.okLabel ?? "Delete";
  const cancelLabel = opts.cancelLabel ?? "Cancel";
  return new Promise((resolve) => {
    const overlay = document.createElement("div");
    overlay.className = "pd-overlay";
    overlay.innerHTML = `
      <div class="pd-modal confirm-modal" role="dialog" aria-modal="true" style="max-width:420px;">
        <div class="pd-body">
          <div class="confirm-msg">${escapeHtml(message)}</div>
          <div class="confirm-actions">
            <button class="secondary" data-confirm="cancel">${escapeHtml(cancelLabel)}</button>
            <button class="danger" data-confirm="ok">${escapeHtml(okLabel)}</button>
          </div>
        </div>
      </div>
    `;
    let done = false;
    const close = (result) => {
      if (done) return;
      done = true;
      document.removeEventListener("keydown", onKey);
      overlay.remove();
      resolve(result);
    };
    const onKey = (e) => { if (e.key === "Escape") close(false); };
    overlay.addEventListener("click", (e) => {
      if (e.target === overlay) close(false);
      const btn = e.target.closest("[data-confirm]");
      if (btn) close(btn.getAttribute("data-confirm") === "ok");
    });
    document.addEventListener("keydown", onKey);
    document.body.appendChild(overlay);
    const ok = overlay.querySelector('[data-confirm="ok"]');
    if (ok) ok.focus();
  });
}

// Availability chip: chance a player is still on the board at your next pick.
export function availabilityChip(pct) {
  if (pct === null || pct === undefined) return "";
  const n = Number(pct);
  const cls = n >= 66 ? "avail-high" : n >= 33 ? "avail-mid" : "avail-low";
  return `<span class="avail-chip ${cls}" title="Chance still available at your next pick">${Math.round(n)}%</span>`;
}

// Tier badge: tiny 'T#' pill; empty string when tier is null/undefined.
export function tierBadge(tier) {
  if (tier === null || tier === undefined) return "";
  return `<span class="tier-badge">T${escapeHtml(tier)}</span>`;
}
