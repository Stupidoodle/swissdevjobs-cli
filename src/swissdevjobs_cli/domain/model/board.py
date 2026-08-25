"""A job board: one country-specific instance of a platform."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Board:
    """One board instance.

    ``platform`` names the backend family (e.g. "devitjobs" — the shared
    engine behind swissdevjobs.ch and its sister sites); ``country`` is the
    lowercase ISO 3166-1 alpha-2 code boards are selected by.
    """

    platform: str
    country: str
    base_url: str
    name: str
    currency: str
    source: str  # value stored in the applications/jobs `source` column
