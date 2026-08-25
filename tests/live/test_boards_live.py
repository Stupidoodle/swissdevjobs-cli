"""Read-only smoke against the real boards. Opt in with SDJ_LIVE=1.

Never submits anything — the only endpoints touched are the public feeds.
"""

from __future__ import annotations

import os

import pytest

from swissdevjobs_cli.adapters import paths
from swissdevjobs_cli.adapters.boards.registry import BOARDS
from swissdevjobs_cli.adapters.boards.worldwide.devitjobs.client import DevITJobsClient
from swissdevjobs_cli.adapters.http.client import HttpClient

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(not os.environ.get("SDJ_LIVE"), reason="SDJ_LIVE not set"),
]


@pytest.mark.parametrize("code", sorted(BOARDS))
def test_every_board_serves_a_normalizable_feed(code):
    board = BOARDS[code]
    client = DevITJobsClient(board, HttpClient(board.base_url, paths.COOKIE_FILE))
    jobs = client.fetch_jobs()
    assert jobs, f"{board.name} returned an empty feed"
    sample = jobs[0]
    assert sample.id
    assert sample.raw["country"] == code
    assert sample.salary.currency == board.currency
