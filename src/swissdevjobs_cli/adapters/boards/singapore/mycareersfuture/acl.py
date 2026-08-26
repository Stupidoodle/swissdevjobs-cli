"""Anti-corruption layer: MyCareersFuture wire JSON -> domain Job / JobDetail.

MyCareersFuture (api.mycareersfuture.gov.sg) is Singapore's government job
portal. Unlike JobCloud (jobs.ch/jobup.ch), list rows already carry real
salary, skills, and flexible-work-arrangement data — closer in richness to
the devitjobs family than to JobCloud's stripped search documents, even
though the board is search-driven like JobCloud (recon 2026-08-26: ~9,000
active postings in the Information Technology category alone).

Wire shapes verified against 300 live IT postings on 2026-08-26. The ones
that bite, because a plausible guess is wrong in every case:

- `salary.type` is an OBJECT (`{"id": 4, "salaryType": "Monthly"}`), not a
  string. Every sampled posting was Monthly, so the range is annualized
  ×12; "Annual" is honoured defensively. Any other unit — or a truthy
  `metadata.isHideSalary` — leaves the range unpublished rather than
  guessed, because a wrong salary is worse than no salary.
- `skills[]` entries are keyed `skill` (not `name`), alongside `uuid`,
  `confidence`, and `isKeySkill`.
- `flexibleWorkArrangements[]` entries are objects keyed
  `flexibleWorkArrangement`. The observed vocabulary is Telecommuting,
  Flexi-Hours, Staggered Time, Compressed Work Schedule, Creative
  Scheduling, and Employees Choice of Days Off — there is no "Flexi-Place".
  Only Telecommuting is location flexibility, so only it means remote; the
  rest are time flexibility and must not be mistaken for it.
- `address` has no singular `district` key (0 of 300 rows). Location lives
  in `address.districts[]`, always exactly one entry, carrying a verbose
  `location` ("D01 Marina, Raffles Place, People's Park, Cecil") and a
  coarse `region` ("Central", "West", "Islandwide"). Both are kept:
  `actualCity` and `cityCategory`, the same pair the devitjobs wire uses,
  so `--location` substring matching works against either.
- `uuid` is a 32-char hex string with no dashes. It is NOT a MongoDB
  ObjectId, but it would happily hex-decode as one into a 1972 timestamp,
  so `postedAtUnix` is parsed from `metadata.originalPostingDate` instead
  and cached rows MUST round-trip through `light_json`.
- `positionLevels` ("Professional", "Executive", "Manager", "Middle
  Management", "Fresh/entry level", …) has no honest mapping onto the
  shared Junior/Regular/Senior/Principal/CLevel enum, so `level` filtering
  is declared unavailable on the Board rather than guessed at here. The
  original array survives in `raw` for anything that wants it.
- there is no application-submission endpoint: apply instructions live in
  the HTML `description` (email or external ATS link), never a structured
  field the tool could POST to.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

from swissdevjobs_cli.domain.model.board import Board
from swissdevjobs_cli.domain.model.ids import JobId
from swissdevjobs_cli.domain.model.job import Job, JobDetail, strip_html
from swissdevjobs_cli.domain.model.salary import SalaryRange

# Wire `employmentType` -> shared contract aliases. Values verified live;
# "Full Time"/"Part Time" describe hours rather than tenure, so they map to
# `permanent` exactly as the devitjobs ACL maps its own Full-/Part-Time.
EMPLOYMENT_TYPE_CONTRACTS: dict[str, tuple[str, ...]] = {
    "Permanent": ("permanent",),
    "Full Time": ("permanent",),
    "Part Time": ("permanent",),
    "Contract": ("freelance", "temporary"),
    "Temporary": ("temporary",),
    "Freelance": ("freelance",),
    "Internship/Attachment": ("internship",),
}

# The one flexible-work-arrangement that means *where*, not *when*.
_TELECOMMUTING = "telecommuting"

_MONTHS_PER_YEAR = 12


def _epoch(date_str: str | None) -> int | None:
    """A wire date ("2026-08-20") -> unix seconds at UTC midnight, or None.

    UTC is forced deliberately: a naive `.timestamp()` would resolve
    against the runner's local zone and make the cache — and the tests —
    machine-dependent.
    """
    if not date_str:
        return None
    try:
        parsed = datetime.fromisoformat(str(date_str).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return int(parsed.timestamp())


def _salary_range(wire: Mapping[str, Any], currency: str) -> SalaryRange:
    """The annual range, or an empty one when the unit isn't one we trust."""
    empty = SalaryRange(lower=None, upper=None, currency=currency)
    metadata = wire.get("metadata") or {}
    if metadata.get("isHideSalary"):
        return empty

    salary = wire.get("salary") or {}
    kind_wire = salary.get("type")
    kind = kind_wire.get("salaryType") if isinstance(kind_wire, Mapping) else kind_wire
    low, high = salary.get("minimum"), salary.get("maximum")
    if low is None or high is None:
        return empty
    if kind == "Monthly":
        return SalaryRange(
            lower=low * _MONTHS_PER_YEAR,
            upper=high * _MONTHS_PER_YEAR,
            currency=currency,
        )
    if kind == "Annual":
        return SalaryRange(lower=low, upper=high, currency=currency)
    return empty


