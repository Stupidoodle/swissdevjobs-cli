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
from swissdevjobs_cli.adapters.boards import registry
from swissdevjobs_cli.adapters.http.client import CaptchaRequired
from swissdevjobs_cli.domain.model.job import Job
from swissdevjobs_cli.dto.application import as_dict_or_none
from swissdevjobs_cli.dto.apply_preview import WouldSubmitDTO
from swissdevjobs_cli.dto.board import BoardDTO
from swissdevjobs_cli.dto.job import JobDetailDTO, JobSummaryDTO
from swissdevjobs_cli.service_layer import apply as apply_service
from swissdevjobs_cli.service_layer import config as config_service
from swissdevjobs_cli.service_layer import search, tracking

PROTOCOL_VERSION = "2025-06-18"
SUPPORTED_VERSIONS = (PROTOCOL_VERSION,)
SERVER_NAME = "swissdevjobs"

# Derived from the registry so prose can never drift from the board list.
_N_BOARDS = len(registry.BOARDS)
_N_COUNTRIES = len({b.country for b in registry.BOARDS.values()})
_SEARCH_TITLE = f"Search jobs across {_N_BOARDS} boards in {_N_COUNTRIES} countries"


def _log(message: str) -> None:
    """Diagnostics go to stderr; stdout belongs to the protocol."""
    print(f"[{SERVER_NAME}] {message}", file=sys.stderr, flush=True)


class ToolFault(Exception):
    """A tool failure with a stable, documented error code.

    The in-band ``error`` field is part of the wire contract — agents branch
    on it — so it must never leak a Python class name.
    """

    def __init__(self, code: str, message: str):
        """A machine-stable code plus the human-readable explanation."""
        super().__init__(message)
        self.code = code


# --- tool implementations ---------------------------------------------------


def _summarize(runtime: bootstrap.Runtime, job: Job) -> dict[str, Any]:
    """A compact row. Full descriptions come from get_job, to save context."""
    url = runtime.board_for(job).posting_url(job.raw)
    return JobSummaryDTO.from_domain(job, url).as_dict()


