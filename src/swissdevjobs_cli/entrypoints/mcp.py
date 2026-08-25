"""Model Context Protocol server over stdio.

Speaks JSON-RPC 2.0 on stdin/stdout with no dependencies — the protocol is
line-delimited JSON, which the stdlib already handles.

Two rules matter here:

1. **stdout is the transport.** Every diagnostic goes to stderr. A stray
   print corrupts the stream and the client drops the connection.
2. **Submitting an application is irreversible**, so `apply_to_job` is
   annotated as a non-readOnly, non-idempotent, open-world tool and returns
   a refusal unless the caller passes confirm=true. That gives the human on
   the other side of the model a place to say no.
"""

from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path
from typing import Any, Callable

from swissdevjobs_cli import bootstrap
from swissdevjobs_cli.adapters.boards.registry import BOARDS
from swissdevjobs_cli.adapters.boards.worldwide.devitjobs import acl
from swissdevjobs_cli.adapters.http.client import CaptchaRequired
from swissdevjobs_cli.domain.model.job import Job
from swissdevjobs_cli.dto.application import as_dict_or_none
from swissdevjobs_cli.dto.apply_preview import WouldSubmitDTO
from swissdevjobs_cli.dto.job import JobDetailDTO, JobSummaryDTO
from swissdevjobs_cli.service_layer import apply as apply_service
from swissdevjobs_cli.service_layer import config as config_service
from swissdevjobs_cli.service_layer import search, tracking

PROTOCOL_VERSION = "2025-06-18"
SERVER_NAME = "swissdevjobs"


def _log(message: str) -> None:
    """Diagnostics go to stderr; stdout belongs to the protocol."""
    print(f"[{SERVER_NAME}] {message}", file=sys.stderr, flush=True)


# --- tool implementations ---------------------------------------------------


def _summarize(job: Job) -> dict[str, Any]:
    """A compact row. Full descriptions come from get_job, to save context."""
    url = acl.posting_url(job.board, job.raw.get("jobUrl", ""))
    return JobSummaryDTO.from_domain(job, url).as_dict()


def _boards_for(runtime: bootstrap.Runtime, country: str) -> list:
    """Board clients for one country code, or every enabled board for "all"."""
    if country and country != "all":
        code = country.strip().lower()
        if code not in runtime.boards:
            raise ValueError(
                f"Unknown country {country!r}; known: {', '.join(sorted(BOARDS))}"
            )
        return [runtime.boards[code]]
    return runtime.enabled_boards()


def tool_search_jobs(
    runtime: bootstrap.Runtime,
    query: str | None = None,
    tech: list[str] | None = None,
    tech_all: bool = False,
    location: str | None = None,
    remote: bool | None = None,
    visa: bool | None = None,
    level: str | None = None,
    language: str | None = None,
    company: str | None = None,
    min_salary: int | None = None,
    max_salary: int | None = None,
    sort: str = "posted",
    limit: int = 25,
    include_applied: bool = False,
    country: str = "all",
) -> dict[str, Any]:
    """Compact search over the feed with every filter the CLI has."""
    uow = runtime.uow
    jobs = search.list_jobs(uow, _boards_for(runtime, country))
    hits = [
        j
        for j in jobs
        if search.matches(
            j,
            tech=tech,
            tech_any=not tech_all,
            location=location,
            remote=remote,
            visa=visa,
            level=level,
            min_salary=min_salary,
            max_salary=max_salary,
            language=language,
            query=query,
            company=company,
        )
    ]
    hits.sort(key=lambda j: search.sort_key(j, by=sort))

    hidden = 0
    if not include_applied:
        before = len(hits)
        hits = [j for j in hits if not tracking.is_job_applied(uow, j)]
        hidden = before - len(hits)

    total = len(hits)
    limit = max(1, min(limit, 100))
    return {
        "total_in_feed": len(jobs),
        "total_matching": total,
        "hidden_already_applied": hidden,
        "returned": min(limit, total),
        "jobs": [_summarize(j) for j in hits[:limit]],
    }


def tool_get_job(runtime: bootstrap.Runtime, job_id: str) -> dict[str, Any]:
    """The full posting as an apply-ready payload."""
    uow = runtime.uow
    jobs = search.list_jobs(uow, runtime.enabled_boards())
    job = search.resolve(jobs, job_id)
    if not job:
        raise ValueError(f"No job matching {job_id!r}")
    detail = search.get_detail(uow, runtime.board_for(job), str(job.id))
    return JobDetailDTO.from_domain(
        detail,
        posting_url=acl.posting_url(detail.board, detail.raw.get("jobUrl", "")),
        applied=as_dict_or_none(tracking.existing_application(uow, str(detail.id))),
    ).as_dict()


