"""Board client for the devitjobs platform.

Endpoints (identical across the family's boards):
- GET  /api/jobsLight   → array of all active jobs (lightweight fields)
- GET  /api/job/{_id}   → full detail incl. description and requirements
- POST /api/jobApply    → native direct apply (multipart/form-data)
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from swissdevjobs_cli.adapters.boards.worldwide.devitjobs import acl
from swissdevjobs_cli.adapters.http.client import HttpClient
from swissdevjobs_cli.domain.model.application import Applicant
from swissdevjobs_cli.domain.model.board import Board
from swissdevjobs_cli.domain.model.job import Job, JobDetail


class DevITJobsClient:
    """Implements BoardPort for one board of the devitjobs family."""

    def __init__(self, board: Board, http: HttpClient):
        """Bind one Board of the family to an HTTP transport."""
        self.board = board
        self._http = http

    def fetch_jobs(self, *, force: bool = False) -> list[Job]:
        """Fetch the full lightweight feed from the board.

        On a forced refresh, bust Cloudflare's edge cache. `/api/jobsLight` is
        served with `Cache-Control: max-age=3600` and CF will happily hand back
        a HIT that is many hours stale (observed Age ~80k s), which would hide
        freshly-posted jobs. A unique query string yields a distinct cache key
        → MISS → origin-fresh data.
        """
        path = "/api/jobsLight"
        if force:
            path += f"?_cb={int(time.time())}"
        wire = json.loads(self._http.get(path).decode("utf-8"))
        return acl.jobs_from_wire(wire, self.board)

    def fetch_detail(self, job_id: str) -> JobDetail:
        """Fetch the full posting for one job id."""
        wire = json.loads(self._http.get(f"/api/job/{job_id}").decode("utf-8"))
        return acl.detail_from_wire(wire, self.board)

    def submit_application(
        self, detail: JobDetail, applicant: Applicant, motivation: str
    ) -> dict[str, Any]:
        """Submit a direct application via POST /api/jobApply.

        Honeypot fields (yearsOfExperience, personal_website_url, address,
        required_confirmation) are intentionally left empty — they are hidden
        from real users via CSS and serve as bot traps.
        """
        raw = detail.raw
        cv_bytes = Path(applicant.cv_path).read_bytes()
        cv_filename = Path(applicant.cv_path).name

        company_email = detail.apply_email or ""
        visa_sponsorship = raw.get("hasVisaSponsorship", "No")

        fields: dict[str, str] = {
            # Hidden metadata fields populated from job data
            "company": detail.company,
            "jobName": detail.title,
            "techCategory": raw.get("techCategory", ""),
            "hasLangCheck": "Yes" if detail.has_lang_check else "No",
            "doesCompanyAcceptFromOutsideEurope": str(visa_sponsorship),
            "hasCompanyContactEmail": "true" if company_email else "false",
            # Visible fields
            "name": applicant.name,
            "email": applicant.email,
            "isFromEurope": "Yes" if applicant.is_from_europe else "No",
            "motivationLetter": motivation,
            "wantsNewsletter": "No",
        }
        if company_email:
            fields["companyEmail"] = company_email
        if detail.has_lang_check:
            fields["langSkills"] = applicant.lang_skills

        files = {"cvFile": (cv_filename, cv_bytes, "application/pdf")}
        return self._http.post_multipart(
            "/api/jobApply",
            fields,
            files,
            referer=f"{self.board.base_url}/jobs/{detail.slug}",
        )
