"""Central data-directory resolution.

All persisted data (accounts, sessions, per-user drafts/leagues, imported
rankings, ECR, and regenerable caches) lives under one root so a hosted
instance can point everything at a single persistent disk via FFL_DATA_DIR.
Defaults to app/data for local dev.
"""
from __future__ import annotations

import os
from pathlib import Path

DATA_DIR = Path(os.environ.get("FFL_DATA_DIR") or (Path(__file__).resolve().parent / "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)

CACHE_DIR = DATA_DIR / "cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)
