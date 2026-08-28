"""Board client for the JobCloud platform (jobs.ch, jobup.ch).

Endpoints (no auth, JSON), one search host per board:
- GET https://job-search-api.<board>/search?query=&rows=&page=&sort=
      &categoryIds=&employmentTypeIds=&employmentGradeMin=&employmentGradeMax=
- GET {base_url}/api/v1/public/search/job/{job_id}

The search moved hosts on 2026-08-28: `/api/v1/public/search` on the board's
own domain now answers `410 Gone` with a `[]` body on both boards, while the
detail endpoint beside it still serves. `job-search-api.<board>` is the API
the site's own frontend calls, and it is the same search with camelCase
names — see ``acl.search_doc_to_wire``. Old snake-case params are IGNORED
rather than rejected there (`category-ids[]=106` silently returns the
unfiltered corpus), so every server-side filter is proved by effect in the
live lane, never by a 200.

Server-imposed limits (recon 2026-08-28): `rows` serves up to 200 (500 is an
empty body), the page number caps at 100, and deep pages fail past roughly
10k rows — a full mirror of the ~45k-job inventory is impossible by design,
so this board is search-driven: every fetch passes the user's query through
and returns the matching slice, newest first. There is NO native apply:
`application_method` is either an external ATS redirect or JobCloud's own
authenticated form.
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

ROWS_PER_PAGE = 100  # server serves up to 200; 100 keeps deep pages inside the window
DEFAULT_PAGES = 5  # pages fetched per search → up to 500 rows per board

# The search host per board — the board's own domain serves details only.
SEARCH_HOSTS: dict[str, str] = {
    "jobsch": "https://job-search-api.jobs.ch",
    "jobup": "https://job-search-api.jobup.ch",
}
SEARCH_PATH = "/search"
DETAIL_PATH = "/api/v1/public/search/job"
MAX_PAGE = 100  # the server's own page ceiling; page 101 comes back empty

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

    def _search_host(self) -> str:
        try:
            return SEARCH_HOSTS[self.board.source]
        except KeyError:
            raise ValueError(
                f"No JobCloud search host known for board {self.board.source!r}"
            ) from None

    def _search_page(self, params: list[tuple]) -> dict[str, Any]:
        qs = urllib.parse.urlencode(params)
        url = f"{self._search_host()}{SEARCH_PATH}?{qs}"
        return json.loads(self._http.get(url).decode("utf-8"))

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

        ``category`` is an alias ("it") resolved against this board's own
        taxonomy; ``contract`` and ``workload`` filter server-side (the ids
        are platform-wide — see ``acl.CONTRACT_TYPE_IDS``), which matters on
        a search-driven board: post-fetch filtering would waste the 2000-row
        result window on rows we then throw away. Pagination stops at the
        page budget, the server's own page count, and that window, whichever
        comes first.
        """
        base: list[tuple] = [("rows", ROWS_PER_PAGE), ("sort", "date")]
        if query:
            base.append(("query", query))
        if contract in acl.CONTRACT_TYPE_IDS:
            base.append(("employmentTypeIds", acl.CONTRACT_TYPE_IDS[contract]))
        if workload is not None:
            base.append(("employmentGradeMin", workload))
            base.append(("employmentGradeMax", workload))
        if category:
            ids = CATEGORY_IDS.get(self.board.source, {})
            if category not in ids:
                known = ", ".join(sorted(ids)) or "(none)"
                raise ValueError(
                    f"Unknown category {category!r} for {self.board.name}; "
                    f"known: {known}"
                )
            base.append(("categoryIds", ids[category]))

        jobs: list[Job] = []
        for page in range(1, min(_page_budget(), MAX_PAGE) + 1):
            payload = self._search_page([*base, ("page", page)])
            documents = payload.get("documents") or []
            jobs.extend(acl.jobs_from_wire(documents, self.board))
            if page >= int(payload.get("numPages") or 0) or not documents:
                break
        return jobs

    def fetch_detail(self, job_id: str) -> JobDetail:
        """Fetch the full posting for one job id."""
        wire = json.loads(self._http.get(f"{DETAIL_PATH}/{job_id}").decode("utf-8"))
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
