"""Anti-corruption layer: JobCloud wire JSON → domain Job / JobDetail.

jobs.ch and jobup.ch share the JobCloud backend (`/api/v1/public/search`,
`/api/v1/public/search/job/{id}`), so one translation covers both boards.
The raw mapping keeps every original wire key and adds the normalized keys
(`name`, `company`, `actualCity`, …) the rest of the system reads, so the
filter/sort/output paths never see platform-specific field names.

Platform facts the mapping encodes (recon 2026-08-25, jobcloud_recon.md):
- no salary fields exist anywhere on the wire → SalaryRange stays empty;
- `language_skills` is a list of {language: ISO-639-1, level}; the FIRST
  entry is treated as the posting's primary language;
- `skills` is usually empty even on details — technology filters mostly
  can't match these rows client-side, server-side `query` is the honest way;
- `application_method` is `application_url` (external ATS) or `form`
  (JobCloud's own authenticated form) — neither is a native apply for us.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any

from swissdevjobs_cli.domain.model.board import Board
from swissdevjobs_cli.domain.model.ids import JobId
from swissdevjobs_cli.domain.model.job import Job, JobDetail
from swissdevjobs_cli.domain.model.salary import SalaryRange

_LANGUAGE_NAMES = {
    "de": "German",
    "fr": "French",
    "en": "English",
    "it": "Italian",
}

# Shared contract aliases → the platform's employment-type ids. Mapping
# recon 2026-08-25: one sample posting per id checked against the label the
# site renders for it (id 2 returned exactly the postings labelled
# "Freelance", etc.); jobup.ch accepts the same ids — the taxonomy is
# platform-wide, unlike the per-board category trees.
CONTRACT_TYPE_IDS: dict[str, int] = {
    "temporary": 1,
    "freelance": 2,
    "internship": 3,
    "supplementary": 4,
    "permanent": 5,
    "apprenticeship": 6,
}
_ID_CONTRACTS = {str(i): alias for alias, i in CONTRACT_TYPE_IDS.items()}


def _primary_language(wire: Mapping[str, Any]) -> str | None:
    skills = wire.get("language_skills") or []
    if not skills or not isinstance(skills[0], Mapping):
        return None
    code = str(skills[0].get("language") or "").lower()
    return _LANGUAGE_NAMES.get(code, code or None)


def _epoch(iso: str | None) -> int | None:
    if not iso:
        return None
    try:
        return int(datetime.fromisoformat(str(iso).replace("Z", "+00:00")).timestamp())
    except ValueError:
        return None


def _skill_names(wire: Mapping[str, Any]) -> list[str]:
    names = []
    for entry in wire.get("skills") or []:
        if isinstance(entry, Mapping):
            name = entry.get("name") or entry.get("skill")
            if name:
                names.append(str(name))
        elif entry:
            names.append(str(entry))
    return names


def _normalize(wire: Mapping[str, Any], board: Board) -> dict[str, Any]:
    """Original wire keys + the normalized keys the system reads."""
    raw = dict(wire)
    posted_unix = _epoch(raw.get("initial_publication_date"))
    raw["_id"] = raw.get("job_id") or ""
    raw["jobUrl"] = raw.get("slug") or ""
    raw["name"] = raw.get("title") or ""
    raw["company"] = raw.get("company_name") or ""
    raw["actualCity"] = raw.get("place")
    raw["language"] = _primary_language(raw)
    raw["activeFrom"] = raw.get("publication_date")
    raw["postedAtUnix"] = posted_unix
    raw["postedAt"] = (
        raw.get("initial_publication_date") if posted_unix is not None else None
    )
    tech = _skill_names(raw)
    raw["technologies"] = tech
    raw["filterTags"] = tech
    raw["country"] = board.country
    raw["source"] = board.source
    raw["contractTypes"] = [
        _ID_CONTRACTS[str(i)]
        for i in raw.get("employment_type_ids") or []
        if str(i) in _ID_CONTRACTS
    ]
    grades = [g for g in raw.get("employment_grades") or [] if isinstance(g, int)]
    raw["workloadFrom"] = min(grades) if grades else None
    raw["workloadTo"] = max(grades) if grades else None
    return raw


def job_from_wire(wire: Mapping[str, Any], board: Board) -> Job:
    """One search document → domain Job."""
    raw = _normalize(wire, board)
    return Job(
        id=JobId(raw["_id"]),
        slug=raw["jobUrl"],
        title=raw["name"],
        company=raw["company"],
        city=raw.get("actualCity"),
        salary=SalaryRange.from_wire(raw, currency=board.currency),
        posted_at_unix=raw["postedAtUnix"],
        board=board,
        raw=raw,
    )


def jobs_from_wire(documents: list[Mapping[str, Any]], board: Board) -> list[Job]:
    """One search response's documents → domain Jobs."""
    return [job_from_wire(doc, board) for doc in documents]


def detail_from_wire(wire: Mapping[str, Any], board: Board) -> JobDetail:
    """A job-detail payload → domain JobDetail."""
    raw = _normalize(wire, board)
    redirect = raw.get("application_url") or raw.get("external_url") or None
    # Normalized detail keys the DTOs and CLI renderer read. template_text is
    # HTML; the DTO strips it at render time like devitjobs descriptions.
    raw["description"] = raw.get("template_text") or raw.get("template_lead_text") or ""
    raw["candidateContactWay"] = raw.get("application_method")
    raw["redirectJobUrl"] = redirect
    return JobDetail(
        id=JobId(raw["_id"]),
        slug=raw["jobUrl"],
        title=raw["name"],
        company=raw["company"],
        city=raw.get("actualCity"),
        salary=SalaryRange.from_wire(raw, currency=board.currency),
        language=raw.get("language"),
        contact_way=raw.get("application_method"),
        apply_email=None,
        redirect_url=redirect,
        questions=tuple(raw.get("application_questions") or ()),
        has_lang_check=False,
        board=board,
        raw=raw,
    )


def posting_url(board: Board, raw: Mapping[str, Any]) -> str:
    """The public URL of a posting, from the wire's `_links` block."""
    links = raw.get("_links") or {}
    for key in ("detail_en", "detail_de", "detail_fr"):
        href = (links.get(key) or {}).get("href")
        if href:
            return str(href)
    return f"{board.base_url}/en/vacancies/detail/{raw.get('job_id') or ''}/"
