"""The port every job-board adapter implements."""

from __future__ import annotations

from typing import Any, Protocol

from swissdevjobs_cli.domain.model.application import Applicant
from swissdevjobs_cli.domain.model.board import Board
from swissdevjobs_cli.domain.model.job import Job, JobDetail


class BoardPort(Protocol):
    """Fetches postings from one board and submits native applications."""

    board: Board

    def fetch_jobs(self, *, force: bool = False) -> list[Job]:
        """The board's full lightweight feed, ACL-normalized to domain Jobs."""
        ...

    def fetch_detail(self, job_id: str) -> JobDetail:
        """The full posting for one job id."""
        ...

    def submit_application(
        self, detail: JobDetail, applicant: Applicant, motivation: str
    ) -> dict[str, Any]:
        """POST the board's native apply form. Returns {"status", "response"}."""
        ...
