"""Board client for MyCareersFuture (Singapore's government job portal).

Endpoints (no auth, JSON) — note the API lives on a DIFFERENT HOST from the
board's ``base_url``: ``Board.base_url`` (www.mycareersfuture.gov.sg) is the
public site used for display links, while every call below goes to
``api.mycareersfuture.gov.sg``, so this client passes absolute URLs:

- GET /v2/jobs?search=&categories=&sortBy=&limit=&page=
- GET /v2/jobs/{uuid}

Server-imposed limits (recon 2026-08-26): ``limit`` is hard-capped at 100
(``limit=200`` is a 400) and ``page`` is ZERO-BASED — page 0 is the newest
page, so iterating from 1 would silently drop the freshest postings. The
Information Technology category alone holds ~9,000 live postings, so a full
mirror is impractical and this board is search-driven: every fetch passes
the user's query through and returns the matching slice, newest first. A
page past the end is a 200 with ``"results": []``, and a page shorter than
``limit`` is the last one.

There is NO native apply: apply instructions live in the posting's HTML
description (an email address or an external ATS link), never a structured
field this tool could POST to.
"""

from __future__ import annotations

import json
import os
import urllib.parse
from collections.abc import Mapping
from typing import Any

from swissdevjobs_cli.adapters.boards.singapore.mycareersfuture import acl
from swissdevjobs_cli.adapters.http.client import HttpClient
from swissdevjobs_cli.domain.model.application import Applicant
from swissdevjobs_cli.domain.model.board import Board
from swissdevjobs_cli.domain.model.job import Job, JobDetail

API_HOST = "https://api.mycareersfuture.gov.sg"  # not Board.base_url
ROWS_PER_PAGE = 100  # server hard cap; higher values are a 400
DEFAULT_PAGES = 3  # pages fetched per search → up to 300 rows
IT_CATEGORY = "Information Technology"  # the wire's own category label


def _page_budget() -> int:
    """Pages per search; SDJ_MYCAREERSFUTURE_PAGES overrides the default of 3."""
    try:
        return max(1, int(os.environ.get("SDJ_MYCAREERSFUTURE_PAGES", DEFAULT_PAGES)))
    except ValueError:
        return DEFAULT_PAGES


class MyCareersFutureClient:
    """Implements BoardPort for MyCareersFuture."""

    def __init__(self, board: Board, http: HttpClient):
        """Bind the board to an HTTP transport."""
        self.board = board
        self._http = http

    def _search_page(self, params: list[tuple]) -> dict[str, Any]:
        qs = urllib.parse.urlencode(params)
        return json.loads(self._http.get(f"{API_HOST}/v2/jobs?{qs}").decode("utf-8"))

    def fetch_jobs(
        self,
        *,
        query: str | None = None,
        category: str | None = None,
        contract: str | None = None,
        workload: int | None = None,
        force: bool = False,
    ) -> list[Job]:
        """The matching slice, newest first — or the newest postings, no query.

        ``query`` is passed server-side as ``search``. ``category``,
        ``contract`` and ``workload`` are accepted for BoardPort parity but
        do nothing here: the fetch is always scoped to the single
        Information Technology category, this wire carries no workload
        (percentage-of-full-time) data at all, and no server-side contract
        parameter has been confirmed — contract filtering therefore happens
        client-side in the service layer, off ``acl`` contract aliases.
        Pagination starts at page 0 and stops at the page budget or the
        first short page, whichever comes first.
        """
        base: list[tuple] = [
            ("categories", IT_CATEGORY),
            ("sortBy", "new_posting_date"),
            ("limit", ROWS_PER_PAGE),
        ]
        if query:
            base.append(("search", query))

        jobs: list[Job] = []
        for page in range(_page_budget()):  # the wire's `page` is 0-based
            payload = self._search_page([*base, ("page", page)])
            results = payload.get("results") or []
            jobs.extend(acl.jobs_from_wire(results, self.board))
            if len(results) < ROWS_PER_PAGE:
                break
        return jobs

    def fetch_detail(self, job_id: str) -> JobDetail:
        """Fetch the full posting for one job uuid."""
        wire = json.loads(
            self._http.get(f"{API_HOST}/v2/jobs/{job_id}").decode("utf-8")
        )
        return acl.detail_from_wire(wire, self.board)

    def hydrate_detail(self, raw: Mapping[str, Any]) -> JobDetail:
        """A cached raw detail payload → domain JobDetail."""
        return acl.detail_from_wire(raw, self.board)

    def posting_url(self, raw: Mapping[str, Any]) -> str:
        """The public URL of a posting on this board."""
        return acl.posting_url(self.board, raw)

    def submit_application(
        self, detail: JobDetail, applicant: Applicant, motivation: str
    ) -> dict[str, Any]:
        """No native apply here; the deliverability gate refuses first."""
        raise RuntimeError(
            f"{self.board.name} has no native apply endpoint — "
            "follow the apply instructions in the posting's description "
            "(email or external ATS link) instead"
        )
