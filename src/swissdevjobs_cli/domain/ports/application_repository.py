"""Port for tracked applications."""

from __future__ import annotations

import builtins
from typing import Any, Protocol

from swissdevjobs_cli.domain.model.application import ApplicationRecord


class ApplicationRepository(Protocol):
    """Records what was applied to, so nothing is ever submitted twice."""

    def get_by_job_id(self, job_id: str) -> ApplicationRecord | None:
        """The application for a job id, or None."""
        ...

    def get_by_company_role(self, company: str, role: str) -> ApplicationRecord | None:
        """Match for jobs applied to outside this tool (no job id known)."""
        ...

    def upsert(
        self,
        *,
        job_id: str | None,
        company: str,
        role: str,
        method: str,
        status: str = "submitted",
        notes: str | None = None,
        source: str = "swissdevjobs",
    ) -> ApplicationRecord:
        """Record an application; a duplicate job_id updates in place."""
        ...

    def list(self, limit: int = 100) -> builtins.list[ApplicationRecord]:
        """All applications, newest first."""
        ...

    def applied_company_roles(self) -> set[tuple[str, str]]:
        """Lowercased (company, role) pairs for id-less dedup."""
        ...

    def stats(self) -> dict[str, Any]:
        """Counters for `sdj stats`."""
        ...
