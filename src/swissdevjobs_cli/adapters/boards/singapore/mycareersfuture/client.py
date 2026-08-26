"""Board client for the MyCareersFuture platform (Singapore government portal).

Three read endpoints, no auth, all on `api.mycareersfuture.gov.sg` — a
different host from the board's `base_url`, which is only ever a display
and browser-link value:

- browse:  GET  /v2/jobs?categories=&sortBy=&limit=&page=
- search:  POST /v2/search?limit=&page=&sortBy=   {"search", "categories", …}
- detail:  GET  /v2/jobs/{uuid}

**Why search is a POST.** `GET /v2/jobs` accepts a `search=` parameter, and
that is what this client first used, but it does not work: any query not
already warm in the CDN returns HTTP 504 after ~29s (verified repeatedly on
2026-08-26 across many query strings; only queries someone had just fetched
came back). `POST /v2/search` answers the same queries in well under a
second. The GET path stays correct — and fast — for unqueried browsing, so
each is used where it actually works.

The two payloads differ, and the ACL absorbs it: POST rows carry no
`description` (resolved on demand by `fetch_detail`) and no
`metadata.originalPostingDate`, only the re-stampable `newPostingDate`.
Verified over 500 POST rows: every other field the ACL reads is present,
including `flexibleWorkArrangements` and `hiringCompany`.

`limit` caps at 100 (200 is a 400) and `page` is ZERO-based on both paths.
Neither path offers any way to submit an application.
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

API_HOST = "https://api.mycareersfuture.gov.sg"
BROWSE_PATH = "/v2/jobs"
SEARCH_PATH = "/v2/search"
ROWS_PER_PAGE = 100  # server hard cap; 200 is a 400
DEFAULT_PAGES = 3  # pages per fetch -> up to 300 rows
IT_CATEGORY = "Information Technology"
# Generous next to the ~1s these endpoints actually take. The 20s default
# was tuned for a different wire, and a slow answer beats a spurious failure.
TIMEOUT = 45


def _page_budget() -> int:
    """Pages per fetch; SDJ_MYCAREERSFUTURE_PAGES overrides the default of 3."""
    try:
        return max(1, int(os.environ.get("SDJ_MYCAREERSFUTURE_PAGES", DEFAULT_PAGES)))
    except ValueError:
        return DEFAULT_PAGES


class MyCareersFutureClient:
    """Implements BoardPort for the MyCareersFuture platform."""

    def __init__(self, board: Board, http: HttpClient):
        """Bind the board to a transport; calls target API_HOST, not base_url."""
        self.board = board
        self._http = http

    def _browse_page(self, page: int) -> list:
        """One page of the unqueried feed, via GET."""
        params = [
            ("categories", IT_CATEGORY),
            ("sortBy", "new_posting_date"),
            ("limit", ROWS_PER_PAGE),
            ("page", page),
        ]
        url = f"{API_HOST}{BROWSE_PATH}?{urllib.parse.urlencode(params)}"
        payload = json.loads(self._http.get(url, timeout=TIMEOUT).decode("utf-8"))
        return payload.get("results") or []

    def _search_page(self, query: str, page: int) -> list:
        """One page of query results, via POST — the only path that answers."""
        params = [
            ("limit", ROWS_PER_PAGE),
            ("page", page),
            ("sortBy", "new_posting_date"),
        ]
        url = f"{API_HOST}{SEARCH_PATH}?{urllib.parse.urlencode(params)}"
        body = {"search": query, "sessionId": "", "categories": [IT_CATEGORY]}
        raw = self._http.post_json(url, body, timeout=TIMEOUT)
        payload = json.loads(raw.decode("utf-8"))
        return payload.get("results") or []

    def fetch_jobs(
        self,
        *,
        query: str | None = None,
        category: str | None = None,
        contract: str | None = None,
        workload: int | None = None,
        force: bool = False,
    ) -> list[Job]:
        """The matching slice, newest first — or the newest IT postings, no query.

        A query goes to the POST search endpoint, the only one that answers
        reliably; without one the GET feed is used, which is faster and
        carries the richer payload. Pagination is zero-based on both paths
        and stops on the first short page.

        ``category`` is unused: every fetch is scoped to Information
        Technology, matching the board's declared ``scope="it"``.
        ``contract`` and ``workload`` are accepted for protocol parity only —
        neither has a confirmed server-side parameter here, and ``workload``
        has no wire field at all (the board declares it unavailable).
        """
        rows: list = []
        for page in range(_page_budget()):
            got = self._search_page(query, page) if query else self._browse_page(page)
            rows.extend(got)
            if len(got) < ROWS_PER_PAGE:
                break
        return acl.jobs_from_wire(rows, self.board)

    def fetch_detail(self, job_id: str) -> JobDetail:
        """Fetch the full posting — the only place a description is available."""
        url = f"{API_HOST}{BROWSE_PATH}/{job_id}"
        wire = json.loads(self._http.get(url, timeout=TIMEOUT).decode("utf-8"))
        return acl.detail_from_wire(wire, self.board)

    def hydrate_detail(self, raw: Mapping[str, Any]) -> JobDetail:
        """A cached raw detail payload -> domain JobDetail."""
        return acl.detail_from_wire(raw, self.board)

    def posting_url(self, raw: Mapping[str, Any]) -> str:
        """The public URL of a posting on this board."""
        return acl.posting_url(self.board, raw)

    def submit_application(
        self, detail: JobDetail, applicant: Applicant, motivation: str
    ) -> dict[str, Any]:
        """MyCareersFuture has no apply endpoint; the deliverability gate refuses."""
        raise RuntimeError(
            f"{self.board.name} has no native apply endpoint — "
            "apply on the posting page, which carries the portal's own "
            "application flow"
        )
