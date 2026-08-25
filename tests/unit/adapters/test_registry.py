"""The board registry is the multi-board contract; keep it well-formed."""

from __future__ import annotations

from swissdevjobs_cli.adapters.boards.registry import (
    BOARDS,
    DEFAULT_COUNTRY,
    SOURCE_TO_BOARD,
)


def test_registry_covers_the_six_family_boards():
    assert set(BOARDS) == {"ch", "de", "uk", "us", "nl", "fr"}
    assert DEFAULT_COUNTRY in BOARDS


def test_every_board_is_fully_configured():
    for code, board in BOARDS.items():
        assert board.country == code
        assert board.platform == "devitjobs"
        assert board.base_url.startswith("https://")
        assert not board.base_url.endswith("/")
        assert board.name
        assert board.currency in {"CHF", "EUR", "GBP", "USD"}
        assert board.source


def test_sources_are_unique_and_reverse_mapped():
    sources = [b.source for b in BOARDS.values()]
    assert len(sources) == len(set(sources))
    for board in BOARDS.values():
        assert SOURCE_TO_BOARD[board.source] is board


def test_ch_source_matches_the_v1_database_value():
    """Pre-multi-board rows were written with source='swissdevjobs'."""
    assert BOARDS["ch"].source == "swissdevjobs"
