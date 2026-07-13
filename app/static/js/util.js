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

export function el(html) {
  const template = document.createElement("template");
  template.innerHTML = html.trim();
  return template.content.firstElementChild;
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
