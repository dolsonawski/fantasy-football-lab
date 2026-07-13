# Fantasy Football Lab

A fantasy football app with mock drafts, roster/team analysis, trade analysis, and rankings
comparisons — built as a single Python (FastAPI) app with a plain HTML/CSS/JS frontend, so
there's no Node/npm build step.

## Data source

Player, team, and real season stat data comes from [Sleeper's public API](https://docs.sleeper.com/)
(free, no API key required). There's no free API for proprietary ESPN/Yahoo/FantasyPros expert
rankings, so instead of faking that, this app:

- Scores every player three ways (Standard / Half-PPR / PPR) from their real season stat totals.
- Compares that computed rank against Sleeper's own platform rank (`search_rank`) to flag
  players the market under- or over-valued relative to their production.
- Uses value-based-drafting (VBD) math for roster grades, draft AI, and trade fairness.

## Setup

Requires Python 3.11+.

```
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
```

## Run

```
.venv\Scripts\python -m uvicorn app.main:app --reload --port 8000
```

Then open http://127.0.0.1:8000

## Features

- **Rankings Comparison** (`/#/rankings`) — sortable table ordered by the active draft board
  (computed VBD board per format, or any imported set), with value deltas vs. real production
  and Sleeper's market rank.
- **Mock Draft** (`/#/draft`) — 8–16 team snake draft vs. need-aware AI opponents drafting off
  the chosen ranking board. Live suggestions each pick (best available / values fallen past
  their rank / best fit for your roster). Completing a draft produces a report card: overall
  grade, league-wide starter-value comparison, positional strengths/weaknesses, and specific
  picks where a clearly better board option was passed up.
- **Roster Analysis** (`/#/roster`) — grade a manual roster or one pulled live from a real
  Sleeper league (`league_id` + `roster_id`).
- **Trade Analyzer** (`/#/trade`) — value comparison plus optional before/after lineup grade
  impact when you supply each team's full roster.
- **Import** (`/#/import`) — two importers:
  - Rankings files (CSV / Excel / PDF) become selectable draft boards.
  - Leagues from ESPN (public league id; private with espn_s2 + SWID cookies) or Sleeper —
    all teams and rosters, which then power team-aware trade analysis.

## Ranking sources

FFC ADP (live mock-draft ADP), ESPN Rankings + ESPN ADP (from ESPN's public API),
Sleeper ADP, Projected Points (Sleeper 2026 projections — also the value basis for all
grades/trades), Last-Season Production, and anything you import. The rankings page compares
any two sources; the default view is ESPN Rankings vs Projected Points — i.e., the most
mis-ranked players on ESPN.

## Project layout

```
app/
  main.py              FastAPI app + static file mount
  routers/              HTTP endpoints
  services/
    sleeper_client.py   Sleeper API client with disk caching
    scoring.py           Standard/Half-PPR/PPR scoring formulas
    dataset.py            Builds the scored/ranked player dataset
    rankings_store.py      Draft-ranking sets (computed VBD boards + imported)
    rankings_import.py     CSV/Excel/PDF rankings parser + name matching
    roster_rules.py        Shared starter-slot rules
    draft_engine.py        Mock draft simulator, suggestions, draft grading
    roster_analyzer.py     Roster grading
    trade_analyzer.py      Trade analysis
  static/                 Vanilla JS frontend (hash-routed, no build step)
  cache/                  Cached Sleeper API responses (gitignored)
```
