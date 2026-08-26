"""The MyCareersFuture board client, driven through a hand-written HTTP fake."""

from __future__ import annotations

import json
import urllib.parse

import pytest
from test_mycareersfuture_acl import doc

from swissdevjobs_cli.adapters.boards.registry import BOARDS
from swissdevjobs_cli.adapters.boards.singapore.mycareersfuture.client import (
    MyCareersFutureClient,
)

MCF = BOARDS["mycareersfuture"]


class FakeHttp:
    """Serves one canned /v2/jobs page per call, records every request."""

    def __init__(self, pages=None, detail=None):
        self.pages = pages or {}
        self.detail = detail
        self.gets = []

    def get(self, url, **kwargs):
        self.gets.append(url)
        path = url.split("?", 1)[0]
        if path.rstrip("/").rsplit("/", 1)[-1] not in ("jobs",):
            return json.dumps(self.detail).encode()
        query = urllib.parse.parse_qs(url.split("?", 1)[1])
        page = int(query.get("page", ["0"])[0])
        results = self.pages.get(page, [])
        return json.dumps({"results": results, "total": len(results)}).encode()


def test_fetch_jobs_calls_the_api_host_not_the_public_site():
    http = FakeHttp(pages={0: [doc()]})
    MyCareersFutureClient(MCF, http).fetch_jobs()
    assert http.gets[0].startswith("https://api.mycareersfuture.gov.sg/v2/jobs?")


def test_fetch_jobs_starts_at_page_zero():
    """The wire is 0-based; starting at 1 would skip the newest postings."""
    http = FakeHttp(pages={0: [doc()]})
    MyCareersFutureClient(MCF, http).fetch_jobs()
    assert "page=0" in http.gets[0]


def test_fetch_jobs_scopes_to_it_and_sorts_by_posting_date():
    http = FakeHttp(pages={0: []})
    MyCareersFutureClient(MCF, http).fetch_jobs()
    qs = http.gets[0].split("?", 1)[1]
    assert "categories=Information+Technology" in qs
    assert "sortBy=new_posting_date" in qs
    assert "limit=100" in qs


def test_a_query_is_passed_through_as_search():
    http = FakeHttp(pages={0: []})
    MyCareersFutureClient(MCF, http).fetch_jobs(query="python engineer")
    assert "search=python+engineer" in http.gets[0]


def test_no_query_still_returns_the_newest_postings():
    http = FakeHttp(pages={0: [doc()]})
    jobs = MyCareersFutureClient(MCF, http).fetch_jobs()
    assert len(jobs) == 1
    assert "search=" not in http.gets[0]


def test_fetch_jobs_stops_on_a_short_page():
    http = FakeHttp(pages={0: [doc(uuid=str(n) * 32) for n in range(5)]})
    jobs = MyCareersFutureClient(MCF, http).fetch_jobs()
    assert len(jobs) == 5
    assert len(http.gets) == 1


def test_fetch_jobs_pages_on_while_pages_are_full():
    full = [doc(uuid=f"{n:032x}") for n in range(100)]
    http = FakeHttp(pages={0: full, 1: full, 2: [doc(uuid="f" * 32)]})
    jobs = MyCareersFutureClient(MCF, http).fetch_jobs()
    assert len(jobs) == 201
    assert len(http.gets) == 3


def test_the_page_budget_caps_a_deep_result_set(monkeypatch):
    monkeypatch.setenv("SDJ_MYCAREERSFUTURE_PAGES", "2")
    full = [doc(uuid=f"{n:032x}") for n in range(100)]
    http = FakeHttp(pages={0: full, 1: full, 2: full, 3: full})
    jobs = MyCareersFutureClient(MCF, http).fetch_jobs()
    assert len(jobs) == 200
    assert len(http.gets) == 2


def test_a_nonsense_page_budget_falls_back_to_the_default(monkeypatch):
    monkeypatch.setenv("SDJ_MYCAREERSFUTURE_PAGES", "not-a-number")
    http = FakeHttp(pages={0: [doc()]})
    jobs = MyCareersFutureClient(MCF, http).fetch_jobs()
    assert len(jobs) == 1


def test_fetch_detail_hits_the_uuid_endpoint():
    http = FakeHttp(detail=doc())
    detail = MyCareersFutureClient(MCF, http).fetch_detail(
        "03c9772125f5d5737a8576c031b3f911"
    )
    assert http.gets[-1] == (
        "https://api.mycareersfuture.gov.sg/v2/jobs/03c9772125f5d5737a8576c031b3f911"
    )
    assert detail.company == "GENESYS CLOUD SERVICES SINGAPORE PTE. LTD."
    assert detail.board is MCF


def test_hydrate_detail_round_trips_a_cached_payload():
    client = MyCareersFutureClient(MCF, FakeHttp())
    cached = dict(client.hydrate_detail(doc()).raw)
    again = client.hydrate_detail(cached)
    assert again.company == "GENESYS CLOUD SERVICES SINGAPORE PTE. LTD."
    assert again.board is MCF


def test_posting_url_comes_from_the_wire_metadata():
    client = MyCareersFutureClient(MCF, FakeHttp())
    raw = client.hydrate_detail(doc()).raw
    assert client.posting_url(raw) == doc()["metadata"]["jobDetailsUrl"]


def test_submit_application_refuses_loudly():
    client = MyCareersFutureClient(MCF, FakeHttp())
    detail = client.hydrate_detail(doc())
    with pytest.raises(RuntimeError, match="no native apply"):
        client.submit_application(detail, None, "Dear hiring team")
