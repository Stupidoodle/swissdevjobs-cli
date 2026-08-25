"""Application tracking records and the applicant identity."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Applicant:
    """Who is applying — resolved from flags, the environment, or a .env file."""

    name: str
    email: str
    cv_path: str
    is_from_europe: bool = True
    lang_skills: str = "native"


@dataclass(frozen=True)
class ApplicationRecord:
    """One tracked application, mirroring a row of the applications table."""

    id: int | None
    job_id: str | None
    company: str
    role: str
    method: str
    status: str
    source: str
    applied_at: str | None
    notes: str | None

    def as_dict(self) -> dict[str, Any]:
        """The frozen wire shape used by the CLI and MCP outputs."""
        return {
            "id": self.id,
            "job_id": self.job_id,
            "company": self.company,
            "role": self.role,
            "method": self.method,
            "status": self.status,
            "source": self.source,
            "applied_at": self.applied_at,
            "notes": self.notes,
        }
