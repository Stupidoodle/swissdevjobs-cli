"""Search-driven boards: browse always asks the server, resolve never does."""

from __future__ import annotations

from conftest import job
from fakes.fake_board_port import FakeBoard
from swissdevjobs_cli.adapters.boards.registry import BOARDS
from swissdevjobs_cli.service_layer import apply as apply_service
from swissdevjobs_cli.service_layer import search


def jobcloud_fake(feed=None):
    return FakeBoard(feed=feed if feed is not None else [job()], board=BOARDS["jobsch"])


def test_browse_always_fetches_a_search_driven_board(fresh_uow):
    board = jobcloud_fake()
    search.list_jobs(fresh_uow, [board])
    search.list_jobs(fresh_uow, [board])
    assert len(board.queries) == 2, "a warm cache must not mask a live search"


def test_browse_serves_a_feed_board_from_cache(fresh_uow):
    board = FakeBoard(feed=[job()])
    search.list_jobs(fresh_uow, [board])
    search.list_jobs(fresh_uow, [board])
    assert len(board.queries) == 1


def test_the_query_and_category_reach_the_board(fresh_uow):
    board = jobcloud_fake()
    search.list_jobs(fresh_uow, [board], query="python", category="it")
    assert board.queries == [("python", "it")]


def test_resolve_serves_the_search_driven_cache_without_fetching(fresh_uow):
    board = jobcloud_fake()
    listed = search.list_jobs(fresh_uow, [board], query="python")
    board.queries.clear()
    resolved = search.resolve_jobs(fresh_uow, [board])
    assert board.queries == [], "resolve must never refetch a search-driven board"
    assert [str(j.id) for j in resolved] == [str(j.id) for j in listed]


def test_resolve_finds_nothing_on_a_cold_search_driven_board(fresh_uow):
    board = jobcloud_fake()
    assert search.resolve_jobs(fresh_uow, [board]) == []
    assert board.queries == []


def test_resolve_still_fetches_a_cold_feed_board(fresh_uow):
    board = FakeBoard(feed=[job()])
    resolved = search.resolve_jobs(fresh_uow, [board])
    assert len(resolved) == 1
    assert board.queries == [(None, None)]


def test_query_for_skips_the_client_side_filter_on_server_matched_rows(fresh_uow):
    board = jobcloud_fake()
    (row,) = search.list_jobs(fresh_uow, [board], query="described only")
    assert search.query_for(row, "described only") is None
    feed_row = search.list_jobs(fresh_uow, [FakeBoard(feed=[job()])])[0]
    assert search.query_for(feed_row, "python") == "python"


def test_a_board_without_native_apply_is_refused(fresh_uow):
    from test_jobcloud_acl import detail_doc

    from swissdevjobs_cli.adapters.boards.switzerland.jobcloud import acl

    detail = acl.detail_from_wire(detail_doc(), BOARDS["jobsch"])
    refusal = apply_service.undeliverable(detail)
    assert refusal["error"] == "no_native_apply"
    assert refusal["next_action"] == "use_chrome_mcp"
    assert refusal["apply_url"] == detail.redirect_url
    assert "jobs.ch" in refusal["message"]


def test_the_fallback_mode_for_jobcloud_postings_is_browser():
    from test_jobcloud_acl import detail_doc

    from swissdevjobs_cli.adapters.boards.switzerland.jobcloud import acl

    detail = acl.detail_from_wire(detail_doc(), BOARDS["jobsch"])
    assert apply_service.fallback_mode(detail) == "browser"
