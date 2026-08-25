"""Minimal `.env` loader (stdlib only).

Files are read in order and each one fills in keys that are still unset.
The real process environment always wins, so `SDJ_NAME=x sdj …` overrides
anything on disk, and no `.env` can silently shadow an explicit export.

Search order:
  1. $SDJ_ENV_FILE            explicit override
  2. ./.env                   project-local, walking up to the filesystem root
  3. $SDJ_CONFIG_DIR/.env     defaults to ~/.config/swissdevjobs-cli/.env
"""

from __future__ import annotations

import os
from pathlib import Path

LOADED: list[str] = []  # paths actually read, in load order — surfaced by `sdj config`

TEMPLATE = """\
# swissdevjobs-cli configuration.
# Applicant identity used by `sdj direct-apply`.
SDJ_NAME="Your Name"
SDJ_EMAIL="you@example.com"

# Optional: default CV, so you can omit --cv
# SDJ_CV=/absolute/path/to/cv.pdf

# Optional: override where the cache database and cookie jar live
# SDJ_CACHE_DIR=~/.cache/swissdevjobs-cli
# SDJ_CONFIG_DIR=~/.config/swissdevjobs-cli
"""


def config_dir() -> Path:
    return Path(
        os.environ.get("SDJ_CONFIG_DIR") or Path.home() / ".config" / "swissdevjobs-cli"
    ).expanduser()


def _unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        inner = value[1:-1]
        # Only double quotes process escapes, matching POSIX shell behaviour.
        return (
            inner.replace("\\n", "\n").replace("\\t", "\t")
            if value[0] == '"'
            else inner
        )
    # Unquoted: an unescaped ` #` starts a trailing comment.
    head, sep, _ = value.partition(" #")
    return (head if sep else value).strip()


def parse(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].lstrip()
        key, sep, value = line.partition("=")
        key = key.strip()
        if not sep or not key or not key.replace("_", "").isalnum():
            continue
        out[key] = _unquote(value)
    return out


def _candidates() -> list[Path]:
    paths: list[Path] = []
    explicit = os.environ.get("SDJ_ENV_FILE")
    if explicit:
        paths.append(Path(explicit).expanduser())

    # Walk up from the working directory so a repo-root .env applies in subdirs.
    try:
        here = Path.cwd().resolve()
        for d in (here, *here.parents):
            paths.append(d / ".env")
    except OSError:
        pass

    paths.append(config_dir() / ".env")
    return paths


def load() -> list[str]:
    """Populate os.environ from the first-found values. Existing vars are kept."""
    seen: set[Path] = set()
    for path in _candidates():
        if path in seen:
            continue
        seen.add(path)
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        applied = False
        for key, value in parse(text).items():
            if key not in os.environ:
                os.environ[key] = value
                applied = True
        if applied or text.strip():
            LOADED.append(str(path))
    return LOADED


def write_template(path: Path | None = None) -> Path:
    """Write a starter .env, refusing to clobber an existing one."""
    target = path or (config_dir() / ".env")
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        raise FileExistsError(target)
    target.write_text(TEMPLATE, encoding="utf-8")
    target.chmod(0o600)  # it holds an email address; keep it owner-only
    return target