def tool_apply_to_job(
    runtime: bootstrap.Runtime,
    job_id: str,
    motivation: str,
    cv_path: str,
    confirm: bool = False,
    name: str | None = None,
    email: str | None = None,
    lang_skills: str = "native",
    is_from_europe: bool = True,
    force: bool = False,
) -> dict[str, Any]:
    """The irreversible one: native submission behind the confirm gate."""
    uow = runtime.uow
    jobs = search.list_jobs(uow, runtime.enabled_boards())
    job = search.resolve(jobs, job_id)
    if not job:
        raise ValueError(f"No job matching {job_id!r}")

    board = runtime.board_for(job)
    detail = search.get_detail(uow, board, str(job.id))
    existing = tracking.existing_application(uow, str(detail.id))
    if existing and not force:
        return {"already_applied": True, "application": existing.as_dict()}

    refusal = apply_service.undeliverable(detail)
    if refusal and not force:
        return refusal

    resolved = config_service.resolve_applicant(
        name,
        email,
        cv_path,
        labels=("name/$SDJ_NAME", "email/$SDJ_EMAIL", "cv_path/$SDJ_CV"),
    )
    if isinstance(resolved, list):
        return {"error": "missing_identity", "missing": resolved}
    if not Path(resolved.cv_path).is_file():
        return {"error": "cv_not_found", "cv_path": resolved.cv_path}
    motivation_error = apply_service.validate_motivation(motivation)
    if motivation_error:
        return {"error": "invalid_motivation", "message": motivation_error}

    applicant = resolved
    if not (is_from_europe and lang_skills == "native"):
        from swissdevjobs_cli.domain.model.application import Applicant

        applicant = Applicant(
            name=resolved.name,
            email=resolved.email,
            cv_path=resolved.cv_path,
            is_from_europe=is_from_europe,
            lang_skills=lang_skills,
        )

    # Irreversible: make the model surface it to a human before it happens.
    if not confirm:
        return {
            "error": "confirmation_required",
            "message": (
                "Submitting an application cannot be undone. Show the user the role, "
                "the salary, and the motivation letter, get their explicit approval, "
                "then call this tool again with confirm=true."
            ),
            "would_submit": WouldSubmitDTO.from_domain(
                detail, applicant, motivation
            ).as_dict(),
        }

    result, application = apply_service.submit_and_track(
        uow, board, detail, applicant, motivation
    )
    return {
        "submitted": result["status"] == 200,
        "http_status": result["status"],
        "response": result.get("response", "")[:500],
        "application": as_dict_or_none(application),
    }


def tool_list_applications(
    runtime: bootstrap.Runtime, limit: int = 100
) -> dict[str, Any]:
    """Every tracked application, newest first."""
    apps = [r.as_dict() for r in tracking.list_applications(runtime.uow, limit=limit)]
    return {"count": len(apps), "applications": apps}


def tool_mark_applied(
    runtime: bootstrap.Runtime,
    job_id: str,
    method: str,
    notes: str | None = None,
) -> dict[str, Any]:
    """Record an application submitted outside this tool."""
    uow = runtime.uow
    jobs = search.list_jobs(uow, runtime.enabled_boards())
    job = search.resolve(jobs, job_id)
    if not job:
        raise ValueError(f"No job matching {job_id!r}")
    detail = search.get_detail(uow, runtime.board_for(job), str(job.id))
    return tracking.mark_applied(
        uow,
        job_id=str(detail.id),
        company=detail.company,
        role=detail.title,
        method=method,
        notes=notes,
        source=detail.board.source,
    ).as_dict()


def tool_top_technologies(
    runtime: bootstrap.Runtime, limit: int = 25
) -> dict[str, Any]:
    """Tag frequency across the current feed."""
    jobs = search.list_jobs(runtime.uow, runtime.enabled_boards())
    return {
        "technologies": [
            {"name": n, "postings": c} for n, c in search.top_technologies(jobs, limit)
        ]
    }


# --- tool registry ----------------------------------------------------------

_STR = {"type": "string"}
_INT = {"type": "integer"}
_BOOL = {"type": "boolean"}

