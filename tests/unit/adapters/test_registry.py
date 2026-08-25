"""The board registry is the multi-board contract; keep it well-formed."""

from __future__ import annotations

from swissdevjobs_cli.adapters.boards.registry import (
    BOARDS,
    FALLBACK_SOURCE,
    SOURCE_TO_BOARD,
    known_selectors,
    resolve_selectors,
)


def test_registry_covers_the_eight_boards():
    assert set(BOARDS) == {
        "swissdevjobs",
        "germantechjobs",
        "devitjobs-uk",
        "devitjobs-us",
        "devitjobs-nl",
        "devitjobs-fr",
        "jobsch",
        "jobup",
    }
    assert FALLBACK_SOURCE in BOARDS


def test_every_board_is_fully_configured():
    for source, board in BOARDS.items():
        assert board.source == source
        assert board.platform in {"devitjobs", "jobcloud"}
        assert board.base_url.startswith("https://")
        assert not board.base_url.endswith("/")
        assert board.name
        assert board.currency in {"CHF", "EUR", "GBP", "USD"}
        assert len(board.country) == 2


def test_sources_are_unique_and_reverse_mapped():
    sources = [b.source for b in BOARDS.values()]
    assert len(sources) == len(set(sources))
    for board in BOARDS.values():
        assert SOURCE_TO_BOARD[board.source] is board


def test_ch_source_matches_the_v1_database_value():
    """Pre-multi-board rows were written with source='swissdevjobs'."""
    assert BOARDS["swissdevjobs"].country == "ch"


def test_jobcloud_boards_are_search_driven_without_native_apply():
    for source in ("jobsch", "jobup"):
        assert BOARDS[source].search_driven
        assert not BOARDS[source].native_apply
    assert not BOARDS["swissdevjobs"].search_driven
    assert BOARDS["swissdevjobs"].native_apply


def test_a_country_code_selects_every_board_in_that_country():
    assert resolve_selectors(["ch"]) == ["swissdevjobs", "jobsch", "jobup"]


def test_a_source_id_selects_exactly_one_board():
    assert resolve_selectors(["jobsch"]) == ["jobsch"]


def test_all_and_unknown_only_fall_back_to_every_board():
    assert resolve_selectors(["all"]) == list(BOARDS)
    assert resolve_selectors([]) == list(BOARDS)
    assert resolve_selectors(["xx", "  "]) == list(BOARDS)


def test_mixed_selectors_deduplicate_in_registry_order():
    assert resolve_selectors(["jobsch", "ch", "de"]) == [
        "swissdevjobs",
        "germantechjobs",
        "jobsch",
        "jobup",
    ]


def test_known_selectors_cover_countries_and_sources():
    known = known_selectors()
    assert "ch" in known
    assert "jobsch" in known
    assert "swissdevjobs" in known
