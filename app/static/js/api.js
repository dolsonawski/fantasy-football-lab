const BASE = "";

async function request(path, options = {}) {
  let res;
  try {
    res = await fetch(BASE + path, {
      headers: { "Content-Type": "application/json" },
      ...options,
    });
  } catch (_) {
    // fetch() rejects only on a network-level failure (server down, no
    // connection) — never on an HTTP error status.
    const err = new Error("Can't reach the server. Make sure it's running (or the site is deployed) and you're online.");
    err.isNetwork = true;
    throw err;
  }
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail || JSON.stringify(body);
    } catch (_) { /* ignore */ }
    const err = new Error(detail);
    err.status = res.status;
    throw err;
  }
  return res.json();
}

export const api = {
  getMeta: () => request(`/api/meta`),

  me: () => request(`/api/auth/me`),
  signup: (body) => request(`/api/auth/signup`, { method: "POST", body: JSON.stringify(body) }),
  login: (body) => request(`/api/auth/login`, { method: "POST", body: JSON.stringify(body) }),
  logout: () => request(`/api/auth/logout`, { method: "POST" }),

  tradeMatches: (params = {}) =>
    request(`/api/trade/matches?${new URLSearchParams(params)}`),

  listPlayers: (params = {}) =>
    request(`/api/players?${new URLSearchParams(params)}`),

  playerDetail: (id, format = "ppr") =>
    request(`/api/players/${id}/detail?format=${format}`),

  compareRankings: (params = {}) =>
    request(`/api/rankings/compare?${new URLSearchParams(params)}`),

  listRankingSets: () => request(`/api/rankings/sets`),

  deleteRankingSet: (setId) =>
    request(`/api/rankings/sets/${setId}`, { method: "DELETE" }),

  importRankings: async (file, name) => {
    const form = new FormData();
    form.append("file", file);
    form.append("name", name || "");
    const res = await fetch(`/api/rankings/import`, { method: "POST", body: form });
    if (!res.ok) {
      let detail = res.statusText;
      try { detail = (await res.json()).detail || detail; } catch (_) { /* ignore */ }
      throw new Error(detail);
    }
    return res.json();
  },

  draftSuggestions: (draftId) => request(`/api/draft/${draftId}/suggestions`),

  importLeague: (body) =>
    request(`/api/league/import`, { method: "POST", body: JSON.stringify(body) }),

  listLeagues: () => request(`/api/league`),

  getLeague: (key) => request(`/api/league/${key}`),

  deleteLeague: (key) => request(`/api/league/${key}`, { method: "DELETE" }),

  startSit: (params = {}) => request(`/api/season/start-sit?${new URLSearchParams(params)}`),
  waivers: (params = {}) => request(`/api/season/waivers?${new URLSearchParams(params)}`),
  byePlanner: (params = {}) => request(`/api/season/bye-planner?${new URLSearchParams(params)}`),
  liveDraft: (draftId, format = "ppr") => request(`/api/draft/live/${draftId}?format=${format}`),

  draftGrade: (draftId) => request(`/api/draft/${draftId}/grade`),

  draftHistory: () => request(`/api/draft/history`),

  draftHistoryDetail: (draftId) => request(`/api/draft/history/${draftId}`),

  deleteDraftHistory: (draftId) =>
    request(`/api/draft/history/${draftId}`, { method: "DELETE" }),

  startDraft: (body) =>
    request(`/api/draft/start`, { method: "POST", body: JSON.stringify(body) }),

  getDraft: (draftId) => request(`/api/draft/${draftId}`),

  availableInDraft: (draftId, params = {}) =>
    request(`/api/draft/${draftId}/available?${new URLSearchParams(params)}`),

  makeDraftPick: (draftId, playerId) =>
    request(`/api/draft/${draftId}/pick`, {
      method: "POST",
      body: JSON.stringify({ player_id: playerId }),
    }),

  analyzeRoster: (body) =>
    request(`/api/roster/analyze`, { method: "POST", body: JSON.stringify(body) }),

  analyzeSleeperRoster: (params = {}) =>
    request(`/api/roster/sleeper?${new URLSearchParams(params)}`),

  analyzeTrade: (body) =>
    request(`/api/trade/analyze`, { method: "POST", body: JSON.stringify(body) }),
};