TOOLS: list[dict[str, Any]] = [
    {
        "name": "search_jobs",
        "title": "Search dev jobs across 7 countries",
        "description": (
            "Search the devitjobs board family — Switzerland, Germany, UK, "
            "US/Canada, Netherlands, France — where every posting must publish "
            "a salary range. Jobs already applied to are hidden unless "
            "include_applied is true. Returns compact rows; call get_job for "
            "the full posting."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    **_STR,
                    "description": "free text over title, company, city, tags",
                },
                "tech": {
                    "type": "array",
                    "items": _STR,
                    "description": "technology tags, e.g. ['Python', 'Kubernetes']",
                },
                "tech_all": {
                    **_BOOL,
                    "description": "require every tag (default: any)",
                },
                "location": {**_STR, "description": "city substring, e.g. 'Zurich'"},
                "remote": {**_BOOL, "description": "true = remote or hybrid only"},
                "visa": {**_BOOL, "description": "true = visa sponsorship only"},
                "level": {
                    **_STR,
                    "enum": ["Junior", "Regular", "Senior", "Principal", "CLevel"],
                },
                "language": {**_STR, "description": "posting language, e.g. 'English'"},
                "company": {**_STR, "description": "company name substring"},
                "min_salary": {**_INT, "description": "CHF per year"},
                "max_salary": {**_INT, "description": "CHF per year"},
                "sort": {
                    **_STR,
                    "enum": ["posted", "date", "salary", "company"],
                    "description": "posted = true creation time (default)",
                },
                "limit": {**_INT, "description": "max rows, 1-100 (default 25)"},
                "include_applied": {
                    **_BOOL,
                    "description": "show jobs already applied to",
                },
                "country": {
                    **_STR,
                    "enum": ["all", "ch", "de", "uk", "us", "nl", "fr"],
                    "description": (
                        "one board, or 'all' for every enabled board (default)"
                    ),
                },
            },
        },
        "annotations": {
            "title": "Search dev jobs across 7 countries",
            "readOnlyHint": True,
            "openWorldHint": True,
        },
        "handler": tool_search_jobs,
    },
    {
        "name": "get_job",
        "title": "Read a full posting",
        "description": (
            "Full detail for one posting: description, responsibilities, requirements, "
            "screening questions, how to apply, and whether it was already applied to."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "job_id": {**_STR, "description": "job id, URL slug, or substring"}
            },
            "required": ["job_id"],
        },
        "annotations": {
            "title": "Read a full posting",
            "readOnlyHint": True,
            "openWorldHint": True,
        },
        "handler": tool_get_job,
    },
    {
        "name": "apply_to_job",
        "title": "Submit an application",
        "description": (
            "Submit an application through the site's own form. IRREVERSIBLE. "
            "Call it first without confirm to get back exactly what would be sent, "
            "show that to the user, and only pass confirm=true once they agree. "
            "Refuses postings the site would silently drop, naming the real ATS URL. "
            "Identity falls back to $SDJ_NAME / $SDJ_EMAIL / $SDJ_CV."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "job_id": {**_STR, "description": "job id, URL slug, or substring"},
                "motivation": {
                    **_STR,
                    "description": "cover letter text; < and > are rejected",
                },
                "cv_path": {**_STR, "description": "absolute path to a PDF CV"},
                "confirm": {
                    **_BOOL,
                    "description": (
                        "must be true to actually submit; the user has to agree first"
                    ),
                },
                "name": {**_STR, "description": "applicant name (default: $SDJ_NAME)"},
                "email": {
                    **_STR,
                    "description": "applicant email (default: $SDJ_EMAIL)",
                },
                "lang_skills": {**_STR, "enum": ["native", "fluent", "good", "basic"]},
                "is_from_europe": {
                    **_BOOL,
                    "description": "EU/EEA/CH based (default true)",
                },
                "force": {
                    **_BOOL,
                    "description": "override duplicate and deliverability refusals",
                },
            },
            "required": ["job_id", "motivation", "cv_path"],
        },
        "annotations": {
            "title": "Submit an application",
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": True,
        },
        "handler": tool_apply_to_job,
    },
    {
        "name": "list_applications",
        "title": "List tracked applications",
        "description": "Every application recorded locally, newest first.",
        "inputSchema": {
            "type": "object",
            "properties": {"limit": {**_INT, "description": "max rows (default 100)"}},
        },
        "annotations": {
            "title": "List tracked applications",
            "readOnlyHint": True,
            "openWorldHint": False,
        },
        "handler": tool_list_applications,
    },
    {
        "name": "mark_applied",
        "title": "Record an application made elsewhere",
        "description": (
            "Record an application submitted outside this tool — by email, on an ATS, "
            "or through LinkedIn — so it stops appearing in future searches."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "job_id": {**_STR, "description": "job id, URL slug, or substring"},
                "method": {**_STR, "enum": ["email", "browser", "linkedin", "direct"]},
                "notes": {**_STR, "description": "anything worth remembering"},
            },
            "required": ["job_id", "method"],
        },
        "annotations": {
            "title": "Record an application made elsewhere",
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
        "handler": tool_mark_applied,
    },
    {
        "name": "top_technologies",
        "title": "Most-requested technologies",
        "description": "Which technologies appear most often across current postings.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {**_INT, "description": "how many tags (default 25)"}
            },
        },
        "annotations": {
            "title": "Most-requested technologies",
            "readOnlyHint": True,
            "openWorldHint": True,
        },
        "handler": tool_top_technologies,
    },
]

