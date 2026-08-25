"""Filesystem locations, resolved once at import.

Imported only by the adapters that need them (persistence, http, bootstrap) —
never by the package `__init__`, so `envfile.load()` has run before these
resolve and a `.env`-provided SDJ_CACHE_DIR / SDJ_CONFIG_DIR is honored.
"""

from __future__ import annotations

import os
from pathlib import Path

CACHE_DIR = Path(
    os.environ.get("SDJ_CACHE_DIR", Path.home() / ".cache" / "swissdevjobs-cli")
)
CONFIG_DIR = Path(
    os.environ.get("SDJ_CONFIG_DIR", Path.home() / ".config" / "swissdevjobs-cli")
)
COOKIE_FILE = CONFIG_DIR / "cookies.txt"
DB_PATH = CACHE_DIR / "swissdevjobs.db"

CACHE_DIR.mkdir(parents=True, exist_ok=True)
CONFIG_DIR.mkdir(parents=True, exist_ok=True)
