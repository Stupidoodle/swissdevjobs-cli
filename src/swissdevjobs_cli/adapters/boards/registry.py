"""Every known board, keyed by its unique source id.

Selectors (CLI flags, ``SDJ_COUNTRIES``, MCP params) accept either a source
id ("jobsch") or a country code ("ch" — expands to every board in that
country), so the day a country gains a second board nothing user-facing
breaks. The devitjobs six share one backend (verified live: identical
/api/jobsLight, /api/job/{id}, and /api/jobApply behavior); `us` covers the
US and Canada — devitjobs.us 301-redirects to devitjobs.com, which lists
both. jobs.ch and jobup.ch share the JobCloud backend: all-industries,
query-driven, no native apply.

MyCareersFuture (Singapore, government portal) is search-driven like
JobCloud — its IT category alone carries ~9,000 active jobs, too large and
rate-limit-uncertain to mirror — but unlike JobCloud it publishes real
salary and skills data per row.
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
        filters_unavailable=("workload",),
    ),
    "germantechjobs": Board(
        platform="devitjobs",
        country="de",
        base_url="https://germantechjobs.de",
        name="GermanTechJobs",
        currency="EUR",
        source="germantechjobs",
        filters_unavailable=("workload",),
    ),
    "devitjobs-uk": Board(
        platform="devitjobs",
        country="uk",
        base_url="https://devitjobs.uk",
        name="DevITjobs UK",
        currency="GBP",
        source="devitjobs-uk",
        filters_unavailable=("workload",),
    ),
    "devitjobs-us": Board(
        platform="devitjobs",
        country="us",
        base_url="https://devitjobs.com",
        name="DevITjobs US/CA",
        currency="USD",
        source="devitjobs-us",
        filters_unavailable=("workload",),
    ),
    "devitjobs-nl": Board(
        platform="devitjobs",
        country="nl",
        base_url="https://devitjobs.nl",
        name="DevITjobs NL",
        currency="EUR",
        source="devitjobs-nl",
        filters_unavailable=("workload",),
    ),
    "devitjobs-fr": Board(
        platform="devitjobs",
        country="fr",
        base_url="https://devitjobs.fr",
        name="DevITjobs FR",
        currency="EUR",
        source="devitjobs-fr",
        filters_unavailable=("workload",),
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
        scope="all-industries",
        salary_published=False,
        filters_unavailable=("salary", "remote", "visa", "level", "tech"),
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
        scope="all-industries",
        salary_published=False,
        filters_unavailable=("salary", "remote", "visa", "level", "tech"),
    ),
    "mycareersfuture": Board(
        platform="mycareersfuture",
        country="sg",
        base_url="https://www.mycareersfuture.gov.sg",
        name="MyCareersFuture",
        currency="SGD",
        source="mycareersfuture",
        search_driven=True,
        native_apply=False,
        scope="it",
        salary_published=True,
        filters_unavailable=("visa", "level", "workload"),
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


def categories_for(source: str) -> list[str]:
    """The category aliases one board understands (empty for all-IT feeds)."""
    from swissdevjobs_cli.adapters.boards.switzerland.jobcloud.client import (
        CATEGORY_IDS,
    )

    return sorted(CATEGORY_IDS.get(source, {}))


def contracts_for(source: str) -> list[str]:
    """The contract-type aliases one board's platform can serve."""
    board = BOARDS.get(source)
    if board is None:
        return []
    if board.platform == "jobcloud":
        from swissdevjobs_cli.adapters.boards.switzerland.jobcloud.acl import (
            CONTRACT_TYPE_IDS,
        )

        return sorted(CONTRACT_TYPE_IDS)
    from swissdevjobs_cli.adapters.boards.worldwide.devitjobs.acl import (
        JOBTYPE_CONTRACTS,
    )

    return sorted({a for aliases in JOBTYPE_CONTRACTS.values() for a in aliases})


def known_contracts() -> list[str]:
    """Every contract alias any board understands — the shared schema enum."""
    return sorted({c for source in BOARDS for c in contracts_for(source)})


def known_categories() -> list[str]:
    """Every category alias any board understands — the shared schema enum.

    Derived, not hardcoded: the day a board adds a "finance" alias it must
    appear in the MCP schema, the CLI choices, and list_boards output
    without touching three files.
    """
    return sorted({c for source in BOARDS for c in categories_for(source)})


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
