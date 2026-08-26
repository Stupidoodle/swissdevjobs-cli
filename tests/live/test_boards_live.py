"""Read-only smoke against the real boards. Opt in with SDJ_LIVE=1.

Never submits anything — the only endpoints touched are the public feeds.
"""

from __future__ import annotations

import os

import pytest

from swissdevjobs_cli.adapters import paths
from swissdevjobs_cli.adapters.boards.registry import BOARDS
from swissdevjobs_cli.adapters.boards.singapore.mycareersfuture.client import (
    MyCareersFutureClient,
)
from swissdevjobs_cli.adapters.boards.switzerland.jobcloud.client import JobCloudClient
from swissdevjobs_cli.adapters.boards.worldwide.devitjobs.client import DevITJobsClient
from swissdevjobs_cli.adapters.http.client import HttpClient

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(not os.environ.get("SDJ_LIVE"), reason="SDJ_LIVE not set"),
]

_CLIENTS = {
    "devitjobs": DevITJobsClient,
    "jobcloud": JobCloudClient,
    "mycareersfuture": MyCareersFutureClient,
}


def _client(board):
    http = HttpClient(board.base_url, paths.COOKIE_FILE)
    return _CLIENTS[board.platform](board, http)


@pytest.mark.parametrize("source", sorted(BOARDS))
def test_every_board_serves_a_normalizable_feed(source):
    board = BOARDS[source]
    jobs = _client(board).fetch_jobs()
    assert jobs, f"{board.name} returned an empty feed"
    sample = jobs[0]
    assert sample.id
    assert sample.raw["country"] == board.country
    assert sample.raw["source"] == source
    assert sample.salary.currency == board.currency


def test_a_jobcloud_query_actually_narrows():
    board = BOARDS["jobsch"]
    jobs = _client(board).fetch_jobs(query="python")
    assert jobs, "jobs.ch returned nothing for a python query"
    assert all(j.board is board for j in jobs)


def test_a_mycareersfuture_query_actually_narrows():
    board = BOARDS["mycareersfuture"]
    jobs = _client(board).fetch_jobs(query="python")
    assert jobs, "MyCareersFuture returned nothing for a python query"
    assert all(j.board is board for j in jobs)


def test_mycareersfuture_publishes_the_data_it_claims_to():
    """The wire nests salary and skills in shapes a plausible guess gets wrong.

    Asserted live because unit fixtures cannot catch the platform quietly
    reshaping them: a wrong guess yields None everywhere, not an error.
    """
    board = BOARDS["mycareersfuture"]
    jobs = _client(board).fetch_jobs()
    assert jobs, "MyCareersFuture returned an empty feed"
    priced = [j for j in jobs if j.salary.lower]
    tagged = [j for j in jobs if j.raw["technologies"]]
    located = [j for j in jobs if j.city]
    assert len(priced) > len(jobs) // 2, "salary.type nesting likely changed"
    assert len(tagged) > len(jobs) // 2, "skills[].skill key likely changed"
    assert len(located) > len(jobs) // 2, "address.districts shape likely changed"
    assert all(j.raw["workplace"] in ("remote", "onsite") for j in jobs)
