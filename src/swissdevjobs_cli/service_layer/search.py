"""Searching, filtering, sorting, and resolving jobs across the cache and feed."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from swissdevjobs_cli.domain.model.job import Job, JobDetail
from swissdevjobs_cli.domain.ports.board_port import BoardPort
from swissdevjobs_cli.domain.ports.unit_of_work import UnitOfWork

# resolve_jobs serves anything the cache ever held: you can only show or
# apply to what a past listing surfaced, however long ago that was.
_ANY_AGE = 10**10


def list_jobs(
    uow: UnitOfWork,
    boards: Sequence[BoardPort],
    *,
    query: str | None = None,
    category: str | None = None,
    tech: list[str] | None = None,
    max_age_seconds: int = 600,
    force: bool = False,
) -> list[Job]:
    """The browse corpus of every requested board.

    Feed boards serve their cached full feed when fresh enough. Search-driven
    boards always ask the server — their cache is an accumulation of past
    query slices, so it is never a truthful browse corpus — and their fresh
    rows are stored so show/apply can resolve them later.
    """
    combined: list[Job] = []
    for board in boards:
        jobs = None
        if not board.board.search_driven and not force:
            jobs = uow.jobs.cached_jobs(board.board.source, max_age_seconds)
        if jobs is None:
            jobs = board.fetch_jobs(
                query=server_query(board.board, query, tech),
                category=category,
                force=force,
            )
            uow.jobs.store_jobs(jobs)
        combined.extend(jobs)
    return combined


def server_query(board, query: str | None, tech: list[str] | None) -> str | None:
    """The query one board matches server-side.

    Boards that publish no technology tags fold the tech terms into their
    full-text query — the only place those terms can match at all (verified
    live: JobCloud ANDs multi-term queries, so folding narrows correctly).
    """
    if not board.search_driven or "tech" not in board.filters_unavailable:
        return query
    terms = ([query] if query else []) + list(tech or [])
    return " ".join(terms) or None


def requested_filters(
    *,
    tech: list[str] | None = None,
    remote: bool | None = None,
    visa: bool | None = None,
    level: str | None = None,
    min_salary: int | None = None,
    max_salary: int | None = None,
) -> set:
    """The filter dimensions this call actually asked for."""
    wanted = set()
    if tech:
        wanted.add("tech")
    if remote is not None:
        wanted.add("remote")
    if visa is True:
        wanted.add("visa")
    if level:
        wanted.add("level")
    if min_salary is not None or max_salary is not None:
        wanted.add("salary")
    return wanted


def split_by_filterability(
    boards: Sequence[BoardPort], wanted: set
) -> tuple[list, dict]:
    """(searchable, excluded): who can serve these filters, who cannot.

    A board missing a requested dimension is excluded up front — filtering
    its rows on data that does not exist would silently drop all of them,
    which reads as "searched, nothing matched". The one exception: a
    search-driven board missing only "tech" stays searchable, because the
    tech terms travel server-side as its query (see ``server_query``).
    """
    searchable: list = []
    excluded: dict = {}
    for board in boards:
        missing = [d for d in board.board.filters_unavailable if d in wanted]
        if missing and not (missing == ["tech"] and board.board.search_driven):
            excluded[board.board.source] = missing
        else:
            searchable.append(board)
    return searchable, excluded


def coverage_note(
    boards: Sequence[BoardPort],
    excluded: Mapping[str, list],
    *,
    query: str | None,
    category: str | None,
    tech: list[str] | None,
) -> str | None:
    """One in-band sentence on coverage gaps; None when coverage is honest.

    In-band steering survives context compaction; skill prose doesn't.
    """
    parts = []
    blind = [
        b.board.name
        for b in boards
        if b.board.search_driven
        and not query
        and not category
        and not server_query(b.board, query, tech)
    ]
    if blind:
        parts.append(
            f"{', '.join(blind)} returned newest postings only — "
            "pass a query for coverage"
        )
    folded = [
        b.board.name
        for b in boards
        if tech and b.board.search_driven and "tech" in b.board.filters_unavailable
    ]
    if folded:
        parts.append(
            f"{', '.join(folded)} matched the tech terms server-side "
            "(full-text, all terms required)"
        )
    if excluded:
        detail = "; ".join(
            f"{source}: no {', '.join(dims)} data" for source, dims in excluded.items()
        )
        parts.append(
            f"boards excluded — their platform publishes none of the "
            f"filtered data ({detail}); drop those filters to search them"
        )
    return " | ".join(parts) or None


def resolve_jobs(uow: UnitOfWork, boards: Sequence[BoardPort]) -> list[Job]:
    """The resolve corpus: every cached row, any age, plus never-fetched feeds.

    Resolution must be cheap and offline-stable — `sdj show` right after
    `sdj list` must not refetch anything, least of all a search-driven
    board's ten pages.
    """
    combined: list[Job] = []
    for board in boards:
        jobs = uow.jobs.cached_jobs(board.board.source, _ANY_AGE)
        if jobs is None and not board.board.search_driven:
            jobs = board.fetch_jobs()
            uow.jobs.store_jobs(jobs)
        combined.extend(jobs or [])
    return combined


def get_detail(
    uow: UnitOfWork,
    board: BoardPort,
    job_id: str,
    *,
    max_age_seconds: int = 3600,
    force: bool = False,
) -> JobDetail:
    """The full posting, served from the cache when fresh enough."""
    if not force:
        cached = uow.jobs.cached_detail(job_id, max_age_seconds)
        if cached is not None:
            return board.hydrate_detail(cached)

    detail = board.fetch_detail(job_id)
    uow.jobs.store_detail(job_id, dict(detail.raw))
    return detail


def query_for(job: Job, query: str | None) -> str | None:
    """The client-side query for one row.

    Rows from a search-driven board were already matched server-side —
    re-applying the query client-side would drop hits the server found in
    fields the light row doesn't carry (the description, most of all).
    """
    return None if job.board.search_driven else query


def tech_for(job: Job, tech: list[str] | None) -> list[str] | None:
    """The client-side tech tags for one row.

    Rows from boards without tech tags matched the terms server-side (they
    travelled as the query) — re-filtering on their always-empty tag list
    would drop every hit the server found.
    """
    return None if "tech" in job.board.filters_unavailable else tech


def resolve(jobs: list[Job], query: str) -> Job | None:
    """Find one job by id, exact slug, or slug/title substring."""
    q = query.lower()
    for j in jobs:
        if j.id == query or j.slug.lower() == q:
            return j
    for j in jobs:
        if q in j.slug.lower() or q in j.title.lower():
            return j
    return None


def _lower_set(xs: Iterable[str]) -> set:
    return {str(x).lower() for x in xs if x}


def _tech_ok(tags: set, tech: list[str] | None, tech_any: bool) -> bool:
    if not tech:
        return True
    wanted = _lower_set(tech)
    hit = tags & wanted
    if tech_any:
        return bool(hit)
    return hit == wanted


def _location_ok(raw: Mapping[str, Any], location: str | None) -> bool:
    if not location:
        return True
    hay = (
        (raw.get("cityCategory") or "") + " " + (raw.get("actualCity") or "")
    ).lower()
    return location.lower() in hay


def _workplace_ok(raw: Mapping[str, Any], remote: bool | None) -> bool:
    if remote is True and raw.get("workplace") not in ("remote", "hybrid"):
        return False
    return not (remote is False and raw.get("workplace") == "remote")


def _salary_ok(
    raw: Mapping[str, Any], min_salary: int | None, max_salary: int | None
) -> bool:
    if min_salary is not None and (raw.get("annualSalaryTo") or 0) < min_salary:
        return False
    return not (
        max_salary is not None and (raw.get("annualSalaryFrom") or 10**9) > max_salary
    )


def _query_ok(raw: Mapping[str, Any], tags: set, query: str | None) -> bool:
    if not query:
        return True
    hay = (
        " ".join(
            str(raw.get(k, "") or "")
            for k in ("name", "company", "actualCity", "techCategory")
        )
        + " "
        + " ".join(tags)
    )
    return query.lower() in hay.lower()


def matches(
    job: Job,
    *,
    tech: list[str] | None = None,
    tech_any: bool = True,
    location: str | None = None,
    remote: bool | None = None,
    visa: bool | None = None,
    level: str | None = None,
    min_salary: int | None = None,
    max_salary: int | None = None,
    language: str | None = None,
    query: str | None = None,
    company: str | None = None,
) -> bool:
    """Apply every requested filter; filters combine as AND.

    Reads the normalized wire mapping (`job.raw`) — the ACL guarantees these
    keys for every board of the platform, and the wire shape is the frozen
    contract the JSON output and cache round-trip share.
    """
    raw: Mapping[str, Any] = job.raw
    tags = _lower_set(
        list(raw.get("filterTags") or []) + list(raw.get("technologies") or [])
    )

    if not _tech_ok(tags, tech, tech_any):
        return False
    if not _location_ok(raw, location):
        return False
    if not _workplace_ok(raw, remote):
        return False
    if visa is True and raw.get("hasVisaSponsorship") != "Yes":
        return False
    if level and (raw.get("expLevel") or "").lower() != level.lower():
        return False
    if language and (raw.get("language") or "").lower() != language.lower():
        return False
    if not _salary_ok(raw, min_salary, max_salary):
        return False
    if company and company.lower() not in (raw.get("company") or "").lower():
        return False
    return _query_ok(raw, tags, query)


def _iso_to_epoch(iso: str) -> int:
    """Parse an ISO-8601-ish timestamp to unix seconds. Empty / unparseable → 0."""
    if not iso:
        return 0
    from datetime import datetime

    try:
        # Strip trailing 'Z' or timezone offset; MongoDB-style strings vary.
        s = iso.replace("Z", "+00:00")
        return int(datetime.fromisoformat(s).timestamp())
    except Exception:
        return 0


def sort_key(job: Job, *, by: str):
    """Sort key for one job. `posted` uses the immutable ObjectId timestamp."""
    raw = job.raw
    if by == "salary":
        return -(raw.get("annualSalaryTo") or raw.get("annualSalaryFrom") or 0)
    if by == "date":
        # Newest first by `activeFrom` (when the board last bumped it).
        return -_iso_to_epoch(raw.get("activeFrom") or "")
    if by == "posted":
        # Newest first by true posting time, decoded from the ObjectId.
        return -(job.posted_at_unix or 0)
    if by == "company":
        return job.company.lower()
    return 0


def top_technologies(jobs: list[Job], limit: int) -> list[tuple]:
    """The most-tagged technologies across the current feed."""
    counter: Counter = Counter()
    for job in jobs:
        for tag in job.raw.get("filterTags") or []:
            counter[tag] += 1
    return counter.most_common(limit)
