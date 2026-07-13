"""Player-name normalization and team-defense matching, shared by the
rankings import parser and the live ADP client."""
from __future__ import annotations

import re

_NAME_SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "v"}

# City/nickname forms -> Sleeper team-defense player id (the team abbr).
TEAM_DEFENSES = {
    "cardinals": "ARI", "arizona": "ARI",
    "falcons": "ATL", "atlanta": "ATL",
    "ravens": "BAL", "baltimore": "BAL",
    "bills": "BUF", "buffalo": "BUF",
    "panthers": "CAR", "carolina": "CAR",
    "bears": "CHI", "chicago": "CHI",
    "bengals": "CIN", "cincinnati": "CIN",
    "browns": "CLE", "cleveland": "CLE",
    "cowboys": "DAL", "dallas": "DAL",
    "broncos": "DEN", "denver": "DEN",
    "lions": "DET", "detroit": "DET",
    "packers": "GB", "green bay": "GB",
    "texans": "HOU", "houston": "HOU",
    "colts": "IND", "indianapolis": "IND",
    "jaguars": "JAX", "jacksonville": "JAX",
    "chiefs": "KC", "kansas city": "KC",
    "raiders": "LV", "las vegas": "LV",
    "chargers": "LAC",
    "rams": "LAR",
    "dolphins": "MIA", "miami": "MIA",
    "vikings": "MIN", "minnesota": "MIN",
    "patriots": "NE", "new england": "NE",
    "saints": "NO", "new orleans": "NO",
    "giants": "NYG",
    "jets": "NYJ",
    "eagles": "PHI", "philadelphia": "PHI",
    "steelers": "PIT", "pittsburgh": "PIT",
    "49ers": "SF", "niners": "SF", "san francisco": "SF",
    "seahawks": "SEA", "seattle": "SEA",
    "buccaneers": "TB", "tampa bay": "TB", "tampa": "TB",
    "titans": "TEN", "tennessee": "TEN",
    "commanders": "WAS", "washington": "WAS",
}


# Well-known nickname forms -> the name Sleeper's directory uses.
_ALIASES = {
    "hollywoodbrown": "marquisebrown",
    "tankdell": "nathanieldell",
}


def normalize_name(name: str) -> str:
    name = re.sub(r"[^a-z\s]", "", name.lower())
    tokens = [t for t in name.split() if t not in _NAME_SUFFIXES]
    joined = "".join(tokens)
    return _ALIASES.get(joined, joined)


def match_defense(raw_name: str, pos_hint: str | None = None) -> str | None:
    """Only matches when the row explicitly signals a team defense (DST/DEF
    keyword or position column) — otherwise 'Justin Houston' would match HOU."""
    lowered = raw_name.lower()
    explicit = pos_hint in ("DEF", "DST", "D/ST") or any(
        k in lowered for k in ("dst", "d/st", "defense")
    )
    if not explicit:
        return None
    for key, abbr in TEAM_DEFENSES.items():
        if key in lowered:
            return abbr
    return None
