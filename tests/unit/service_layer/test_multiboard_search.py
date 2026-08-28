"""Multi-board aggregation: independent caches, combined feeds."""

from __future__ import annotations

import pytest

from conftest import job
from fakes.fake_board_port import FakeBoard
from swissdevjobs_cli.adapters.boards.registry import BOARDS
from swissdevjobs_cli.service_layer import search


def test_the_feed_combines_every_requested_board(fresh_uow):
    ch = FakeBoard(feed=[job()], board=BOARDS["swissdevjobs"])
    de = FakeBoard(
        feed=[job(_id="68b0000057370f0152e4950e", jobUrl="de-role")],
        board=BOARDS["germantechjobs"],
    )
    jobs = search.list_jobs(fresh_uow, [ch, de])
    assert {j.board.country for j in jobs} == {"ch", "de"}
    assert len(jobs) == 2


def test_boards_cache_independently(fresh_uow):
    ch = FakeBoard(feed=[job()], board=BOARDS["swissdevjobs"])
    search.list_jobs(fresh_uow, [ch])

    # CH is now warm; a DE fetch must still hit the DE board, not the cache.
    de = FakeBoard(
        feed=[job(_id="68b0000057370f0152e4950e", jobUrl="de-role")],
        board=BOARDS["germantechjobs"],
    )
    jobs = search.list_jobs(fresh_uow, [ch, de])
    assert len(jobs) == 2

    # …and a warm cache serves both without touching either board again.
    ch.raises = de.raises = RuntimeError("no network expected")
    jobs = search.list_jobs(fresh_uow, [ch, de])
    assert len(jobs) == 2


def test_one_dead_board_does_not_abort_the_others(fresh_uow):
    """A board can vanish mid-release; the other eight still have to answer.

    jobs.ch retired its search endpoint while v0.9.1 was live and every
    keyword search across all nine boards died with it.
    """
    ch = FakeBoard(feed=[job()], board=BOARDS["swissdevjobs"])
    de = FakeBoard(
        feed=[job(_id="68b0000057370f0152e4950e", jobUrl="de-role")],
        board=BOARDS["germantechjobs"],
    )
    de.raises = RuntimeError("HTTP 410 for https://www.jobs.ch/api/v1/public/search")
    failures: dict[str, str] = {}
    jobs = search.list_jobs(fresh_uow, [ch, de], failures=failures)
    assert [j.board.source for j in jobs] == ["swissdevjobs"]
    assert "410" in failures["germantechjobs"]


def test_a_partial_result_says_so_in_band(fresh_uow):
    """Silence would read as "searched, nothing matched" — the one lie to avoid."""
    ch = FakeBoard(feed=[job()], board=BOARDS["swissdevjobs"])
    note = search.coverage_note(
        [ch], {}, query="python", category=None, tech=None, failures={"jobsch": "410"}
    )
    assert note and "partial" in note and "jobsch" in note


def test_every_board_failing_is_an_error_not_an_empty_feed(fresh_uow):
    ch = FakeBoard(feed=[job()], board=BOARDS["swissdevjobs"])
    ch.raises = OSError("connection reset")
    with pytest.raises(RuntimeError, match="every board failed"):
        search.list_jobs(fresh_uow, [ch])


def test_the_same_slug_on_two_boards_does_not_collide(fresh_uow):
    ch = FakeBoard(feed=[job()], board=BOARDS["swissdevjobs"])
    de = FakeBoard(
        feed=[job(_id="68b0000057370f0152e4950e")], board=BOARDS["germantechjobs"]
    )
    jobs = search.list_jobs(fresh_uow, [ch, de])
    assert len(jobs) == 2, "per-board slug uniqueness must keep both rows"


def test_cached_rows_remember_their_board(fresh_uow):
    de = FakeBoard(
        feed=[job(_id="68b0000057370f0152e4950e", jobUrl="de-role")],
        board=BOARDS["germantechjobs"],
    )
    search.list_jobs(fresh_uow, [de])
    cached = search.list_jobs(fresh_uow, [de])
    assert cached[0].board is BOARDS["germantechjobs"]
    assert cached[0].salary.currency == "EUR"


def test_a_warm_cache_is_no_longer_lossy(fresh_uow):
    """v1 reconstructed rows from columns and dropped expLevel; v2 must not."""
    ch = FakeBoard(feed=[job(expLevel="Senior")], board=BOARDS["swissdevjobs"])
    search.list_jobs(fresh_uow, [ch])
    ch.raises = RuntimeError("no network expected")
    cached = search.list_jobs(fresh_uow, [ch])
    assert cached[0].raw["expLevel"] == "Senior"
    assert search.matches(cached[0], level="Senior")
