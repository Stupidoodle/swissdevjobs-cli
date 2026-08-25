"""Command-line interface for swissdevjobs.ch."""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import sys
import textwrap
import webbrowser

from swissdevjobs_cli import bootstrap
from swissdevjobs_cli.adapters import envfile
from swissdevjobs_cli.adapters.boards import registry
from swissdevjobs_cli.adapters.http.client import CaptchaRequired, store_clearance
from swissdevjobs_cli.domain.model.application import Applicant
from swissdevjobs_cli.domain.model.job import Job, strip_html
from swissdevjobs_cli.dto.application import as_dict_or_none
from swissdevjobs_cli.dto.board import BoardDTO
from swissdevjobs_cli.dto.job import JobDetailDTO, JobSummaryDTO
from swissdevjobs_cli.service_layer import apply as apply_service
from swissdevjobs_cli.service_layer import config as config_service
from swissdevjobs_cli.service_layer import search, tracking

# --- Cloudflare challenge UX ------------------------------------------------
# The boards sit behind Cloudflare; a headless client can't solve the JS
# challenge, so the documented UX is: pause, open the URL in the user's
# browser, let them solve it, and paste the cf_clearance cookie back here.


def interactive_unblock(challenge_url: str) -> bool:
    """Block the CLI, open the URL in a browser, prompt for the cf_clearance cookie.

    Returns True once the cookie is stored so callers may retry; False if
    aborted. Designed to be safely called from any command — it is a
    synchronous gate. The cookie domain is derived from the challenged URL,
    so this works for any board of the family.
    """
    host = challenge_url.split("//", 1)[-1].split("/", 1)[0]
    print("", file=sys.stderr)
    print("Cloudflare challenge detected.", file=sys.stderr)
    print(f"Opening {challenge_url} in your default browser.", file=sys.stderr)
    print(
        "Solve the challenge, then in DevTools → Application → Cookies copy the\n"
        f"value of 'cf_clearance' (on .{host}) and paste it below.\n"
        "Press Enter with empty input to abort.",
        file=sys.stderr,
    )
    with contextlib.suppress(Exception):
        webbrowser.open(challenge_url, new=2)
    try:
        value = input("cf_clearance cookie value: ").strip()
    except (EOFError, KeyboardInterrupt):
        return False
    if not value:
        return False
    from swissdevjobs_cli.adapters import paths

    store_clearance(paths.COOKIE_FILE, value, f".{host}")
    print("Saved. Retrying request…", file=sys.stderr)
    return True


def with_retry(runtime: bootstrap.Runtime, fn, *args, **kwargs):
    """Run `fn`; if it raises CaptchaRequired, prompt the user and retry once."""
    try:
        return fn(*args, **kwargs)
    except CaptchaRequired as e:
        if interactive_unblock(e.url):
            return fn(*args, **kwargs)
        raise


# --- commands ---------------------------------------------------------------


def _print_row(j: Job) -> None:
    raw = j.raw
    tags = ", ".join((raw.get("filterTags") or [])[:6])
    posted = (raw.get("postedAt") or "")[:10]  # immutable, decoded from _id
    active = (raw.get("activeFrom") or "")[:10]  # bumped when SDJ re-promotes
    # If both are present, show "posted/active" — otherwise just whichever exists.
    if posted and active and posted != active:
        date_col = f"p={posted} a={active}"
    elif posted:
        date_col = f"p={posted}"
    elif active:
        date_col = f"a={active}"
    else:
        date_col = ""
    line = (
        f"{raw['_id']}  "
        f"{j.board.source[:14]:14}  "
        f"{date_col:24}  "
        f"{(raw.get('name') or '')[:48]:48}  "
        f"{(raw.get('company') or '')[:25]:25}  "
        f"{(raw.get('actualCity') or raw.get('cityCategory') or '')[:12]:12}  "
        f"{j.salary.format():22}  "
        f"{(raw.get('workplace') or '')[:7]:7}  "
        f"{tags}"
    )
    print(line)


