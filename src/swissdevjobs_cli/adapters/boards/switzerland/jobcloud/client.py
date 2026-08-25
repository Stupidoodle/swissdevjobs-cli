"""Board client for the JobCloud platform (jobs.ch, jobup.ch).

Endpoints (identical on both boards, no auth, JSON):
- GET /api/v1/public/search?query=&rows=&page=&sort=&category-ids[]=
- GET /api/v1/public/search/job/{job_id}

Server-imposed limits (recon 2026-08-25): `rows` is hard-capped at 20 and
the result window at 2000 (~100 pages) — a full mirror of the ~45k-job
inventory is impossible by design, so this board is search-driven: every
fetch passes the user's query through and returns the matching slice,
newest first. There is NO native apply: `application_method` is either an
external ATS redirect or JobCloud's own authenticated form.
"""

from __future__ import annotations

import json
import os
import urllib.parse
from collections.abc import Mapping
from typing import Any

from swissdevjobs_cli.adapters.boards.switzerland.jobcloud import acl
from swissdevjobs_cli.adapters.http.client import HttpClient
from swissdevjobs_cli.domain.model.application import Applicant
from swissdevjobs_cli.domain.model.board import Board
from swissdevjobs_cli.domain.model.job import Job, JobDetail

ROWS_PER_PAGE = 20  # server hard cap; higher values are a 422
DEFAULT_PAGES = 5  # pages fetched per search → up to 100 rows per board

# Root category ids differ per board — each board runs its own taxonomy
# (jobup rejects jobs.ch ids with a 422).
CATEGORY_IDS: dict[str, dict[str, int]] = {
    "jobsch": {"it": 106},
    "jobup": {"it": 702},
}


def _page_budget() -> int:
    """Pages per search; SDJ_JOBCLOUD_PAGES overrides the default of 5."""
    try:
        return max(1, int(os.environ.get("SDJ_JOBCLOUD_PAGES", DEFAULT_PAGES)))
    except ValueError:
        return DEFAULT_PAGES


class JobCloudClient:
    """Implements BoardPort for one board of the JobCloud platform."""

    def __init__(self, board: Board, http: HttpClient):
        """Bind one Board of the platform to an HTTP transport."""
        self.board = board
        self._http = http

    def _search_page(self, params: list[tuple]) -> dict[str, Any]:
        qs = urllib.parse.urlencode(params)
        return json.loads(self._http.get(f"/api/v1/public/search?{qs}").decode("utf-8"))

    def fetch_jobs(
        self,
        *,
        query: str | None = None,
        category: str | None = None,
        force: bool = False,
    ) -> list[Job]:
        """The matching slice, newest first — or the newest postings, no query.

        ``category`` is an alias ("it") resolved against this board's own
        taxonomy. Pagination stops at the page budget, the server's own page
        count, and the 2000-result window, whichever comes first.
        """
        base: list[tuple] = [("rows", ROWS_PER_PAGE), ("sort", "date")]
        if query:
            base.append(("query", query))
        if category:
            ids = CATEGORY_IDS.get(self.board.source, {})
            if category not in ids:
                known = ", ".join(sorted(ids)) or "(none)"
                raise ValueError(
                    f"Unknown category {category!r} for {self.board.name}; "
                    f"known: {known}"
                )
            base.append(("category-ids[]", ids[category]))

        jobs: list[Job] = []
        for page in range(1, min(_page_budget(), 100) + 1):
            payload = self._search_page([*base, ("page", page)])
            documents = payload.get("documents") or []
            jobs.extend(acl.jobs_from_wire(documents, self.board))
            if page >= int(payload.get("num_pages") or 0) or not documents:
                break
        return jobs

    def fetch_detail(self, job_id: str) -> JobDetail:
        """Fetch the full posting for one job id."""
        wire = json.loads(
            self._http.get(f"/api/v1/public/search/job/{job_id}").decode("utf-8")
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
        """JobCloud has no native apply; the deliverability gate refuses first."""
        raise RuntimeError(
            f"{self.board.name} has no native apply endpoint — "
            "drive the posting's ATS via the apply URL instead"
        )