def _boards_for(runtime: bootstrap.Runtime, country: str) -> list:
    """Board clients for one selector (country code or source id), or "all"."""
    if country and country != "all":
        token = country.strip().lower()
        if token not in registry.known_selectors():
            raise ToolFault(
                "unknown_selector",
                f"Unknown board selector {country!r}; "
                f"known: {', '.join(registry.known_selectors())}",
            )
        return [
            runtime.boards[s]
            for s in registry.resolve_selectors([token])
            if s in runtime.boards
        ]
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
    contract: str | None = None,
    workload: int | None = None,
    sort: str = "posted",
    limit: int = 25,
    include_applied: bool = False,
    board: str | None = None,
    country: str = "all",
    category: str | None = None,
) -> dict[str, Any]:
    """Compact search over the feed with every filter the CLI has.

    ``board`` is the selector; ``country`` is its pre-0.5.1 name, kept as an
    alias (``board`` wins when both are passed).
    """
    uow = runtime.uow
    wanted = search.requested_filters(
        tech=tech,
        remote=remote,
        visa=visa,
        level=level,
        min_salary=min_salary,
        max_salary=max_salary,
        contract=contract,
        workload=workload,
    )
    board_clients, excluded = search.split_by_filterability(
        _boards_for(runtime, board or country), wanted
    )
    jobs = search.list_jobs(
        uow,
        board_clients,
        query=query,
        category=category,
        tech=tech,
        contract=contract,
        workload=workload,
    )
    hits = [
        j
        for j in jobs
        if search.matches(
            j,
            tech=search.tech_for(j, tech),
            tech_any=not tech_all,
            location=location,
            remote=remote,
            visa=visa,
            level=level,
            min_salary=min_salary,
            max_salary=max_salary,
            language=language,
            query=search.query_for(j, query),
            company=company,
            contract=contract,
            workload=workload,
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
    result: dict[str, Any] = {
        "total_in_feed": len(jobs),
        "total_matching": total,
        "hidden_already_applied": hidden,
        "returned": min(limit, total),
        "boards_searched": [b.board.source for b in board_clients],
    }
    if excluded:
        result["boards_excluded"] = excluded
    note = search.coverage_note(
        board_clients, excluded, query=query, category=category, tech=tech
    )
    if note:
        result["note"] = note
    result["jobs"] = [_summarize(runtime, j) for j in hits[:limit]]
    return result


def tool_get_job(runtime: bootstrap.Runtime, job_id: str) -> dict[str, Any]:
    """The full posting as an apply-ready payload."""
    uow = runtime.uow
    jobs = search.resolve_jobs(uow, runtime.enabled_boards())
    job = search.resolve(jobs, job_id)
    if not job:
        raise ToolFault(
            "job_not_found",
            f"No job matching {job_id!r} in the local cache — "
            "run search_jobs first; only listed jobs can be fetched",
        )
    board = runtime.board_for(job)
    detail = search.get_detail(uow, board, str(job.id))
    return JobDetailDTO.from_domain(
        detail,
        posting_url=board.posting_url(detail.raw),
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
    jobs = search.resolve_jobs(uow, runtime.enabled_boards())
    job = search.resolve(jobs, job_id)
    if not job:
        raise ToolFault("job_not_found", f"No job matching {job_id!r}")

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
    jobs = search.resolve_jobs(uow, runtime.enabled_boards())
    job = search.resolve(jobs, job_id)
    if not job:
        raise ToolFault("job_not_found", f"No job matching {job_id!r}")
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


def tool_list_boards(runtime: bootstrap.Runtime) -> dict[str, Any]:
    """Board facts as data — the discovery call the skills point at."""
    return {
        "boards": [
            BoardDTO.from_domain(
                b,
                categories=registry.categories_for(source),
                contracts=registry.contracts_for(source),
                enabled=source in runtime.enabled,
            ).as_dict()
            for source, b in registry.BOARDS.items()
        ]
    }


def tool_top_technologies(
    runtime: bootstrap.Runtime, limit: int = 25
) -> dict[str, Any]:
    """Tag frequency across the current feed (feed boards only)."""
    boards = [b for b in runtime.enabled_boards() if not b.board.search_driven]
    jobs = search.list_jobs(runtime.uow, boards)
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
        "title": _SEARCH_TITLE,
        "description": (
            "Search every enabled job board and return compact rows (call "
            "get_job for the full posting). Boards differ — call list_boards "
            "for each board's scope, salary availability, and categories. "
            "Search-driven boards return only their newest postings without "
            "a query, so pass the user's real search terms. Jobs already "
            "applied to are hidden unless include_applied is true."
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
                "contract": {
                    **_STR,
                    "enum": registry.known_contracts(),
                    "description": "contract type; boards map their own "
                    "taxonomy onto these aliases",
                },
                "workload": {
                    **_INT,
                    "description": "workload percent the posting must offer, "
                    "e.g. 80 — boards without workload data are excluded "
                    "visibly",
                },
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
                "board": {
                    **_STR,
                    "enum": ["all", *registry.known_selectors()],
                    "description": (
                        "board selector: a board id selects one board "
                        "('jobsch'), a country code every board there "
                        "('ch' = swissdevjobs + jobs.ch + jobup.ch), 'all' "
                        "every enabled board (default)"
                    ),
                },
                "country": {
                    **_STR,
                    "description": "deprecated alias of `board`",
                },
                "category": {
                    **_STR,
                    "enum": registry.known_categories(),
                    "description": (
                        "narrow all-industry boards to one category "
                        "(all-IT boards ignore it; see list_boards)"
                    ),
                },
            },
        },
        "annotations": {
            "readOnlyHint": True,
            "openWorldHint": True,
        },
        # Claude Code warns at 10k output tokens; a limit=100 search is ~14k.
        # This raises the per-tool ceiling so max-limit searches stay quiet.
        "_meta": {"anthropic/maxResultSizeChars": 200000},
        "handler": tool_search_jobs,
    },
    {
        "name": "list_boards",
        "title": "List the available job boards",
        "description": (
            "Every board this server can search, as data: scope (all-IT vs "
            "all-industries), currency, whether salary data is published, "
            "whether it is search-driven (pass query for real coverage), "
            "whether it has native apply (native_apply=false means driving "
            "the posting's ATS in a browser), its category aliases, and "
            "whether it is enabled in the current config."
        ),
        "inputSchema": {"type": "object", "properties": {}},
        "annotations": {
            "readOnlyHint": True,
            "openWorldHint": False,
        },
        "handler": tool_list_boards,
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
            "readOnlyHint": False,
            # destructiveHint deliberately OMITTED: the spec default is
            # true, and an irreversible outward submission should get every
            # confirmation layer a client keys on this hint — the in-band
            # confirm gate stays as defense in depth.
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
            "readOnlyHint": True,
            "openWorldHint": False,
        },
        "_meta": {"anthropic/maxResultSizeChars": 200000},
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
            "readOnlyHint": True,
            "openWorldHint": True,
        },
        "handler": tool_top_technologies,
    },
]

