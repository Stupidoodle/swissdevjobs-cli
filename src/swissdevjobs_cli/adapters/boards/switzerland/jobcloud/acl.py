"""Anti-corruption layer: JobCloud wire JSON → domain Job / JobDetail.

jobs.ch and jobup.ch share the JobCloud backend, so one translation covers
both boards — but as of 2026-08-28 its two halves no longer speak the same
dialect: search moved to `job-search-api.<board>/search` and renamed every
field to camelCase, while `/api/v1/public/search/job/{id}` kept the original
snake-case names. `search_doc_to_wire` folds the former into the latter, so
everything below this line sees one shape. The raw mapping keeps every
original wire key and adds the normalized keys (`name`, `company`,
`actualCity`, …) the rest of the system reads, so the filter/sort/output
paths never see platform-specific field names.

Platform facts the mapping encodes (recon 2026-08-25, re-verified 2026-08-28):
- no salary fields exist anywhere on the wire → SalaryRange stays empty;
- `language_skills` is a list of {language: ISO-639-1, level}; the FIRST
  entry is treated as the posting's primary language. It exists on details
  only — search rows carry an always-empty `languageIds`, so both boards
  declare "language" in `filters_unavailable`;
- `skills` is usually empty even on details — technology filters mostly
  can't match these rows client-side, server-side `query` is the honest way;
- `application_method` is `application_url` (external ATS) or `form`
  (JobCloud's own authenticated form) — neither is a native apply for us.
"""

from __future__ import annotations

import re
import unicodedata
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


def _slugify(text: str) -> str:
    ascii_only = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", ascii_only.lower())).strip("-")


def search_doc_to_wire(doc: Mapping[str, Any]) -> dict[str, Any]:
    """A `job-search-api` document → the snake-case shape the ACL reads.

    The search host renamed every field to camelCase when it moved off
    `/api/v1/public/search` (2026-08-28), but the detail endpoint kept the
    original names — and `Job.raw` is a frozen contract, so the snake-case
    keys are what consumers still get. The camelCase originals are kept
    alongside them: additive keys are allowed, removals are not.

    Two fields have no equivalent on the new search rows. `slug` is gone, so
    it is rebuilt in the detail endpoint's own `{id}-{title}` shape — it is
    the handle `sdj show` resolves against and dropping it would empty a
    contract key. `language_skills` is unrecoverable: `languageIds` exists
    but is empty on every row (200/200 sampled), which is why the boards
    declare "language" unfilterable rather than silently matching nothing.
    """
    wire = dict(doc)
    raw_company = doc.get("company")
    company: Mapping[str, Any] = raw_company if isinstance(raw_company, Mapping) else {}
    job_id = str(doc.get("id") or "")
    title = str(doc.get("title") or "")
    wire["job_id"] = job_id
    wire["title"] = title
    wire["slug"] = f"{job_id}-{_slugify(title)}" if job_id else ""
    wire["company_name"] = company.get("name") or ""
    wire["company_id"] = company.get("id")
    wire["company_slug"] = company.get("slug")
    wire["place"] = doc.get("place")
    wire["locations"] = doc.get("locations") or []
    wire["initial_publication_date"] = doc.get("initialPublicationDate")
    wire["publication_date"] = doc.get("publicationDate")
    wire["employment_type_ids"] = doc.get("employmentTypeIds") or []
    wire["employment_grades"] = doc.get("employmentGrades") or []
    wire["employment_position_ids"] = doc.get("employmentPositionIds") or []
    wire["benefit_ids"] = doc.get("benefitIds") or []
    wire["listing_tags"] = doc.get("listingTags") or []
    wire["is_paid"] = doc.get("isPaid")
    wire["language_skills"] = []
    return wire


def jobs_from_wire(documents: list[Mapping[str, Any]], board: Board) -> list[Job]:
    """One search response's documents → domain Jobs."""
    return [job_from_wire(search_doc_to_wire(doc), board) for doc in documents]


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
