"""The JobCloud board client, driven through a hand-written HTTP fake."""

from __future__ import annotations

import json
import urllib.parse

import pytest
from test_jobcloud_acl import detail_doc, search_doc

from swissdevjobs_cli.adapters.boards.registry import BOARDS
from swissdevjobs_cli.adapters.boards.switzerland.jobcloud.client import JobCloudClient


class FakeHttp:
    """Serves one canned search payload per page, records every request."""

    def __init__(self, pages=None, detail=None):
        self.pages = pages or {}
        self.detail = detail
        self.gets = []

    def get(self, path, **kwargs):
        self.gets.append(path)
        if "/api/v1/public/search/job/" in path:
            return json.dumps(self.detail).encode()
        query = urllib.parse.parse_qs(path.split("?", 1)[1])
        page = int(query["page"][0])
        payload = {
            "numPages": len(self.pages),
            "currentPage": page,
            "documents": self.pages.get(page, []),
        }
        return json.dumps(payload).encode()


def test_fetch_jobs_paginates_until_the_server_page_count():
    http = FakeHttp(
        pages={
            1: [search_doc(id="a" * 36)],
            2: [search_doc(id="b" * 36)],
        }
    )
    jobs = JobCloudClient(BOARDS["jobsch"], http).fetch_jobs()
    assert [str(j.id)[:1] for j in jobs] == ["a", "b"]
    assert len(http.gets) == 2


def test_the_page_budget_caps_a_deep_result_set(monkeypatch):
    monkeypatch.setenv("SDJ_JOBCLOUD_PAGES", "1")
    http = FakeHttp(pages={n: [search_doc(id=str(n) * 36)] for n in range(1, 9)})
    jobs = JobCloudClient(BOARDS["jobsch"], http).fetch_jobs()
    assert len(jobs) == 1
    assert len(http.gets) == 1


def test_a_query_is_passed_through_to_the_server():
    http = FakeHttp(pages={1: []})
    JobCloudClient(BOARDS["jobsch"], http).fetch_jobs(query="python zürich")
    assert http.gets[0].startswith("https://job-search-api.jobs.ch/search?")
    assert "query=python+z%C3%BCrich" in http.gets[0]
    assert "sort=date" in http.gets[0]
    assert "rows=100" in http.gets[0]


def test_the_it_category_resolves_per_board_taxonomy():
    http = FakeHttp(pages={1: []})
    JobCloudClient(BOARDS["jobsch"], http).fetch_jobs(category="it")
    assert "categoryIds=106" in http.gets[0]
    http2 = FakeHttp(pages={1: []})
    JobCloudClient(BOARDS["jobup"], http2).fetch_jobs(category="it")
    assert "categoryIds=702" in http2.gets[0]
    assert http2.gets[0].startswith("https://job-search-api.jobup.ch/search?")


def test_an_unknown_category_is_a_loud_error():
    with pytest.raises(ValueError, match="Unknown category"):
        JobCloudClient(BOARDS["jobsch"], FakeHttp()).fetch_jobs(category="gastro")


def test_fetch_detail_hits_the_public_job_endpoint():
    http = FakeHttp(detail=detail_doc())
    detail = JobCloudClient(BOARDS["jobsch"], http).fetch_detail("f667bc34")
    assert http.gets[0] == "/api/v1/public/search/job/f667bc34"
    # Details still live on the board's own domain — only search moved hosts.
    assert detail.redirect_url.startswith("https://stats.the-network.com/")


def test_hydrate_detail_round_trips_a_cached_payload():
    client = JobCloudClient(BOARDS["jobup"], FakeHttp())
    cached = dict(client.hydrate_detail(detail_doc()).raw)
    again = client.hydrate_detail(cached)
    assert again.company == "SEPPmail Deutschland GmbH"
    assert again.board is BOARDS["jobup"]


def test_submit_application_refuses_loudly():
    client = JobCloudClient(BOARDS["jobsch"], FakeHttp())
    detail = client.hydrate_detail(detail_doc())
    with pytest.raises(RuntimeError, match="no native apply"):
        client.submit_application(detail, None, "Dear team")


def test_contract_and_workload_filter_server_side():
    """The platform's own params do the filtering, server-side.

    Post-fetch filtering would waste the search-driven result window on
    rows the client then throws away.
    """
    http = FakeHttp(pages={1: []})
    JobCloudClient(BOARDS["jobsch"], http).fetch_jobs(contract="freelance", workload=80)
    assert "employmentTypeIds=2" in http.gets[0]
    assert "employmentGradeMin=80" in http.gets[0]
    assert "employmentGradeMax=80" in http.gets[0]
    # The retired endpoint IGNORED unknown params instead of rejecting them,
    # so a leftover snake-case name would quietly return the whole corpus.
    assert "employment-type-ids" not in http.gets[0]
