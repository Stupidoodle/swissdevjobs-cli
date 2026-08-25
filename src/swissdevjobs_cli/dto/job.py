"""Job-shaped DTOs: the compact search row and the full apply payload."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from swissdevjobs_cli.domain.model.job import Job, JobDetail, strip_html
from swissdevjobs_cli.service_layer.apply import fallback_mode


@dataclass(frozen=True)
class JobSummaryDTO:
    """One compact search row. Full descriptions stay in the detail payload.

    Since 0.6.0 the row is omit-empty: keys whose value is None or an empty
    list are dropped (all-industry boards would otherwise ship six dead
    fields per row), and salary is numeric-only — ``salary_from``/
    ``salary_to`` plus ``currency``, no formatted string.
    """

    job_id: str | None
    title: str | None
    company: str | None
    city: str | None
    salary_from: int | None
    salary_to: int | None
    currency: str
    workplace: str | None
    language: str | None
    technologies: list[str]
    posted_at: str | None
    country: str
    source: str
    url: str

    @classmethod
    def from_domain(cls, job: Job, url: str) -> JobSummaryDTO:
        """Build from a domain Job; renders wire fields from `raw`."""
        raw = job.raw
        return cls(
            country=job.board.country,
            source=job.board.source,
            job_id=raw.get("_id"),
            title=raw.get("name"),
            company=raw.get("company"),
            city=raw.get("actualCity") or raw.get("cityCategory"),
            salary_from=raw.get("annualSalaryFrom"),
            salary_to=raw.get("annualSalaryTo"),
            currency=job.board.currency,
            workplace=raw.get("workplace"),
            language=raw.get("language"),
            technologies=list(raw.get("filterTags") or [])[:8],
            posted_at=raw.get("postedAt"),
            url=url,
        )

    def as_dict(self) -> dict[str, Any]:
        """The frozen wire shape, key order included; empty keys omitted."""
        row = {
            "job_id": self.job_id,
            "title": self.title,
            "company": self.company,
            "city": self.city,
            "salary_from": self.salary_from,
            "salary_to": self.salary_to,
            # A bare number is ambiguous across mixed-country result sets.
            "currency": (
                self.currency
                if self.salary_from is not None or self.salary_to is not None
                else None
            ),
            "workplace": self.workplace,
            "language": self.language,
            "technologies": self.technologies,
            "posted_at": self.posted_at,
            "country": self.country,
            "source": self.source,
            "url": self.url,
        }
        return {k: v for k, v in row.items() if v not in (None, [], "")}


@dataclass(frozen=True)
class JobDetailDTO:
    """Everything a caller needs to decide how to apply to one posting."""

    mode: str
    fallback_mode: str
    job_id: str
    title: str | None
    company: str | None
    location: str | None
    language: str | None
    posting_url: str
    apply_email: str | None
    apply_url: str | None
    questions: tuple[Any, ...]
    salary: str
    must_have: str
    nice_have: str
    responsibilities: str
    description: str
    technologies: list[str]
    applied: dict[str, Any] | None

    @classmethod
    def from_domain(
        cls,
        detail: JobDetail,
        *,
        posting_url: str,
        applied: dict[str, Any] | None = None,
    ) -> JobDetailDTO:
        """Build from a domain JobDetail.

        `direct` is the preferred mode wherever the board has a native apply
        form; boards without one (jobs.ch, jobup.ch) are `browser` — the
        posting's ATS is the only channel.
        """
        raw = detail.raw
        return cls(
            mode="direct" if detail.board.native_apply else "browser",
            fallback_mode=fallback_mode(detail),
            job_id=str(detail.id),
            title=raw.get("name"),
            company=raw.get("company"),
            location=raw.get("actualCity"),
            language=raw.get("language"),
            posting_url=posting_url,
            apply_email=detail.apply_email,
            apply_url=detail.redirect_url,
            questions=detail.questions,
            salary=detail.salary.format(),
            must_have=strip_html(raw.get("requirementsMustTextArea") or ""),
            nice_have=strip_html(raw.get("requirementsNiceTextArea") or ""),
            responsibilities=strip_html(raw.get("responsibilitiesTextArea") or ""),
            description=strip_html(raw.get("description") or ""),
            technologies=list(raw.get("technologies") or []),
            applied=applied,
        )

    def as_dict(self) -> dict[str, Any]:
        """The frozen wire shape, key order included."""
        return {
            "mode": self.mode,
            "fallback_mode": self.fallback_mode,
            "job_id": self.job_id,
            "title": self.title,
            "company": self.company,
            "location": self.location,
            "language": self.language,
            "posting_url": self.posting_url,
            "apply_email": self.apply_email,
            "apply_url": self.apply_url,
            "questions": list(self.questions),
            "salary": self.salary,
            "must_have": self.must_have,
            "nice_have": self.nice_have,
            "responsibilities": self.responsibilities,
            "description": self.description,
            "technologies": self.technologies,
            "applied": self.applied,
        }