def _window(filtered: list, args: argparse.Namespace, total: int):
    """Windowing: --limit (hard cap) wins; otherwise --page / --per-page paginate."""
    page_info = None
    if args.limit and args.limit > 0:
        return filtered[: args.limit], page_info
    if args.per_page and args.per_page > 0 and args.page and args.page >= 1:
        per = args.per_page
        page = args.page
        total_pages = max(1, (total + per - 1) // per)
        # Only window if explicitly paged (page > 1) OR total exceeds one page AND user
        # asked for a page. With default page=1, only window when there's overflow AND
        # a non-default per-page value. Otherwise return all.
        if page > 1 or (args.per_page != 50 and total > per):
            start = (page - 1) * per
            filtered = filtered[start : start + per]
            page_info = (page, total_pages, per)
    return filtered, page_info


def _raw_list_payload(filtered: list, counts: dict, page_info):
    """The pre-0.6 --json shape, byte for byte: full raw wire rows.

    A flat list unless pagination was requested — kept as the --raw escape
    hatch so existing scripts migrate by adding one flag.
    """
    rows = [dict(j.raw) for j in filtered]
    if not page_info:
        return rows
    page, total_pages, per = page_info
    return {
        **counts,
        "page": page,
        "per_page": per,
        "total_pages": total_pages,
        "jobs": rows,
    }


def _summary_list_payload(
    args: argparse.Namespace,
    runtime: bootstrap.Runtime,
    boards: list,
    excluded: dict,
    filtered: list,
    counts: dict,
    page_info,
) -> dict:
    """The 0.6 --json envelope: compact summary rows plus coverage steering."""
    payload = {
        **counts,
        "returned": len(filtered),
        "boards_searched": [b.board.source for b in boards],
    }
    if excluded:
        payload["boards_excluded"] = excluded
    note = search.coverage_note(
        boards, excluded, query=args.query, category=args.category, tech=args.tech
    )
    if note:
        payload["note"] = note
    if page_info:
        page, total_pages, per = page_info
        payload["page"] = page
        payload["per_page"] = per
        payload["total_pages"] = total_pages
    payload["jobs"] = [
        JobSummaryDTO.from_domain(j, runtime.board_for(j).posting_url(j.raw)).as_dict()
        for j in filtered
    ]
    return payload


def cmd_list(args: argparse.Namespace, runtime: bootstrap.Runtime) -> int:
    """Search, filter, sort, and print the feed."""
    uow = runtime.uow
    remote = True if args.remote else (False if args.onsite else None)
    visa = True if args.visa else None
    boards = (
        [
            runtime.boards[s]
            for s in registry.resolve_selectors(args.country)
            if s in runtime.boards
        ]
        if args.country
        else runtime.enabled_boards()
    )
    boards, excluded = search.split_by_filterability(
        boards,
        search.requested_filters(
            tech=args.tech,
            remote=remote,
            visa=visa,
            level=args.level,
            min_salary=args.min_salary,
            max_salary=args.max_salary,
            contract=args.contract,
            workload=args.workload,
        ),
    )
    jobs = with_retry(
        runtime,
        search.list_jobs,
        uow,
        boards,
        query=args.query,
        category=args.category,
        tech=args.tech,
        contract=args.contract,
        workload=args.workload,
        force=args.refresh,
    )
    filtered = [
        j
        for j in jobs
        if search.matches(
            j,
            tech=search.tech_for(j, args.tech),
            tech_any=not args.tech_all,
            location=args.location,
            remote=remote,
            visa=visa,
            level=args.level,
            min_salary=args.min_salary,
            max_salary=args.max_salary,
            language=args.language,
            query=search.query_for(j, args.query),
            company=args.company,
            contract=args.contract,
            workload=args.workload,
        )
    ]
    filtered.sort(key=lambda j: search.sort_key(j, by=args.sort))

    # Always hide jobs already applied to, unless explicitly overridden.
    hide_count = 0
    if not args.include_applied:
        before = len(filtered)
        filtered = [j for j in filtered if not tracking.is_job_applied(uow, j)]
        hide_count = before - len(filtered)

    total_after_filters = len(filtered)
    # --limit semantics: unset means "no cap" for the table and --raw (the
    # pre-0.6 behavior) but 50 for --json summaries; 0 is always "no cap".
    # An explicit --page/--per-page request must keep paginating: a default
    # cap would win over the window in _window() and swallow page 2.
    if args.limit is None:
        wants_pages = args.page != 1 or args.per_page != 50
        args.limit = 50 if (args.json and not args.raw and not wants_pages) else 0
    filtered, page_info = _window(filtered, args, total_after_filters)

    if args.json:
        counts = {
            "total_in_feed": len(jobs),
            "total_after_filters": total_after_filters,
            "hidden_already_applied": hide_count,
        }
        if args.raw:
            payload = _raw_list_payload(filtered, counts, page_info)
        else:
            payload = _summary_list_payload(
                args, runtime, boards, excluded, filtered, counts, page_info
            )
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0

    note = search.coverage_note(
        boards, excluded, query=args.query, category=args.category, tech=args.tech
    )
    if note:
        print(f"note: {note}", file=sys.stderr)
    if not filtered:
        print("No matching jobs.", file=sys.stderr)
        return 1

    header = (
        f"{len(filtered)} shown · {total_after_filters} match filters · "
        f"{len(jobs)} in feed"
    )
    if hide_count:
        header += f" · {hide_count} hidden (already applied)"
    if page_info:
        page, total_pages, per = page_info
        header += f" · page {page}/{total_pages} (per_page={per})"
    print(header)
    print("-" * 160)
    for j in filtered:
        _print_row(j)
    return 0


def cmd_show(args: argparse.Namespace, runtime: bootstrap.Runtime) -> int:
    """Print one posting in full."""
    uow = runtime.uow
    jobs = with_retry(runtime, search.resolve_jobs, uow, runtime.enabled_boards())
    job = search.resolve(jobs, args.id)
    if not job:
        print(f"No job matching {args.id!r}", file=sys.stderr)
        return 1
    board = runtime.board_for(job)
    detail = with_retry(
        runtime, search.get_detail, uow, board, str(job.id), force=args.refresh
    )
    raw = detail.raw

    if args.json:
        print(json.dumps(dict(raw), indent=2, ensure_ascii=False))
        return 0

    print(f"# {raw.get('name')}  @  {raw.get('company')}")
    print(
        f"Location:   {raw.get('actualCity')} ({raw.get('cityCategory')})  "
        f"workplace={raw.get('workplace')}  visa={raw.get('hasVisaSponsorship')}"
    )
    print(
        f"Level:      {raw.get('expLevel')}   Language: {raw.get('language')}   "
        f"Type: {raw.get('jobType')}"
    )
    print(f"Salary:     {detail.salary.format()}")
    print(f"Tech:       {', '.join(raw.get('technologies') or [])}")
    print(f"URL:        {board.posting_url(raw)}")
    print(
        f"Contact:    {raw.get('candidateContactWay')}  "
        f"{raw.get('emailAddressForApplications') or raw.get('redirectJobUrl') or ''}"
    )
    print()
    for label, key in (
        ("Description", "description"),
        ("Responsibilities", "responsibilitiesTextArea"),
        ("Must-have", "requirementsMustTextArea"),
        ("Nice-to-have", "requirementsNiceTextArea"),
    ):
        val = raw.get(key)
        if val:
            print(f"## {label}")
            print(textwrap.indent(strip_html(val), "  "))
            print()
    return 0


def cmd_open(args: argparse.Namespace, runtime: bootstrap.Runtime) -> int:
    """Open a posting in the default browser."""
    jobs = with_retry(
        runtime, search.resolve_jobs, runtime.uow, runtime.enabled_boards()
    )
    job = search.resolve(jobs, args.id)
    if not job:
        print(f"No job matching {args.id!r}", file=sys.stderr)
        return 1
    url = runtime.board_for(job).posting_url(job.raw)
    print(url)
    webbrowser.open(url, new=2)
    return 0


def _complete_application(args, runtime, detail, existing) -> int:
    """Handle `apply --complete <method>`: record without submitting anything."""
    raw = detail.raw
    if existing:
        app = existing.as_dict()
    else:
        app = tracking.mark_applied(
            runtime.uow,
            job_id=str(detail.id),
            company=raw.get("company", ""),
            role=raw.get("name", ""),
            method=args.complete,
            notes=args.notes,
        ).as_dict()
    if args.json:
        payload = {
            "marked": True,
            "application": app,
            "job_id": str(detail.id),
            "company": raw.get("company"),
            "title": raw.get("name"),
        }
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0
    print(f"Marked as applied via {args.complete}")
    return 0


def cmd_apply(args: argparse.Namespace, runtime: bootstrap.Runtime) -> int:
    """Surface the application mechanism so an agent (or human) can act on it.

    Three modes you'll see in the wild:
      1. candidateContactWay == "Email": apply by email; the address is in
         emailAddressForApplications
      2. candidateContactWay == "CompanyWebsite": redirectJobUrl points to a third-party
         ATS (Recruitee, Workday, Greenhouse, Lever, SmartRecruiters, etc.). An agent
         should open that URL with chrome-mcp and fill the form manually.
      3. applyQuestions: non-empty → the site has custom screening questions; an
         agent should answer them (on-site form or via email as a structured reply).

    With --complete <method>, marks the job as applied (for email/browser modes).
    """
    uow = runtime.uow
    jobs = with_retry(runtime, search.resolve_jobs, uow, runtime.enabled_boards())
    job = search.resolve(jobs, args.id)
    if not job:
        print(f"No job matching {args.id!r}", file=sys.stderr)
        return 1
    board = runtime.board_for(job)
    detail = with_retry(runtime, search.get_detail, uow, board, str(job.id))
    raw = detail.raw

    posting_url = board.posting_url(raw)
    existing = tracking.existing_application(uow, str(detail.id))

    # If --complete flag is set, mark as applied
    if args.complete:
        return _complete_application(args, runtime, detail, existing)

    payload = JobDetailDTO.from_domain(
        detail, posting_url=posting_url, applied=as_dict_or_none(existing)
    ).as_dict()
    email = payload["apply_email"]
    redirect = payload["apply_url"]
    fallback = payload["fallback_mode"]
    questions = payload["questions"]

    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0

    print(f"Apply mode: {payload['mode'].upper()}  (fallback: {fallback.upper()})")
    if existing:
        print(
            f"STATUS:     Already applied on {existing.applied_at} "
            f"via {existing.method}"
        )
    print(f"Posting:    {posting_url}")
    print(
        f"Role:       {payload['title']} @ {payload['company']} ({payload['location']})"
    )
    print(f"Salary:     {payload['salary']}   Language: {payload['language']}")
    print(
        f"Workflow:   sdj direct-apply {detail.id} "
        "--cv <cv.pdf> --motivation <text|path>"
    )
    if fallback == "email":
        print(f"Fallback:   email to {email}")
    elif fallback == "browser":
        print(f"Fallback:   ATS at {redirect}")
        if args.open:
            webbrowser.open(redirect, new=2)
    if questions:
        print("\nScreening questions:")
        for i, q in enumerate(questions, 1):
            text = q.get("question") if isinstance(q, dict) else str(q)
            print(f"  {i}. {text}")
    return 0


def cmd_boards(args: argparse.Namespace, runtime: bootstrap.Runtime) -> int:
    """List every known board with its capabilities and enabled state."""
    rows = [
        BoardDTO.from_domain(
            b,
            categories=registry.categories_for(source),
            contracts=registry.contracts_for(source),
            enabled=source in runtime.enabled,
        ).as_dict()
        for source, b in registry.BOARDS.items()
    ]
    if args.json:
        print(json.dumps({"boards": rows}, indent=2, ensure_ascii=False))
        return 0

    print(
        f"{len(rows)} boards — select with --board <id|country>, "
        "persist with `sdj config --boards`"
    )
    print("-" * 100)
    for r in rows:
        traits = [
            r["scope"],
            "salary" if r["salary_published"] else "no-salary",
        ]
        if r["search_driven"]:
            traits.append("search-driven")
        if not r["native_apply"]:
            traits.append("no-native-apply")
        if r["filters_unavailable"]:
            traits.append("unfilterable: " + ", ".join(r["filters_unavailable"]))
        if r["categories"]:
            traits.append("categories: " + ", ".join(r["categories"]))
        line = (
            f"{r['source']:15}  {r['country']:3}  {r['name'][:18]:18}  "
            f"{r['currency']:3}  {'enabled' if r['enabled'] else '       '}  "
            f"{' · '.join(traits)}"
        )
        print(line)
    return 0


def cmd_tech(args: argparse.Namespace, runtime: bootstrap.Runtime) -> int:
    """Print the most-tagged technologies across the feed.

    Feed boards only: search-driven boards rarely tag technologies, and
    counting a query slice would skew the totals anyway.
    """
    boards = [b for b in runtime.enabled_boards() if not b.board.search_driven]
    jobs = with_retry(runtime, search.list_jobs, runtime.uow, boards)
    top = search.top_technologies(jobs, args.limit)
    if args.json:
        print(json.dumps(top, indent=2))
        return 0
    for name, n in top:
        print(f"{n:4d}  {name}")
    return 0


def cmd_auth(args: argparse.Namespace, runtime: bootstrap.Runtime) -> int:
    """Proactively open a board so the user can clear a Cloudflare challenge."""
    source = registry.resolve_selectors([args.country])[0]
    board = runtime.boards[source].board
    ok = interactive_unblock(board.base_url + "/")
    return 0 if ok else 1


def cmd_applications(args: argparse.Namespace, runtime: bootstrap.Runtime) -> int:
    """List all tracked applications."""
    apps = [r.as_dict() for r in tracking.list_applications(runtime.uow, args.limit)]

    if args.json:
        print(json.dumps(apps, indent=2, ensure_ascii=False))
        return 0

    if not apps:
        print("No applications tracked yet.")
        return 0

    print(f"{len(apps)} application(s)")
    print("-" * 120)
    for a in apps:
        line = (
            f"{a['id']:4d}  "
            f"{(a['company'] or '')[:28]:28}  "
            f"{(a['role'] or '')[:40]:40}  "
            f"{(a['method'] or '')[:8]:8}  "
            f"{(a['status'] or '')[:10]:10}  "
            f"{(a['applied_at'] or '')[:10]}"
        )
        print(line)
    return 0


def cmd_stats(args: argparse.Namespace, runtime: bootstrap.Runtime) -> int:
    """Show database statistics."""
    stats = tracking.stats(runtime.uow)

    if args.json:
        print(json.dumps(stats, indent=2))
        return 0

    print(
        f"Jobs cached:     {stats['jobs_cached']} (light), "
        f"{stats['jobs_with_detail']} (detail)"
    )
    print(
        f"Applications:    {stats['applications_total']} total "
        f"({stats['applications_submitted']} submitted)"
    )
    print(f"Database:        {stats['db_path']}")
    return 0


def _resolve_identity(args) -> Applicant | None:
    """Applicant identity from flags/env, with the historic CLI error text."""
    resolved = config_service.resolve_applicant(
        args.name,
        args.email,
        args.cv,
        labels=("--name/$SDJ_NAME", "--email/$SDJ_EMAIL", "--cv/$SDJ_CV"),
    )
    if isinstance(resolved, list):
        print(
            f"Error: missing {', '.join(resolved)}.\n"
            "       Run `sdj config --init` to create "
            f"{envfile.config_dir() / '.env'},\n"
            f"       then fill in your details there.",
            file=sys.stderr,
        )
        return None
    if not os.path.isfile(resolved.cv_path):
        print(f"Error: CV not found: {resolved.cv_path}", file=sys.stderr)
        return None
    return resolved


def _resolve_motivation(value: str) -> str | None:
    """The --motivation argument: inline text, or a path to read. None = error."""
    motivation = value.strip()
    # If it looks like a file path and the file exists, read it
    if motivation and os.path.exists(motivation):
        with open(motivation, encoding="utf-8") as fh:
            motivation = fh.read().strip()
    if not motivation:
        print("Error: --motivation TEXT_OR_PATH is required", file=sys.stderr)
        return None

    # Validate no HTML in motivation (site rejects < and >)
    if apply_service.validate_motivation(motivation):
        print(
            "Error: motivation letter must not contain < or > characters",
            file=sys.stderr,
        )
        return None
    return motivation


def _direct_apply_preflight(args, runtime, job):
    """Dedup + deliverability checks. Returns the detail, or an exit code."""
    uow, board = runtime.uow, runtime.board_for(job)

    # Check for existing application (dedup as data, not error)
    existing = tracking.existing_application(uow, str(job.id))
    if existing and not args.force:
        if args.json:
            print(
                json.dumps(
                    {"already_applied": True, "application": existing.as_dict()},
                    indent=2,
                )
            )
            return 0  # Success exit - agent handles this
        print(f"Already applied on {existing.applied_at} via {existing.method}")
        print("Use --force to apply again.")
        return 1

    detail = with_retry(runtime, search.get_detail, uow, board, str(job.id))

    # Non-deliverable detection: the native POST only reaches the company when
    # the board holds a real forwarding channel. Aggregator syndication and
    # CompanyWebsite postings silently black-hole (HTTP 200, nothing sent), so
    # refuse and route the agent to chrome MCP on the real ATS URL instead.
    refusal = apply_service.undeliverable(detail)
    if refusal and not args.force:
        if args.json:
            print(json.dumps(refusal, indent=2))
        else:
            url = refusal["apply_url"] or "(no redirect URL — open the posting page)"
            print(
                f"Apply in a browser — drive the form at:\n"
                f"  {url}\n"
                f"({refusal['message']})",
                file=sys.stderr,
            )
        return 2
    return detail


def cmd_direct_apply(args: argparse.Namespace, runtime: bootstrap.Runtime) -> int:
    """Submit an application directly via the board's native form (POST /api/jobApply).

    This bypasses external ATS systems and email — the application is sent
    through the board's own form, which forwards it to the company.

    Honeypot fields (yearsOfExperience, personal_website_url, address,
    required_confirmation) are intentionally left empty.

    Auto-marks job as applied on success. Returns {"already_applied": true} if
    already applied (use --force to override).
    """
    uow = runtime.uow

    resolved = _resolve_identity(args)
    if resolved is None:
        return 1

    jobs = with_retry(runtime, search.resolve_jobs, uow, runtime.enabled_boards())
    job = search.resolve(jobs, args.id)
    if not job:
        print(f"No job matching {args.id!r}", file=sys.stderr)
        return 1

    preflight = _direct_apply_preflight(args, runtime, job)
    if isinstance(preflight, int):
        return preflight
    detail = preflight
    raw = detail.raw

    motivation = _resolve_motivation(args.motivation)
    if motivation is None:
        return 1

    applicant = Applicant(
        name=resolved.name,
        email=resolved.email,
        cv_path=resolved.cv_path,
        is_from_europe=not args.not_eu,
        lang_skills=args.lang_skills,
    )

    board = runtime.board_for(job)
    if not args.json:
        print(f"Submitting direct application to {board.board.name}...")
        print(
            f"  Role:    {raw.get('name')} @ {raw.get('company')} "
            f"({raw.get('actualCity')})"
        )
        print(f"  Salary:  {detail.salary.format()}")
        print(f"  CV:      {applicant.cv_path}")
        print(f"  Name:    {applicant.name}")
        print(f"  Email:   {applicant.email}")
        print()

    result, application = with_retry(
        runtime,
        apply_service.submit_and_track,
        uow,
        board,
        detail,
        applicant,
        motivation,
    )

    if args.json:
        result = dict(result)
        result["application"] = as_dict_or_none(application)
        print(json.dumps(result, indent=2))
    else:
        print(f"✓ Submitted — HTTP {result['status']}")
        resp = result.get("response", "")
        if resp:
            print(f"  Response: {resp[:200]}")
        if application:
            print(f"  Marked as applied (id: {application.id})")
    return 0


def cmd_config(args: argparse.Namespace, runtime: bootstrap.Runtime) -> int:
    """Show the resolved configuration, or scaffold a .env file."""
    if args.countries:
        value = args.countries.strip().lower()
        codes = [c.strip() for c in value.split(",")]
        known = registry.known_selectors()
        unknown = [c for c in codes if c != "all" and c not in known]
        if unknown:
            print(
                f"Error: unknown board selector(s): {', '.join(unknown)}. "
                f"Known: {', '.join(known)} or 'all'.",
                file=sys.stderr,
            )
            return 1
        path = envfile.set_value("SDJ_BOARDS", value)
        print(f"Wrote SDJ_BOARDS={value} to {path}")
        return 0

    if args.init:
        try:
            path = envfile.write_template()
        except FileExistsError as e:
            print(f"{e.args[0]} already exists — edit it directly.", file=sys.stderr)
            return 1
        print(f"Wrote {path}")
        print("Fill in SDJ_NAME and SDJ_EMAIL, then run `sdj config` to verify.")
        return 0

    locations = bootstrap.resolved_paths()
    resolved = config_service.resolved_config(
        locations["env_files_loaded"],
        cache_dir=locations["cache_dir"],
        config_dir=locations["config_dir"],
        cookie_file=locations["cookie_file"],
        db_path=locations["db_path"],
    )
    # "countries" predates board ids and stays for output compatibility.
    resolved["boards"] = runtime.enabled
    resolved["countries"] = runtime.enabled

    if args.json:
        print(json.dumps(resolved, indent=2))
        return 0

    print("Applicant identity")
    print(f"  SDJ_NAME     {resolved['name'] or '(unset)'}")
    print(f"  SDJ_EMAIL    {resolved['email'] or '(unset)'}")
    print(f"  SDJ_CV       {resolved['cv'] or '(unset)'}")
    print()
    print("Boards")
    print(f"  enabled      {', '.join(resolved['boards'])}")
    print("  change with  sdj config --boards jobsch,de  (or 'all')")
    print()
    print("Paths")
    print(f"  cache dir    {resolved['cache_dir']}")
    print(f"  config dir   {resolved['config_dir']}")
    print(f"  cookie jar   {resolved['cookie_file']}")
    print(f"  database     {resolved['database']}")
    print()
    if resolved["env_files_loaded"]:
        print(".env files loaded")
        for path in resolved["env_files_loaded"]:
            print(f"  {path}")
    else:
        print("No .env file found. Run `sdj config --init` to create one.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    """The full argparse tree; kept in one place so --help shows everything."""
    n_boards = len(registry.BOARDS)
    n_countries = len({b.country for b in registry.BOARDS.values()})
    p = argparse.ArgumentParser(
        prog="swissdevjobs",
        description=f"Job search CLI — {n_boards} boards, {n_countries} "
        "countries: the devitjobs family (all-IT, salary published) plus "
        "jobs.ch and jobup.ch (all industries).",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    lp = sub.add_parser("list", help="Search & list jobs")
    lp.add_argument("query", nargs="?", help="free-text search")
    lp.add_argument(
        "--tech",
        action="append",
        default=[],
        help="repeatable, e.g. --tech Python --tech Kubernetes",
    )
    lp.add_argument(
        "--tech-all", action="store_true", help="require ALL --tech tags (default any)"
    )
    lp.add_argument(
        "--board",
        "--source",
        "--country",
        dest="country",
        action="append",
        choices=registry.known_selectors(),
        help="repeatable board selector — a board id picks one board "
        "('jobsch'), a country code every board there ('ch' = swissdevjobs "
        "+ jobs.ch + jobup.ch). Default: the boards enabled via SDJ_BOARDS",
    )
    lp.add_argument(
        "--category",
        choices=registry.known_categories(),
        help="narrow all-industry boards to one category (all-IT boards "
        "ignore it; see `sdj boards`)",
    )
    lp.add_argument("--location", help="city substring, e.g. Zurich")
    lp.add_argument("--remote", action="store_true", help="remote or hybrid only")
    lp.add_argument("--onsite", action="store_true", help="exclude remote")
    lp.add_argument("--visa", action="store_true", help="visa sponsorship only")
    lp.add_argument(
        "--level", choices=["Junior", "Regular", "Senior", "Principal", "CLevel"]
    )
    lp.add_argument("--language", help="e.g. English, German")
    lp.add_argument("--company")
    lp.add_argument(
        "--contract",
        choices=registry.known_contracts(),
        help="contract type; boards map their own taxonomy onto these aliases",
    )
    lp.add_argument(
        "--workload",
        type=int,
        metavar="PCT",
        help="workload percent the posting must offer, e.g. 80",
    )
    lp.add_argument("--min-salary", type=int)
    lp.add_argument("--max-salary", type=int)
    lp.add_argument(
        "--sort",
        choices=["salary", "date", "posted", "company"],
        default="posted",
        help="salary=highest, date=newest activeFrom (re-bump-aware), "
        "posted=true creation time from ObjectId, company=A-Z. Default: posted.",
    )
    lp.add_argument(
        "--limit",
        type=int,
        default=None,
        help="cap output length; 0 = no cap. Default: no cap for the table "
        "and --raw, 50 for --json. Use --page/--per-page for windowed views.",
    )
    lp.add_argument(
        "--page",
        type=int,
        default=1,
        help="1-indexed page number. Combine with --per-page (default page size 50).",
    )
    lp.add_argument(
        "--per-page",
        type=int,
        default=50,
        help="page size when --page is used (default 50).",
    )
    lp.add_argument(
        "--json",
        action="store_true",
        help="summary rows in an envelope (capped at 50 unless --limit given)",
    )
    lp.add_argument(
        "--raw",
        action="store_true",
        help="with --json: full raw wire rows in the pre-0.6 shape "
        "(~470 tokens per row — cap with --limit)",
    )
    lp.add_argument("--refresh", action="store_true", help="bypass cache")
    lp.add_argument(
        "--include-applied",
        action="store_true",
        help="show jobs you've already applied to (hidden by default)",
    )
    lp.set_defaults(func=cmd_list)

    sp = sub.add_parser("show", help="Show full job details")
    sp.add_argument("id", help="job _id, jobUrl slug, or substring")
    sp.add_argument("--json", action="store_true")
    sp.add_argument("--refresh", action="store_true")
    sp.set_defaults(func=cmd_show)

    op = sub.add_parser("open", help="Open job page in your browser")
    op.add_argument("id")
    op.set_defaults(func=cmd_open)

    bp = sub.add_parser("boards", help="List every board and its capabilities")
    bp.add_argument("--json", action="store_true")
    bp.set_defaults(func=cmd_boards)

    tp = sub.add_parser("tech", help="Top technology tags across current listings")
    tp.add_argument("--limit", type=int, default=40)
    tp.add_argument("--json", action="store_true")
    tp.set_defaults(func=cmd_tech)

    apl = sub.add_parser(
        "apply", help="Surface apply mechanism (email / ATS URL / questions)"
    )
    apl.add_argument("id")
    apl.add_argument("--json", action="store_true")
    apl.add_argument(
        "--open", action="store_true", help="also open the apply URL in a browser"
    )
    apl.add_argument(
        "--complete",
        choices=["email", "browser", "linkedin"],
        help="mark job as applied via this method",
    )
    apl.add_argument(
        "--notes", default=None, help="notes to store with the application"
    )
    apl.set_defaults(func=cmd_apply)

    ap = sub.add_parser("auth", help="Open a board to resolve a Cloudflare challenge")
    ap.add_argument(
        "--board",
        "--source",
        "--country",
        dest="country",
        default="ch",
        choices=registry.known_selectors(),
        help="which board to open (default: ch)",
    )
    ap.set_defaults(func=cmd_auth)

    da = sub.add_parser(
        "direct-apply",
        help="Submit via SwissDevJobs native form (POST /api/jobApply)",
    )
    da.add_argument("id", help="job _id, jobUrl slug, or substring")
    da.add_argument(
        "--name",
        default=os.environ.get("SDJ_NAME"),
        help="Applicant full name (default: $SDJ_NAME)",
    )
    da.add_argument(
        "--email",
        default=os.environ.get("SDJ_EMAIL"),
        help="Applicant email address (default: $SDJ_EMAIL)",
    )
    da.add_argument(
        "--cv",
        default=os.environ.get("SDJ_CV"),
        help="Path to a PDF CV (default: $SDJ_CV)",
    )
    da.add_argument(
        "--motivation", default="", help="Cover letter text or path to a .txt file"
    )
    da.add_argument(
        "--not-eu", action="store_true", help="Set isFromEurope=No (default: Yes)"
    )
    da.add_argument(
        "--lang-skills",
        default="native",
        choices=["native", "fluent", "good", "basic"],
        help="Self-rated language skill in the posting's language (default: native). "
        "Only sent when the posting has hasLangCheck=true.",
    )
    da.add_argument("--json", action="store_true")
    da.add_argument(
        "--force", action="store_true", help="apply even if already marked as applied"
    )
    da.set_defaults(func=cmd_direct_apply)

    # applications command
    apps = sub.add_parser("applications", help="List tracked applications")
    apps.add_argument("--limit", type=int, default=100)
    apps.add_argument("--json", action="store_true")
    apps.set_defaults(func=cmd_applications)

    cf = sub.add_parser("config", help="Show resolved config / create a .env")
    cf.add_argument(
        "--init",
        action="store_true",
        help="write a starter .env to the config directory",
    )
    cf.add_argument(
        "--boards",
        "--sources",
        "--countries",
        dest="countries",
        metavar="LIST",
        help="persist which boards to search — board ids and/or country "
        "codes, e.g. 'jobsch', 'ch,de', or 'all' (writes SDJ_BOARDS to the "
        "config .env)",
    )
    cf.add_argument("--json", action="store_true")
    cf.set_defaults(func=cmd_config)

    # stats command
    st = sub.add_parser("stats", help="Show database statistics")
    st.add_argument("--json", action="store_true")
    st.set_defaults(func=cmd_stats)

    return p


def main(argv: list[str] | None = None) -> int:
    """Console-script entry point."""
    parser = build_parser()
    args = parser.parse_args(argv)
    runtime = bootstrap.build_runtime()
    try:
        return args.func(args, runtime)
    except CaptchaRequired as e:
        print(f"Cloudflare challenge unresolved: {e}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