def _skill_names(wire: Mapping[str, Any]) -> list[str]:
    """Skill labels, from the wire's `skill` key."""
    names = []
    for entry in wire.get("skills") or []:
        if isinstance(entry, Mapping):
            name = entry.get("skill")
            if name:
                names.append(str(name))
    return names


def _workplace(wire: Mapping[str, Any]) -> str:
    """Remote only for Telecommuting; the rest flex *when*, not *where*."""
    for entry in wire.get("flexibleWorkArrangements") or []:
        label = (
            entry.get("flexibleWorkArrangement")
            if isinstance(entry, Mapping)
            else entry
        )
        if str(label or "").strip().lower() == _TELECOMMUTING:
            return "remote"
    return "onsite"


def _district(wire: Mapping[str, Any]) -> tuple[str | None, str | None]:
    """(location, region) from the first `address.districts` entry."""
    districts = (wire.get("address") or {}).get("districts") or []
    if not districts or not isinstance(districts[0], Mapping):
        return None, None
    first = districts[0]
    return first.get("location") or None, first.get("region") or None


def _contract_types(wire: Mapping[str, Any]) -> list[str]:
    """Shared contract aliases for this posting's employment types."""
    aliases: list[str] = []
    for entry in wire.get("employmentTypes") or []:
        if not isinstance(entry, Mapping):
            continue
        wire_type = entry.get("employmentType") or ""
        for alias in EMPLOYMENT_TYPE_CONTRACTS.get(wire_type, ()):
            if alias not in aliases:
                aliases.append(alias)
    return aliases


def _normalize(wire: Mapping[str, Any], board: Board) -> dict[str, Any]:
    """Original wire keys + the normalized keys the system reads."""
    raw = dict(wire)
    metadata = wire.get("metadata") or {}
    company = wire.get("postedCompany") or {}
    uuid = wire.get("uuid") or ""
    location, region = _district(wire)
    salary = _salary_range(wire, board.currency)

    raw["_id"] = uuid
    raw["jobUrl"] = metadata.get("jobDetailsUrl") or f"{board.base_url}/job/{uuid}"
    raw["name"] = wire.get("title") or ""
    raw["company"] = company.get("name") or ""
    raw["actualCity"] = location
    raw["cityCategory"] = region
    # No language field exists on the wire, but the platform is English-only
    # by policy (postings render as "English (original)" with machine
    # translations). None here would make `--language en` silently drop
    # every row — the silent-empty lie the parity contract forbids.
    raw["language"] = "en"
    raw["activeFrom"] = metadata.get("newPostingDate")
    raw["postedAt"] = metadata.get("originalPostingDate")
    raw["postedAtUnix"] = _epoch(metadata.get("originalPostingDate"))
    tech = _skill_names(wire)
    raw["technologies"] = tech
    raw["filterTags"] = tech
    raw["workplace"] = _workplace(wire)
    raw["contractTypes"] = _contract_types(wire)
    raw["country"] = board.country
    raw["source"] = board.source
    raw["annualSalaryFrom"] = salary.lower
    raw["annualSalaryTo"] = salary.upper
    return raw


def _salary_of(raw: Mapping[str, Any], board: Board) -> SalaryRange:
    return SalaryRange(
        lower=raw["annualSalaryFrom"],
        upper=raw["annualSalaryTo"],
        currency=board.currency,
    )


def job_from_wire(wire: Mapping[str, Any], board: Board) -> Job:
    """One /v2/jobs list row -> domain Job."""
    raw = _normalize(wire, board)
    return Job(
        id=JobId(raw["_id"]),
        slug=raw["jobUrl"],
        title=raw["name"],
        company=raw["company"],
        city=raw.get("actualCity") or raw.get("cityCategory"),
        salary=_salary_of(raw, board),
        posted_at_unix=raw["postedAtUnix"],
        board=board,
        raw=raw,
    )


def jobs_from_wire(rows: list[Mapping[str, Any]], board: Board) -> list[Job]:
    """One search response's rows -> domain Jobs."""
    return [job_from_wire(row, board) for row in rows]


def detail_from_wire(wire: Mapping[str, Any], board: Board) -> JobDetail:
    """A job row -> domain JobDetail (list rows already carry the description)."""
    raw = _normalize(wire, board)
    raw["description"] = strip_html(str(wire.get("description") or ""))
    raw["candidateContactWay"] = None
    raw["redirectJobUrl"] = None
    return JobDetail(
        id=JobId(raw["_id"]),
        slug=raw["jobUrl"],
        title=raw["name"],
        company=raw["company"],
        city=raw.get("actualCity") or raw.get("cityCategory"),
        salary=_salary_of(raw, board),
        language=raw["language"],
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
