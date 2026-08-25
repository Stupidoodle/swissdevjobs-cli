"""The confirm-gate preview: exactly what apply_to_job would submit."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from swissdevjobs_cli.domain.model.application import Applicant
from swissdevjobs_cli.domain.model.job import JobDetail


@dataclass(frozen=True)
class WouldSubmitDTO:
    """Shown to the human before an irreversible submission is allowed."""

    role: str | None
    company: str | None
    location: str | None
    salary: str
    applicant_name: str
    applicant_email: str
    cv_path: str
    motivation_preview: str
    motivation_chars: int

    @classmethod
    def from_domain(
        cls, detail: JobDetail, applicant: Applicant, motivation: str
    ) -> WouldSubmitDTO:
        """Build the preview from the exact values the submission would use."""
        raw = detail.raw
        return cls(
            role=raw.get("name"),
            company=raw.get("company"),
            location=raw.get("actualCity"),
            salary=detail.salary.format(),
            applicant_name=applicant.name,
            applicant_email=applicant.email,
            cv_path=applicant.cv_path,
            motivation_preview=motivation[:400],
            motivation_chars=len(motivation),
        )

    def as_dict(self) -> dict[str, Any]:
        """The frozen wire shape."""
        return {
            "role": self.role,
            "company": self.company,
            "location": self.location,
            "salary": self.salary,
            "applicant": {"name": self.applicant_name, "email": self.applicant_email},
            "cv_path": self.cv_path,
            "motivation_preview": self.motivation_preview,
            "motivation_chars": self.motivation_chars,
        }
