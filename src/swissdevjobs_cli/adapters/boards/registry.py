"""Every known board, keyed by its unique source id.

Selectors (CLI flags, ``SDJ_COUNTRIES``, MCP params) accept either a source
id ("jobsch") or a country code ("ch" — expands to every board in that
country), so the day a country gains a second board nothing user-facing
breaks. The devitjobs six share one backend (verified live: identical
/api/jobsLight, /api/job/{id}, and /api/jobApply behavior); `us` covers the
US and Canada — devitjobs.us 301-redirects to devitjobs.com, which lists
both. jobs.ch and jobup.ch share the JobCloud backend: all-industries,
query-driven, no native apply.
"""

from __future__ import annotations

from swissdevjobs_cli.domain.model.board import Board

BOARDS: dict[str, Board] = {
    "swissdevjobs": Board(
        platform="devitjobs",
        country="ch",
        base_url="https://swissdevjobs.ch",
        name="SwissDevJobs",
        currency="CHF",
        source="swissdevjobs",
    ),
    "germantechjobs": Board(
        platform="devitjobs",
        country="de",
        base_url="https://germantechjobs.de",
        name="GermanTechJobs",
        currency="EUR",
        source="germantechjobs",
    ),
    "devitjobs-uk": Board(
        platform="devitjobs",
        country="uk",
        base_url="https://devitjobs.uk",
        name="DevITjobs UK",
        currency="GBP",
        source="devitjobs-uk",
    ),
    "devitjobs-us": Board(
        platform="devitjobs",
        country="us",
        base_url="https://devitjobs.com",
        name="DevITjobs US/CA",
        currency="USD",
        source="devitjobs-us",
    ),
    "devitjobs-nl": Board(
        platform="devitjobs",
        country="nl",
        base_url="https://devitjobs.nl",
        name="DevITjobs NL",
        currency="EUR",
        source="devitjobs-nl",
    ),
    "devitjobs-fr": Board(
        platform="devitjobs",
        country="fr",
        base_url="https://devitjobs.fr",
        name="DevITjobs FR",
        currency="EUR",
        source="devitjobs-fr",
    ),
    "jobsch": Board(
        platform="jobcloud",
        country="ch",
        base_url="https://www.jobs.ch",
        name="jobs.ch",
        currency="CHF",
        source="jobsch",
        search_driven=True,
        native_apply=False,
    ),
    "jobup": Board(
        platform="jobcloud",
        country="ch",
        base_url="https://www.jobup.ch",
        name="jobup.ch",
        currency="CHF",
        source="jobup",
        search_driven=True,
        native_apply=False,
    ),
}

SOURCE_TO_BOARD: dict[str, Board] = dict(BOARDS)

# The board every unknown cached `source` value falls back to (rows written
# by a version that knew a since-removed board must still render).
FALLBACK_SOURCE = "swissdevjobs"


def known_selectors() -> list[str]:
    """Every token a user may select boards by: country codes and source ids."""
    countries = {b.country for b in BOARDS.values()}
    return sorted(countries | set(BOARDS))


def resolve_selectors(tokens: list[str]) -> list[str]:
    """Selector tokens → source ids, in registry order, deduplicated.

    A token matches a board by source id or by country code; "all" (or an
    empty/unknown-only list) selects every board. Unknown tokens are ignored
    rather than fatal — a typo in a .env file must not brick every command.
    """
    cleaned = [t.strip().lower() for t in tokens if t.strip()]
    if not cleaned or "all" in cleaned:
        return list(BOARDS)
    picked = [
        source
        for source, board in BOARDS.items()
        if source in cleaned or board.country in cleaned
    ]
    return picked or list(BOARDS)
