import { api } from "../api.js";
import { escapeHtml } from "../util.js";
import { getDeviceId } from "../identity.js";

export async function renderImport(container) {
  let sets = [];
  let leagues = [];
  try { sets = (await api.listRankingSets()).sets; } catch (_) { /* ignore */ }
  try { leagues = (await api.listLeagues()).leagues; } catch (_) { /* ignore */ }
  const imported = sets.filter((s) => s.source === "imported");

  container.innerHTML = `
    <h1>Import</h1>
    <p class="subtitle">
      Bring in outside data: expert rankings files (CSV / Excel / PDF) become selectable draft boards,
      and imported leagues (ESPN or Sleeper) power team-aware trade analysis.
    </p>

    <div class="grid-2" style="margin-bottom:18px;">
      <div class="card" style="margin-bottom:0;">
        <h2>Import a League</h2>
        <div class="controls" style="flex-direction:column;align-items:stretch;">
          <label>Platform
            <select id="lg-platform">
              <option value="espn">ESPN</option>
              <option value="sleeper">Sleeper</option>
            </select>
          </label>
          <label>League ID
            <input type="text" id="lg-id" placeholder="e.g. 12345678">
          </label>
          <div id="espn-cookies">
            <label>espn_s2 cookie (private leagues only)
              <input type="text" id="lg-s2" placeholder="optional">
            </label>
            <label style="margin-top:8px;">SWID cookie (private leagues only)
              <input type="text" id="lg-swid" placeholder="optional, looks like {XXXX-…}">
            </label>
          </div>
          <button id="lg-import">Import League</button>
        </div>
        <p class="tag-note">
          ESPN: the league ID is in your league URL (leagueId=…). Public leagues import directly;
          private ones need the espn_s2 + SWID cookies from your browser while logged in to ESPN.
          Sleeper: sleeper.com/leagues/&lt;league_id&gt;.
        </p>
        <div id="lg-result" style="margin-top:10px;"></div>
      </div>

      <div class="card" style="margin-bottom:0;">
        <h2>Your Imported Leagues</h2>
        <div id="lg-list">
          ${leagues.length ? leagues.map((l) => `
            <div class="player-search-row">
              <div>
                <strong>${escapeHtml(l.name || l.league_id)}</strong>
                <span class="tag-note">${l.platform.toUpperCase()} · ${l.team_count} teams</span>
              </div>
              <button class="danger" data-del-league="${l.key}">Delete</button>
            </div>
          `).join("") : `<div class="empty-state">No leagues imported yet.</div>`}
        </div>
        <p class="tag-note">Imported leagues appear in the Trade Analyzer, where you can pick any two teams and analyze trades with full roster context.</p>
      </div>
    </div>

    <div class="grid-2">
      <div class="card">
        <h2>ECR Reference Board</h2>
        <p class="tag-note" style="margin:0 0 10px;">
          The consensus board the whole app measures value against — draft-room value picks, slip analysis,
          and the default rankings comparison. Refresh it anytime with a current FantasyPros export.
        </p>
        <p class="tag-note" style="margin:0 0 10px;">This board is shared by everyone on the site — updating it replaces the reference for all users.</p>
        <div class="controls" style="flex-direction:column;align-items:stretch;">
          <label>FantasyPros rankings export (.csv / .xlsx)
            <input type="file" id="ecr-file" accept=".csv,.xlsx,.xlsm">
          </label>
          <button id="ecr-upload">Update ECR</button>
        </div>
        <div id="ecr-result" style="margin-top:10px;"></div>

        <h2 style="margin-top:22px;">Upload a Rankings File</h2>
        <div class="controls" style="flex-direction:column;align-items:stretch;">
          <label>Ranking set name
            <input type="text" id="imp-name" placeholder="e.g. FantasyPros Top 200 (PPR)">
          </label>
          <label>File (.csv, .xlsx, .pdf)
            <input type="file" id="imp-file" accept=".csv,.tsv,.txt,.xlsx,.xlsm,.pdf">
          </label>
          <button id="imp-upload">Import Rankings</button>
        </div>
        <p class="tag-note">
          CSV/Excel: needs a player-name column (header like "Player" or "Name"); rank, position, and team
          columns are used when present, otherwise row order is the rank.
          PDF: works with "1. Player Name POS TEAM" style ranked lists.
        </p>
        <div id="imp-result" style="margin-top:12px;"></div>
      </div>

      <div class="card">
        <h2>Your Imported Sets</h2>
        <div id="imp-sets">
          ${imported.length ? imported.map((s) => `
            <div class="player-search-row">
              <div>
                <strong>${escapeHtml(s.name)}</strong>
                <span class="tag-note">${s.player_count} players</span>
              </div>
              <button class="danger" data-del="${s.id}">Delete</button>
            </div>
          `).join("") : `<div class="empty-state">No imported rankings yet.</div>`}
        </div>
      </div>
    </div>
  `;

  container.querySelector("#ecr-upload").addEventListener("click", async () => {
    const fileInput = container.querySelector("#ecr-file");
    const resultEl = container.querySelector("#ecr-result");
    const file = fileInput.files[0];
    if (!file) { resultEl.innerHTML = `<div class="error-state">Choose a file first.</div>`; return; }
    const btn = container.querySelector("#ecr-upload");
    btn.disabled = true;
    btn.textContent = "Updating…";
    try {
      const form = new FormData();
      form.append("file", file);
      const res = await fetch("/api/rankings/ecr", {
        method: "POST",
        headers: { "X-FFL-UID": getDeviceId() },
        body: form,
      });
      if (!res.ok) throw new Error((await res.json()).detail || res.statusText);
      const data = await res.json();
      resultEl.innerHTML = `
        <div class="verdict-banner verdict-fair" style="margin-bottom:0;">
          ECR updated — ${data.matched_count} players matched${data.unmatched_count ? `, ${data.unmatched_count} unmatched (mostly deep-roster names)` : ""}.
        </div>`;
    } catch (err) {
      resultEl.innerHTML = `<div class="error-state">${escapeHtml(err.message)}</div>`;
    } finally {
      btn.disabled = false;
      btn.textContent = "Update ECR";
    }
  });

  const platformSel = container.querySelector("#lg-platform");
  const cookieBox = container.querySelector("#espn-cookies");
  platformSel.addEventListener("change", () => {
    cookieBox.style.display = platformSel.value === "espn" ? "" : "none";
  });

  container.querySelector("#lg-import").addEventListener("click", async () => {
    const btn = container.querySelector("#lg-import");
    const resultEl = container.querySelector("#lg-result");
    const leagueId = container.querySelector("#lg-id").value.trim();
    if (!leagueId) {
      resultEl.innerHTML = `<div class="error-state">Enter a league ID.</div>`;
      return;
    }
    btn.disabled = true;
    btn.textContent = "Importing…";
    try {
      const body = { platform: platformSel.value, league_id: leagueId };
      if (platformSel.value === "espn") {
        body.espn_s2 = container.querySelector("#lg-s2").value.trim();
        body.swid = container.querySelector("#lg-swid").value.trim();
      }
      const league = await api.importLeague(body);
      const unmatchedTotal = league.teams.reduce((n, t) => n + (t.unmatched?.length || 0), 0);
      resultEl.innerHTML = `
        <div class="verdict-banner verdict-fair" style="margin-bottom:0;">
          Imported "${escapeHtml(league.name)}" — ${league.teams.length} teams${unmatchedTotal ? `, ${unmatchedTotal} unmatched player name(s)` : ""}.
          <div class="tag-note" style="font-weight:400;margin-top:4px;">Open the <a href="#/trade">Trade Analyzer</a> to analyze trades between its teams.</div>
        </div>
      `;
      const listEl = container.querySelector("#lg-list");
      if (listEl.querySelector(".empty-state")) listEl.innerHTML = "";
      const row = document.createElement("div");
      row.className = "player-search-row";
      row.innerHTML = `<div><strong>${escapeHtml(league.name)}</strong> <span class="tag-note">${league.platform.toUpperCase()} · ${league.teams.length} teams</span></div>`;
      listEl.appendChild(row);
      btn.disabled = false;
      btn.textContent = "Import League";
    } catch (err) {
      resultEl.innerHTML = `<div class="error-state">${escapeHtml(err.message)}</div>`;
      btn.disabled = false;
      btn.textContent = "Import League";
    }
  });

  container.querySelectorAll("button[data-del-league]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      if (!confirm("Delete this imported league?")) return;
      await api.deleteLeague(btn.dataset.delLeague);
      await renderImport(container);
    });
  });

  container.querySelectorAll("button[data-del]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      if (!confirm("Delete this ranking set?")) return;
      await api.deleteRankingSet(btn.dataset.del);
      await renderImport(container);
    });
  });

  container.querySelector("#imp-upload").addEventListener("click", async () => {
    const fileInput = container.querySelector("#imp-file");
    const resultEl = container.querySelector("#imp-result");
    const file = fileInput.files[0];
    if (!file) {
      resultEl.innerHTML = `<div class="error-state">Choose a file first.</div>`;
      return;
    }
    const btn = container.querySelector("#imp-upload");
    btn.disabled = true;
    btn.textContent = "Importing…";
    try {
      const res = await api.importRankings(file, container.querySelector("#imp-name").value.trim());
      const unmatchedList = res.unmatched.length
        ? `<details style="margin-top:8px;"><summary class="tag-note" style="cursor:pointer;">Show unmatched rows</summary>
             <ul class="rec-list">${res.unmatched.map((u) => `<li>#${u.rank} ${escapeHtml(u.name)}</li>`).join("")}</ul>
           </details>`
        : "";
      resultEl.innerHTML = `
        <div class="verdict-banner verdict-fair" style="margin-bottom:0;">
          Imported "${escapeHtml(res.name)}" — ${res.matched_count} players matched${res.unmatched_count ? `, ${res.unmatched_count} unmatched` : ""}.
          <div class="tag-note" style="font-weight:400;margin-top:4px;">
            Now selectable in <a href="#/rankings">Rankings</a> and new <a href="#/draft">Mock Drafts</a>.
          </div>
          ${unmatchedList}
        </div>
      `;
      const setsEl = container.querySelector("#imp-sets");
      const row = document.createElement("div");
      row.className = "player-search-row";
      row.innerHTML = `<div><strong>${escapeHtml(res.name)}</strong> <span class="tag-note">${res.matched_count} players</span></div>`;
      if (setsEl.querySelector(".empty-state")) setsEl.innerHTML = "";
      setsEl.appendChild(row);
    } catch (err) {
      resultEl.innerHTML = `<div class="error-state">${escapeHtml(err.message)}</div>`;
    } finally {
      btn.disabled = false;
      btn.textContent = "Import Rankings";
    }
  });
}
