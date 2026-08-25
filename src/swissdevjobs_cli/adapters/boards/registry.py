"""Every known board, selectable by lowercase ISO country code."""

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
}

DEFAULT_COUNTRY = "ch"
