"""A job board: one country-specific instance of a platform."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Board:
    """One board instance.

    ``platform`` names the backend family (e.g. "devitjobs" — the shared
    engine behind swissdevjobs.ch and its sister sites); ``country`` is the
    lowercase ISO 3166-1 alpha-2 code. ``source`` is the unique board key —
    the registry, the runtime, and the `source` column all use it, and one
    country may host several boards.

    ``search_driven`` marks boards whose inventory is too large to mirror:
    they answer server-side queries instead of serving a full feed, so the
    local cache only ever holds what past searches surfaced.
    ``native_apply`` is False for boards without their own apply endpoint —
    applying means driving the posting's external ATS.
    ``scope`` says what the inventory covers ("it", or "all-industries" for
    general boards where a category filter narrows the search);
    ``salary_published`` is False where the wire carries no salary data.
    """

    platform: str
    country: str
    base_url: str
    name: str
    currency: str
    source: str  # value stored in the applications/jobs `source` column
    search_driven: bool = False
    native_apply: bool = True
    scope: str = "it"
    salary_published: bool = True
