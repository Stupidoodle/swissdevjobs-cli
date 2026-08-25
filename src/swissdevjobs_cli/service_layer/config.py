"""Resolved configuration for `sdj config` and applicant identity resolution."""

from __future__ import annotations

import os
from typing import Any

from swissdevjobs_cli.domain.model.application import Applicant


def resolve_applicant(
    name: str | None,
    email: str | None,
    cv_path: str | None,
    *,
    labels: tuple[str, str, str],
) -> Applicant | list[str]:
    """Fill identity from the environment; return the missing labels if any.

    ``labels`` keeps each frontend's historic error labels intact — the CLI
    reports "--name/$SDJ_NAME", MCP reports "name/$SDJ_NAME" — while the
    resolution logic lives in one place.
    """
    name = name or os.environ.get("SDJ_NAME")
    email = email or os.environ.get("SDJ_EMAIL")
    cv_path = cv_path or os.environ.get("SDJ_CV") or ""
    missing = [
        label for label, value in zip(labels, (name, email, cv_path)) if not value
    ]
    if missing or not name or not email:
        return missing
    return Applicant(name=name, email=email, cv_path=cv_path)


def resolved_config(
    env_files_loaded: list[str],
    *,
    cache_dir: str,
    config_dir: str,
    cookie_file: str,
    db_path: str,
) -> dict[str, Any]:
    """Everything `sdj config` prints, as one JSON-ready mapping."""
    return {
        "name": os.environ.get("SDJ_NAME"),
        "email": os.environ.get("SDJ_EMAIL"),
        "cv": os.environ.get("SDJ_CV"),
        "cache_dir": cache_dir,
        "config_dir": config_dir,
        "cookie_file": cookie_file,
        "database": db_path,
        "env_files_loaded": env_files_loaded,
    }
