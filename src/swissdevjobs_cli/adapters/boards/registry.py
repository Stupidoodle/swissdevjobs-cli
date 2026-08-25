"""Every known board, selectable by lowercase ISO country code.

All six run the same devitjobs backend (verified live: identical
/api/jobsLight, /api/job/{id}, and /api/jobApply behavior), so one client
class covers the whole platform. `us` covers the US and Canada —
devitjobs.us 301-redirects to devitjobs.com, which lists both.
"""

from __future__ import annotations

from swissdevjobs_cli.domain.model.board import Board

BOARDS: dict[str, Board] = {
    "ch": Board(
        platform="devitjobs",
        country="ch",
        base_url="https://swissdevjobs.ch",
        name="SwissDevJobs",
        currency="CHF",
        source="swissdevjobs",
    ),
    "de": Board(
        platform="devitjobs",
        country="de",
        base_url="https://germantechjobs.de",
        name="GermanTechJobs",
        currency="EUR",
        source="germantechjobs",
    ),
    "uk": Board(
        platform="devitjobs",
        country="uk",
        base_url="https://devitjobs.uk",
        name="DevITjobs UK",
        currency="GBP",
        source="devitjobs-uk",
    ),
    "us": Board(
        platform="devitjobs",
        country="us",
        base_url="https://devitjobs.com",
        name="DevITjobs US/CA",
        currency="USD",
        source="devitjobs-us",
    ),
    "nl": Board(
        platform="devitjobs",
        country="nl",
        base_url="https://devitjobs.nl",
        name="DevITjobs NL",
        currency="EUR",
        source="devitjobs-nl",
    ),
    "fr": Board(
        platform="devitjobs",
        country="fr",
        base_url="https://devitjobs.fr",
        name="DevITjobs FR",
        currency="EUR",
        source="devitjobs-fr",
    ),
}

SOURCE_TO_BOARD: dict[str, Board] = {b.source: b for b in BOARDS.values()}

DEFAULT_COUNTRY = "ch"
