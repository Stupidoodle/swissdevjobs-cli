"""Anti-corruption layer: MyCareersFuture wire JSON -> domain Job / JobDetail.

MyCareersFuture (api.mycareersfuture.gov.sg) is Singapore's government job
portal. Unlike JobCloud (jobs.ch/jobup.ch), list rows already carry real
salary, skills, and flexible-work-arrangement data — closer in richness to
the devitjobs family than to JobCloud's stripped search documents, even
though the board is search-driven like JobCloud (recon 2026-08-26: ~9,000
active postings in the Information Technology category alone).

Platform facts encoded here:
- `salary.type` varies ("Monthly" observed on every sampled posting); only
  "Monthly" and "Annual" are annualized with confidence — anything else
  (or a hidden-salary flag) is left unpublished rather than guessed.
- `flexibleWorkArrangements` uses Singapore's Tripartite Standard taxonomy
  (Flexi-Place / Flexi-Time / Flexi-Load); only Flexi-Place signals a
  remote-capable posting.
- `positionLevels` does not map cleanly onto the shared Junior/Regular/
  Senior/Principal/CLevel enum, so `level` filtering is declared
  unavailable rather than forced into a lossy guess — the original
  `positionLevels` array still survives in `raw`.
- there is no application-submission endpoint: apply instructions live in
  the HTML `description` (email or external ATS link), never a structured
  field the tool could POST to.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from swissdevjobs_cli.domain.model.board import Board
from swissdevjobs_cli.domain.model.ids import JobId
from swissdevjobs_cli.domain.model.job import Job, JobDetail, strip_html
from swissdevjobs_cli.domain.model.salary import SalaryRange

# Wire `employmentType` -> shared contract aliases (same one-to-many shape
# as the devitjobs JOBTYPE_CONTRACTS mapping).
EMPLOYMENT_TYPE_CONTRACTS: dict[str, tuple[str, ...]] = {
    "Permanent": ("permanent",),
    "Full Time": ("permanent",),
    "Part Time": ("permanent",),
    "Contract": ("freelance", "temporary"),
    "Temporary": ("temporary",),
    "Internship": ("internship",),
    "Flexi-work": ("supplementary",),
}

_FLEXI_PLACE = "flexi-place"


def _salary_range(wire: Mapping[str, Any], currency: str) -> SalaryRange:
    salary = wire.get("salary") or {}
    metadata = wire.get("metadata") or {}
    if metadata.get("isHideSalary"):
        return SalaryRange(lower=None, upper=None, currency=currency)
    kind = str(salary.get("type") or "")
    lo, hi = salary.get("minimum"), salary.get("maximum")
    if kind == "Monthly" and lo is not None and hi is not None:
        return SalaryRange(lower=lo * 12, upper=hi * 12, currency=currency)
    if kind == "Annual" and lo is not None and hi is not None:
        return SalaryRange(lower=lo, upper=hi, currency=currency)
    return SalaryRange(lower=None, upper=None, currency=currency)


def _skill_names(wire: Mapping[str, Any]) -> list[str]:
    names = []
    for entry in wire.get("skills") or []:
        if isinstance(entry, Mapping):
            name = entry.get("name")
            if name:
                names.append(str(name))
    return names


def _is_remote(wire: Mapping[str, Any]) -> str:
    arrangements = wire.get("flexibleWorkArrangements") or []
    for entry in arrangements:
        normalized = str(entry).lower().replace(" ", "-")
        if normalized == _FLEXI_PLACE:
            return "remote"
    return "onsite"


def _contract_types(wire: Mapping[str, Any]) -> list[str]:
    aliases: list[str] = []
    for entry in wire.get("employmentTypes") or []:
        if not isinstance(entry, Mapping):
            continue
        for alias in EMPLOYMENT_TYPE_CONTRACTS.get(entry.get("employmentType") or "", ()):
            if alias not in aliases:
                aliases.append(alias)
    return aliases


def _normalize(wire: Mapping[str, Any], board: Board) -> dict[str, Any]:
    """Original wire keys + the normalized keys the system reads."""
    raw = dict(wire)
    metadata = wire.get("metadata") or {}
    address = wire.get("address") or {}
    company = wire.get("postedCompany") or {}
    job_url = metadata.get("jobDetailsUrl") or ""

    raw["_id"] = wire.get("uuid") or ""
    raw["jobUrl"] = job_url or f"{board.base_url}/job/{wire.get('uuid') or ''}"
    raw["name"] = wire.get("title") or ""
    raw["company"] = company.get("name") or ""
    raw["actualCity"] = address.get("district") or None
    raw["language"] = None
    raw["activeFrom"] = metadata.get("newPostingDate")
    raw["postedAt"] = metadata.get("originalPostingDate")
    raw["postedAtUnix"] = None
    tech = _skill_names(wire)
    raw["technologies"] = tech
    raw["filterTags"] = tech
    raw["workplace"] = _is_remote(wire)
    raw["contractTypes"] = _contract_types(wire)
    raw["country"] = board.country
    raw["source"] = board.source
    salary = _salary_range(wire, board.currency)
    raw["annualSalaryFrom"] = salary.lower
    raw["annualSalaryTo"] = salary.upper
    return raw


def job_from_wire(wire: Mapping[str, Any], board: Board) -> Job:
    """One /v2/jobs list row -> domain Job."""
    raw = _normalize(wire, board)
    return Job(
        id=JobId(raw["_id"]),
        slug=raw["jobUrl"],
        title=raw["name"],
        company=raw["company"],
        city=raw.get("actualCity"),
        salary=SalaryRange(
            lower=raw["annualSalaryFrom"],
            upper=raw["annualSalaryTo"],
            currency=board.currency,
        ),
        posted_at_unix=raw["postedAtUnix"],
        board=board,
        raw=raw,
    )


def jobs_from_wire(rows: list[Mapping[str, Any]], board: Board) -> list[Job]:
    """One search response's rows -> domain Jobs."""
    return [job_from_wire(row, board) for row in rows]


def detail_from_wire(wire: Mapping[str, Any], board: Board) -> JobDetail:
    """A job row (list rows already carry the full description) -> JobDetail."""
    raw = _normalize(wire, board)
    raw["description"] = strip_html(str(wire.get("description") or ""))
    raw["candidateContactWay"] = None
    raw["redirectJobUrl"] = None
    return JobDetail(
        id=JobId(raw["_id"]),
        slug=raw["jobUrl"],
        title=raw["name"],
        company=raw["company"],
        city=raw.get("actualCity"),
        salary=SalaryRange(
            lower=raw["annualSalaryFrom"],
            upper=raw["annualSalaryTo"],
            currency=board.currency,
        ),
        language=None,
        contact_way=None,
        apply_email=None,
        redirect_url=None,
        questions=(),
        has_lang_check=False,
        board=board,
        raw=raw,
    )


def posting_url(board: Board, raw: Mapping[str, Any]) -> str:
    """The public URL of a posting, from the normalized jobUrl."""
    url = raw.get("jobUrl") or ""
    if url:
        return str(url)
    return f"{board.base_url}/job/{raw.get('_id') or ''}"