HANDLERS: dict[str, Callable[..., Any]] = {t["name"]: t["handler"] for t in TOOLS}
TOOL_SPECS = [{k: v for k, v in t.items() if k != "handler"} for t in TOOLS]


# --- JSON-RPC plumbing ------------------------------------------------------


def _result(request_id: Any, payload: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": payload}


def _error(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": code, "message": message},
    }


def _content(payload: Any, is_error: bool = False) -> dict[str, Any]:
    text = (
        payload
        if isinstance(payload, str)
        else json.dumps(payload, indent=2, ensure_ascii=False)
    )
    return {"content": [{"type": "text", "text": text}], "isError": is_error}


def _dispatch_tool(
    request_id: Any, params: dict, runtime: bootstrap.Runtime | None
) -> dict:
    """Run one tool call, mapping every failure to an in-band error payload."""
    name = params.get("name")
    handler = HANDLERS.get(name)
    if handler is None:
        return _error(request_id, -32602, f"Unknown tool: {name}")
    if runtime is None:
        runtime = bootstrap.build_runtime()
    try:
        return _result(
            request_id,
            _content(handler(runtime, **(params.get("arguments") or {}))),
        )
    except CaptchaRequired as e:
        return _result(
            request_id,
            _content(
                {
                    "error": "cloudflare_challenge",
                    "message": (
                        "swissdevjobs.ch returned a Cloudflare challenge. "
                        "The user needs to run `sdj auth` in a terminal "
                        f"and clear it at {e.url}."
                    ),
                },
                is_error=True,
            ),
        )
    except TypeError as e:
        return _result(
            request_id,
            _content({"error": "bad_arguments", "message": str(e)}, is_error=True),
        )
    except Exception as e:
        _log(f"tool {name} failed: {traceback.format_exc()}")
        return _result(
            request_id,
            _content({"error": type(e).__name__, "message": str(e)}, is_error=True),
        )


def handle_request(
    message: dict[str, Any], runtime: bootstrap.Runtime | None = None
) -> dict[str, Any] | None:
    """Route one JSON-RPC message. Returns None for notifications.

    ``runtime`` is the injection seam: tests pass a fake-board runtime here;
    production leaves it None and gets the real one, built lazily so that
    initialize/tools-list never touch the network or the database.
    """
    method = message.get("method")
    request_id = message.get("id")
    params = message.get("params") or {}

    if method == "initialize":
        return _result(
            request_id,
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": SERVER_NAME, "version": _version()},
                "instructions": (
                    "Search and apply to developer jobs in Switzerland, Germany, "
                    "the UK, the US/Canada, the Netherlands, and France. Every "
                    "posting carries a published salary range. Applying is "
                    "irreversible: call apply_to_job "
                    "without confirm first, show the user what would be sent, and only "
                    "re-call with confirm=true once they have agreed."
                ),
            },
        )

    # Notifications carry no id and expect no response.
    if request_id is None:
        return None

    if method == "tools/list":
        return _result(request_id, {"tools": TOOL_SPECS})

    if method == "tools/call":
        return _dispatch_tool(request_id, params, runtime)

    if method in ("resources/list", "prompts/list"):
        return _result(request_id, {"resources": [], "prompts": []})

    if method == "ping":
        return _result(request_id, {})

    return _error(request_id, -32601, f"Method not found: {method}")


def _version() -> str:
    from swissdevjobs_cli import __version__

    return __version__


def serve(stdin=None, stdout=None) -> int:
    """Read line-delimited JSON-RPC from stdin, answer on stdout."""
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
    _log(f"v{_version()} ready — {len(TOOLS)} tools over stdio")
    runtime: bootstrap.Runtime | None = None

    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError as e:
            print(
                json.dumps(_error(None, -32700, f"Parse error: {e}")),
                file=stdout,
                flush=True,
            )
            continue

        if runtime is None and message.get("method") == "tools/call":
            runtime = bootstrap.build_runtime()
        response = handle_request(message, runtime)
        if response is not None:
            print(json.dumps(response, ensure_ascii=False), file=stdout, flush=True)

    _log("stdin closed, shutting down")
    return 0


def main(argv: list[str] | None = None) -> int:
    """Console-script entry point."""
    try:
        return serve()
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
