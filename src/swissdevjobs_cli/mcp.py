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
from typing import Any, Callable

from . import api, db
from .filter import matches, sort_key
from .payloads import apply_payload, fmt_salary, undeliverable

PROTOCOL_VERSION = "2025-06-18"
SERVER_NAME = "swissdevjobs"


def _log(message: str) -> None:
    """Diagnostics go to stderr; stdout belongs to the protocol."""
    print(f"[{SERVER_NAME}] {message}", file=sys.stderr, flush=True)


# --- tool implementations ---------------------------------------------------


def _summarize(job: dict[str, Any]) -> dict[str, Any]:
    """A compact row. Full descriptions come from get_job, to save context."""
    return {
        "job_id": job.get("_id"),
        "title": job.get("name"),
        "company": job.get("company"),
        "city": job.get("actualCity") or job.get("cityCategory"),
        "salary": fmt_salary(job),
        "salary_from": job.get("annualSalaryFrom"),
        "salary_to": job.get("annualSalaryTo"),
        "workplace": job.get("workplace"),
        "language": job.get("language"),
        "technologies": (job.get("filterTags") or [])[:8],
        "posted_at": job.get("postedAt"),
        "url": api.job_url(job.get("jobUrl", "")),
    }


def tool_search_jobs(
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
) -> dict[str, Any]:
    jobs = api.list_jobs()
    hits = [
        j
        for j in jobs
        if matches(
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
    hits.sort(key=lambda j: sort_key(j, by=sort))

    hidden = 0
    if not include_applied:
        before = len(hits)
        hits = [j for j in hits if not db.is_job_applied(j)]
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


def tool_get_job(job_id: str) -> dict[str, Any]:
    jobs = api.list_jobs()
    job = api.resolve_id(jobs, job_id)
    if not job:
        raise ValueError(f"No job matching {job_id!r}")
    detail = api.get_job(job["_id"])
    return apply_payload(
        detail,
        posting_url=api.job_url(detail.get("jobUrl", "")),
        applied=db.is_applied(detail["_id"]),
    )


def tool_apply_to_job(
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
    import os
    from pathlib import Path

    jobs = api.list_jobs()
    job = api.resolve_id(jobs, job_id)
    if not job:
        raise ValueError(f"No job matching {job_id!r}")

    detail = api.get_job(job["_id"])
    existing = db.is_applied(detail["_id"])
    if existing and not force:
        return {"already_applied": True, "application": existing}

    refusal = undeliverable(detail)
    if refusal and not force:
        return refusal

    name = name or os.environ.get("SDJ_NAME")
    email = email or os.environ.get("SDJ_EMAIL")
    cv_path = cv_path or os.environ.get("SDJ_CV") or ""
    missing = [
        label
        for label, value in (
            ("name/$SDJ_NAME", name),
            ("email/$SDJ_EMAIL", email),
            ("cv_path/$SDJ_CV", cv_path),
        )
        if not value
    ]
    if missing or not name or not email:
        return {"error": "missing_identity", "missing": missing}
    if not Path(cv_path).is_file():
        return {"error": "cv_not_found", "cv_path": cv_path}
    if "<" in motivation or ">" in motivation:
        return {
            "error": "invalid_motivation",
            "message": "The site rejects < and > in the motivation letter.",
        }

    # Irreversible: make the model surface it to a human before it happens.
    if not confirm:
        return {
            "error": "confirmation_required",
            "message": (
                "Submitting an application cannot be undone. Show the user the role, "
                "the salary, and the motivation letter, get their explicit approval, "
                "then call this tool again with confirm=true."
            ),
            "would_submit": {
                "role": detail.get("name"),
                "company": detail.get("company"),
                "location": detail.get("actualCity"),
                "salary": fmt_salary(detail),
                "applicant": {"name": name, "email": email},
                "cv_path": cv_path,
                "motivation_preview": motivation[:400],
                "motivation_chars": len(motivation),
            },
        }

    result = api.direct_apply(
        detail,
        name=name,
        email=email,
        motivation=motivation,
        cv_path=cv_path,
        is_from_europe=is_from_europe,
        lang_skills=lang_skills,
    )
    application = None
    if result["status"] == 200:
        application = db.mark_applied(
            job_id=detail["_id"],
            company=detail.get("company", ""),
            role=detail.get("name", ""),
            method="direct",
        )
    return {
        "submitted": result["status"] == 200,
        "http_status": result["status"],
        "response": result.get("response", "")[:500],
        "application": application,
    }


def tool_list_applications(limit: int = 100) -> dict[str, Any]:
    apps = db.list_applications(limit=limit)
    return {"count": len(apps), "applications": apps}


def tool_mark_applied(
    job_id: str, method: str, notes: str | None = None
) -> dict[str, Any]:
    jobs = api.list_jobs()
    job = api.resolve_id(jobs, job_id)
    if not job:
        raise ValueError(f"No job matching {job_id!r}")
    detail = api.get_job(job["_id"])
    return db.mark_applied(
        job_id=detail["_id"],
        company=detail.get("company", ""),
        role=detail.get("name", ""),
        method=method,
        notes=notes,
    )


def tool_top_technologies(limit: int = 25) -> dict[str, Any]:
    from collections import Counter

    counter: Counter[str] = Counter()
    for job in api.list_jobs():
        for tag in job.get("filterTags") or []:
            counter[tag] += 1
    return {
        "technologies": [
            {"name": n, "postings": c} for n, c in counter.most_common(limit)
        ]
    }


# --- tool registry ----------------------------------------------------------

_STR = {"type": "string"}
_INT = {"type": "integer"}
_BOOL = {"type": "boolean"}

TOOLS: list[dict[str, Any]] = [
    {
        "name": "search_jobs",
        "title": "Search Swiss dev jobs",
        "description": (
            "Search swissdevjobs.ch, where every posting must publish a salary range. "
            "Jobs already applied to are hidden unless include_applied is true. "
            "Returns compact rows; call get_job for the full posting."
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
            },
        },
        "annotations": {
            "title": "Search Swiss dev jobs",
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
                    "description": "must be true to actually submit; the user has to agree first",
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


def handle_request(message: dict[str, Any]) -> dict[str, Any] | None:
    """Route one JSON-RPC message. Returns None for notifications."""
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
                    "Search and apply to Swiss developer jobs. Every posting carries a "
                    "published salary range. Applying is irreversible: call apply_to_job "
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
        name = params.get("name")
        handler = HANDLERS.get(name)
        if handler is None:
            return _error(request_id, -32602, f"Unknown tool: {name}")
        try:
            return _result(
                request_id, _content(handler(**(params.get("arguments") or {})))
            )
        except api.CaptchaRequired as e:
            return _result(
                request_id,
                _content(
                    {
                        "error": "cloudflare_challenge",
                        "message": (
                            "swissdevjobs.ch returned a Cloudflare challenge. The user needs to "
                            f"run `sdj auth` in a terminal and clear it at {e.url}."
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

    if method in ("resources/list", "prompts/list"):
        return _result(request_id, {"resources": [], "prompts": []})

    if method == "ping":
        return _result(request_id, {})

    return _error(request_id, -32601, f"Method not found: {method}")


def _version() -> str:
    from . import __version__

    return __version__


def serve(stdin=None, stdout=None) -> int:
    """Read line-delimited JSON-RPC from stdin, answer on stdout."""
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
    _log(f"v{_version()} ready — {len(TOOLS)} tools over stdio")

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

        response = handle_request(message)
        if response is not None:
            print(json.dumps(response, ensure_ascii=False), file=stdout, flush=True)

    _log("stdin closed, shutting down")
    return 0


def main(argv: list[str] | None = None) -> int:
    try:
        return serve()
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
