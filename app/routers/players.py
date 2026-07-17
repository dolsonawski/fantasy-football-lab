from __future__ import annotations

from fastapi import APIRouter, Query

from app.services import dataset, espn_client, rankings_store, roster_rules, schedule_client, sleeper_client

router = APIRouter(prefix="/api/players", tags=["players"])


@router.get("")
async def list_players(
    position: str | None = Query(default=None),
    search: str | None = Query(default=None),
    format: str = Query(default="ppr", pattern="^(standard|half_ppr|ppr)$"),
    limit: int = Query(default=300, le=1000),
):
    players = await dataset.build_dataset()

    if position:
        wanted = {p.strip().upper() for p in position.split(",")}
        players = [p for p in players if p["position"] in wanted]

    if search:
        needle = search.lower()
        players = [p for p in players if needle in p["name"].lower()]

    players = sorted(players, key=lambda p: roster_rules.player_value(p, format), reverse=True)
    return {"season": dataset.season_in_use(), "count": len(players), "players": players[:limit]}


# Boards to show side-by-side in a player's detail card (label -> set-id template).
_DETAIL_BOARDS = [
    ("ECR", "ecr"),
    ("ESPN", "espn_rank_{fmt}"),
    ("Sleeper", "sleeper_adp_{fmt}"),
    ("FFC ADP", "adp_{fmt}"),
    ("Projected", "proj_{fmt}"),
]


@router.get("/{player_id}/detail")
async def player_detail(player_id: str, format: str = Query(default="ppr", pattern="^(standard|half_ppr|ppr)$")):
    players = await dataset.build_dataset()
    rec = next((p for p in players if p["id"] == player_id), None)

    directory = await sleeper_client.fetch_players()
    info = directory.get(player_id) or {}
    name = (rec or {}).get("name") or info.get("full_name") or player_id
    espn_id = info.get("espn_id")

    ranks = []
    for label, tmpl in _DETAIL_BOARDS:
        set_id = tmpl.format(fmt=format)
        try:
            board = await rankings_store.get_ranks(set_id)
            ranks.append({"label": label, "rank": board.get(player_id)})
        except Exception:
            ranks.append({"label": label, "rank": None})

    # Season strength-of-schedule (1–5 stars) from the uploaded FantasyPros
    # ECR export, when it carries an SOS column.
    sos = None
    try:
        for e in (await rankings_store.get_set_entries("ecr")) or []:
            if e["player_id"] == player_id:
                sos = e.get("sos")
                break
    except Exception:
        pass

    # Playoff (fantasy weeks 15-17) strength of schedule for this player's
    # NFL team, 1-5 stars (5 = easiest). None when the ESPN schedule fetch
    # failed or the team isn't recognized — the frontend just omits the row.
    playoff_sos = None
    team = (rec or {}).get("team") or info.get("team")
    try:
        if team and team != "FA":
            playoff_sos = (await schedule_client.playoff_sos()).get(team)
    except Exception:
        playoff_sos = None

    try:
        news = await espn_client.player_news(name)
    except Exception:
        news = []

    # Sleeper add/drop momentum — a real "how the market regards him right
    # now" signal (X has no free API, so this is the sentiment proxy).
    trending = {"add": None, "drop": None}
    try:
        adds = await sleeper_client.fetch_trending("add", 24, 200)
        drops = await sleeper_client.fetch_trending("drop", 24, 200)
        for row in adds:
            if row.get("player_id") == player_id:
                trending["add"] = row.get("count")
                break
        for row in drops:
            if row.get("player_id") == player_id:
                trending["drop"] = row.get("count")
                break
    except Exception:
        pass

    from urllib.parse import quote_plus
    q = quote_plus(f"{name} NFL")
    social = [
        {"label": "X / Twitter", "url": f"https://x.com/search?q={quote_plus(name + ' NFL')}&f=live"},
        {"label": "Reddit r/fantasyfootball", "url": f"https://www.reddit.com/r/fantasyfootball/search/?q={q}&sort=new"},
    ]

    links = []
    if espn_id:
        links.append({"label": "ESPN profile", "url": f"https://www.espn.com/nfl/player/_/id/{espn_id}"})
    slug = name.lower().replace("'", "").replace(".", "").replace(" ", "-")
    if rec and rec["position"] not in ("DEF",):
        links.append({"label": "FantasyPros", "url": f"https://www.fantasypros.com/nfl/players/{slug}.php"})
    links.append({"label": "Google News", "url": f"https://news.google.com/search?q={q}%20fantasy"})

    return {
        "id": player_id,
        "name": name,
        "position": (rec or {}).get("position") or info.get("position"),
        "team": (rec or {}).get("team") or info.get("team") or "FA",
        "injury_status": info.get("injury_status"),
        "age": info.get("age"),
        "years_exp": info.get("years_exp"),
        "rookie": (rec or {}).get("rookie"),
        "bye": (rec or {}).get("bye"),
        "sos": sos,
        "playoff_sos": playoff_sos,
        "format": format,
        "proj_points": (rec or {}).get("proj_points"),
        "points": (rec or {}).get("points"),
        "proj_pos_rank": (rec or {}).get("proj_rank_position", {}).get(format) if rec else None,
        "perf_rank": (rec or {}).get("rank_overall", {}).get(format) if rec else None,
        "ranks": ranks,
        "news": news,
        "trending": trending,
        "social": social,
        "links": links,
    }