HANDLERS: dict[str, Callable[..., Any]] = {t["name"]: t["handler"] for t in TOOLS}
TOOL_SPECS = [{k: v for k, v in t.items() if k != "handler"} for t in TOOLS]
SPECS: dict[str, dict[str, Any]] = {t["name"]: t for t in TOOL_SPECS}


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
    # Compact separators on purpose: results are consumed by models, and
    # pretty-printing costs ~19% more tokens on every tool call.
    text = (
        payload
        if isinstance(payload, str)
        else json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
    )
    return {"content": [{"type": "text", "text": text}], "isError": is_error}


_SCHEMA_TYPES = {"string": str, "integer": int, "boolean": bool, "array": list}


def _invalid_argument(spec: dict[str, Any], arguments: dict[str, Any]) -> str | None:
    """Check arguments against the tool's own declared inputSchema.

    Enum membership and primitive types only — full JSON Schema validation
    would need a dependency, and this covers the real failure mode: a typoed
    enum value silently matching zero jobs, which an agent reads as "no jobs
    exist" and stops searching.
    """
    schema = spec["inputSchema"]
    props = schema.get("properties", {})
    for required in schema.get("required", []):
        if required not in arguments:
            return f"Missing required argument {required!r}"
    for key, value in arguments.items():
        prop = props.get(key)
        if prop is None:
            return f"Unknown argument {key!r}; known: {', '.join(sorted(props))}"
        if value is None:
            continue
        expected = _SCHEMA_TYPES.get(prop.get("type", ""))
        is_bad_bool = prop.get("type") == "integer" and isinstance(value, bool)
        if expected is not None and (not isinstance(value, expected) or is_bad_bool):
            return f"{key} expects type {prop['type']}"
        enum = prop.get("enum")
        if enum is not None and value not in enum:
            return f"{key} must be one of: {', '.join(map(str, enum))}"
    return None


def _dispatch_tool(
    request_id: Any, params: dict, runtime: bootstrap.Runtime | None
) -> dict:
    """Run one tool call, mapping every failure to an in-band error payload."""
    name = str(params.get("name") or "")
    handler = HANDLERS.get(name)
    if handler is None:
        return _error(request_id, -32602, f"Unknown tool: {name}")
    arguments = params.get("arguments") or {}
    problem = _invalid_argument(SPECS[name], arguments)
    if problem is not None:
        return _result(
            request_id,
            _content({"error": "invalid_arguments", "message": problem}, is_error=True),
        )
    if runtime is None:
        runtime = bootstrap.build_runtime()
    try:
        return _result(request_id, _content(handler(runtime, **arguments)))
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
    except ToolFault as e:
        return _result(
            request_id,
            _content({"error": e.code, "message": str(e)}, is_error=True),
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
            _content({"error": "internal_error", "message": str(e)}, is_error=True),
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
        # Single-version server: echo the client's version when we support
        # it, otherwise answer with ours (the client then decides whether to
        # disconnect). The membership check is what keeps this line honest
        # the day a second protocol version lands.
        requested = params.get("protocolVersion")
        version = requested if requested in SUPPORTED_VERSIONS else PROTOCOL_VERSION
        return _result(
            request_id,
            {
                "protocolVersion": version,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": SERVER_NAME, "version": _version()},
                "instructions": (
                    f"Search and apply to jobs across {_N_BOARDS} boards in "
                    f"{_N_COUNTRIES} countries. Call list_boards for each "
                    "board's scope, categories, salary availability, and "
                    "apply capability. Search-driven boards return only "
                    "their newest postings without a query — pass the "
                    "user's real search terms. Boards with "
                    "native_apply=false have no native form: apply_to_job "
                    "returns the posting's ATS URL to drive in a browser "
                    "instead. Applying is irreversible: call apply_to_job "
                    "without confirm first, show the user what would be "
                    "sent, and only re-call with confirm=true once they "
                    "have agreed."
                ),
            },
        )

    # Notifications carry no id and expect no response.
    if request_id is None:
        return None

    if method == "tools/list":
        # This server never returns nextCursor, so any cursor is invalid.
        if params.get("cursor") is not None:
            return _error(
                request_id, -32602, "Invalid cursor: this server does not paginate"
            )
        return _result(request_id, {"tools": TOOL_SPECS})

    if method == "tools/call":
        return _dispatch_tool(request_id, params, runtime)

    if method == "resources/list":
        return _result(request_id, {"resources": []})

    if method == "prompts/list":
        return _result(request_id, {"prompts": []})

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

        # Valid JSON that isn't an object (an array — e.g. a legacy JSON-RPC
        # batch, removed in spec 2025-06-18 — a number, a string) must get a
        # -32600, not crash the whole session.
        if not isinstance(message, dict):
            print(
                json.dumps(
                    _error(None, -32600, "Invalid Request: expected a JSON object")
                ),
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
