"""Command-line interface for swissdevjobs.ch."""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import textwrap
import webbrowser
from typing import Any

from . import api
from .captcha import with_retry
from .filter import matches, sort_key


def _strip_html(s: str) -> str:
    s = re.sub(r"<br\s*/?>", "\n", s, flags=re.I)
    s = re.sub(r"</p>", "\n\n", s, flags=re.I)
    s = re.sub(r"<[^>]+>", "", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


def _fmt_salary(j: dict[str, Any]) -> str:
    a, b = j.get("annualSalaryFrom"), j.get("annualSalaryTo")
    if a and b:
        return f"CHF {a:,}–{b:,}".replace(",", "'")
    if a:
        return f"CHF {a:,}+".replace(",", "'")
    return "—"


def _print_row(j: dict[str, Any]) -> None:
    tags = ", ".join((j.get("filterTags") or [])[:6])
    posted = (j.get("postedAt") or "")[:10]  # immutable, decoded from _id
    active = (j.get("activeFrom") or "")[:10]  # bumped when SDJ re-promotes
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
        f"{j['_id']}  "
        f"{date_col:24}  "
        f"{(j.get('name') or '')[:48]:48}  "
        f"{(j.get('company') or '')[:25]:25}  "
        f"{(j.get('actualCity') or j.get('cityCategory') or '')[:12]:12}  "
        f"{_fmt_salary(j):22}  "
        f"{(j.get('workplace') or '')[:7]:7}  "
        f"{tags}"
    )
    print(line)


def cmd_list(args: argparse.Namespace) -> int:
    from . import db

    jobs = with_retry(api.list_jobs, force=args.refresh)
    filtered = [
        j for j in jobs
        if matches(
            j,
            tech=args.tech,
            tech_any=not args.tech_all,
            location=args.location,
            remote=(True if args.remote else (False if args.onsite else None)),
            visa=(True if args.visa else None),
            level=args.level,
            min_salary=args.min_salary,
            max_salary=args.max_salary,
            language=args.language,
            query=args.query,
            company=args.company,
        )
    ]
    filtered.sort(key=lambda j: sort_key(j, by=args.sort))

    # Always hide jobs already applied to, unless explicitly overridden.
    hide_count = 0
    if not args.include_applied:
        before = len(filtered)
        filtered = [j for j in filtered if not db.is_job_applied(j)]
        hide_count = before - len(filtered)

    total_after_filters = len(filtered)

    # Apply windowing: --limit (hard cap) wins; otherwise --page / --per-page paginate.
    page_info = None
    if args.limit and args.limit > 0:
        filtered = filtered[: args.limit]
    elif args.per_page and args.per_page > 0 and args.page and args.page >= 1:
        per = args.per_page
        page = args.page
        total_pages = max(1, (total_after_filters + per - 1) // per)
        # Only window if explicitly paged (page > 1) OR total exceeds one page AND user
        # asked for a page. With default page=1, only window when there's overflow AND
        # a non-default per-page value. Otherwise return all.
        if page > 1 or (args.per_page != 50 and total_after_filters > per):
            start = (page - 1) * per
            filtered = filtered[start : start + per]
            page_info = (page, total_pages, per)

    if args.json:
        if page_info:
            page, total_pages, per = page_info
            print(json.dumps({
                "total_in_feed": len(jobs),
                "total_after_filters": total_after_filters,
                "hidden_already_applied": hide_count,
                "page": page,
                "per_page": per,
                "total_pages": total_pages,
                "jobs": filtered,
            }, indent=2, ensure_ascii=False))
        else:
            # Backward-compatible flat list when no pagination requested.
            print(json.dumps(filtered, indent=2, ensure_ascii=False))
        return 0

    if not filtered:
        print("No matching jobs.", file=sys.stderr)
        return 1

    header = f"{len(filtered)} shown · {total_after_filters} match filters · {len(jobs)} in feed"
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


def cmd_show(args: argparse.Namespace) -> int:
    jobs = with_retry(api.list_jobs)
    job = api.resolve_id(jobs, args.id)
    if not job:
        print(f"No job matching {args.id!r}", file=sys.stderr)
        return 1
    detail = with_retry(api.get_job, job["_id"], force=args.refresh)

    if args.json:
        print(json.dumps(detail, indent=2, ensure_ascii=False))
        return 0

    print(f"# {detail.get('name')}  @  {detail.get('company')}")
    print(f"Location:   {detail.get('actualCity')} ({detail.get('cityCategory')})  "
          f"workplace={detail.get('workplace')}  visa={detail.get('hasVisaSponsorship')}")
    print(f"Level:      {detail.get('expLevel')}   Language: {detail.get('language')}   "
          f"Type: {detail.get('jobType')}")
    print(f"Salary:     {_fmt_salary(detail)}")
    print(f"Tech:       {', '.join(detail.get('technologies') or [])}")
    print(f"URL:        {api.job_url(detail.get('jobUrl', ''))}")
    print(f"Contact:    {detail.get('candidateContactWay')}  "
          f"{detail.get('emailAddressForApplications') or detail.get('redirectJobUrl') or ''}")
    print()
    for label, key in (("Description", "description"),
                       ("Responsibilities", "responsibilitiesTextArea"),
                       ("Must-have", "requirementsMustTextArea"),
                       ("Nice-to-have", "requirementsNiceTextArea")):
        val = detail.get(key)
        if val:
            print(f"## {label}")
            print(textwrap.indent(_strip_html(val), "  "))
            print()
    return 0


def cmd_open(args: argparse.Namespace) -> int:
    jobs = with_retry(api.list_jobs)
    job = api.resolve_id(jobs, args.id)
    if not job:
        print(f"No job matching {args.id!r}", file=sys.stderr)
        return 1
    url = api.job_url(job["jobUrl"])
    print(url)
    webbrowser.open(url, new=2)
    return 0


def cmd_apply(args: argparse.Namespace) -> int:
    """Surface the application mechanism so an agent (or human) can act on it.

    Three modes you'll see in the wild:
      1. candidateContactWay == "Email": apply by email; address in emailAddressForApplications
      2. candidateContactWay == "CompanyWebsite": redirectJobUrl points to a third-party
         ATS (Recruitee, Workday, Greenhouse, Lever, SmartRecruiters, etc.). An agent
         should open that URL with chrome-mcp and fill the form manually.
      3. applyQuestions: non-empty → the site has custom screening questions; an
         agent should answer them (on-site form or via email as a structured reply).

    With --complete <method>, marks the job as applied (for email/browser modes).
    """
    from . import db

    jobs = with_retry(api.list_jobs)
    job = api.resolve_id(jobs, args.id)
    if not job:
        print(f"No job matching {args.id!r}", file=sys.stderr)
        return 1
    d = with_retry(api.get_job, job["_id"])

    contact = d.get("candidateContactWay")
    email = d.get("emailAddressForApplications")
    redirect = d.get("redirectJobUrl")
    questions = d.get("applyQuestions") or []
    posting_url = api.job_url(d.get("jobUrl", ""))

    # Determine fallback mode (used only if direct-apply fails)
    fallback_mode = "unknown"
    if contact == "Email" and email:
        fallback_mode = "email"
    elif contact == "CompanyWebsite" and redirect:
        fallback_mode = "browser"
    elif redirect:
        fallback_mode = "browser"
    elif email:
        fallback_mode = "email"

    # Check if already applied
    existing = db.is_applied(d["_id"])

    # If --complete flag is set, mark as applied
    if args.complete:
        if existing:
            app = existing
        else:
            app = db.mark_applied(
                job_id=d["_id"],
                company=d.get("company", ""),
                role=d.get("name", ""),
                method=args.complete,
                notes=args.notes,
            )
        if args.json:
            payload = {
                "marked": True,
                "application": app,
                "job_id": d["_id"],
                "company": d.get("company"),
                "title": d.get("name"),
            }
            print(json.dumps(payload, indent=2, ensure_ascii=False))
            return 0
        print(f"Marked as applied via {args.complete}")
        return 0

    payload = {
        # direct is always the preferred mode — POST /api/jobApply via sdj direct-apply
        "mode": "direct",
        "fallback_mode": fallback_mode,
        "job_id": d["_id"],
        "title": d.get("name"),
        "company": d.get("company"),
        "location": d.get("actualCity"),
        "language": d.get("language"),
        "posting_url": posting_url,
        "apply_email": email,
        "apply_url": redirect,
        "questions": questions,
        "salary": _fmt_salary(d),
        "must_have": _strip_html(d.get("requirementsMustTextArea") or ""),
        "nice_have": _strip_html(d.get("requirementsNiceTextArea") or ""),
        "responsibilities": _strip_html(d.get("responsibilitiesTextArea") or ""),
        "description": _strip_html(d.get("description") or ""),
        "technologies": d.get("technologies") or [],
        # Agent-first: include applied status
        "applied": existing,
    }

    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0

    print(f"Apply mode: DIRECT  (fallback: {fallback_mode.upper()})")
    if existing:
        print(f"STATUS:     Already applied on {existing['applied_at']} via {existing['method']}")
    print(f"Posting:    {posting_url}")
    print(f"Role:       {payload['title']} @ {payload['company']} ({payload['location']})")
    print(f"Salary:     {payload['salary']}   Language: {payload['language']}")
    print(f"Workflow:   sdj direct-apply {d['_id']} --cv <cv.pdf> --motivation <text|path>")
    if fallback_mode == "email":
        print(f"Fallback:   email to {email}")
    elif fallback_mode == "browser":
        print(f"Fallback:   ATS at {redirect}")
        if args.open:
            webbrowser.open(redirect, new=2)
    if questions:
        print("\nScreening questions:")
        for i, q in enumerate(questions, 1):
            text = q.get("question") if isinstance(q, dict) else str(q)
            print(f"  {i}. {text}")
    return 0


def cmd_tech(args: argparse.Namespace) -> int:
    jobs = with_retry(api.list_jobs)
    from collections import Counter
    c: Counter[str] = Counter()
    for j in jobs:
        for t in j.get("filterTags") or []:
            c[t] += 1
    top = c.most_common(args.limit)
    if args.json:
        print(json.dumps(top, indent=2))
        return 0
    for name, n in top:
        print(f"{n:4d}  {name}")
    return 0


def cmd_auth(args: argparse.Namespace) -> int:
    """Proactively open the site so the user can clear a Cloudflare challenge."""
    from .captcha import interactive_unblock
    ok = interactive_unblock(api.BASE + "/")
    return 0 if ok else 1


def cmd_applications(args: argparse.Namespace) -> int:
    """List all tracked applications."""
    from . import db

    apps = db.list_applications(limit=args.limit)

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


def cmd_stats(args: argparse.Namespace) -> int:
    """Show database statistics."""
    from . import db

    stats = db.get_stats()

    if args.json:
        print(json.dumps(stats, indent=2))
        return 0

    print(f"Jobs cached:     {stats['jobs_cached']} (light), {stats['jobs_with_detail']} (detail)")
    print(f"Applications:    {stats['applications_total']} total ({stats['applications_submitted']} submitted)")
    print(f"Database:        {stats['db_path']}")
    return 0


def cmd_direct_apply(args: argparse.Namespace) -> int:
    """Submit an application directly via the SwissDevJobs native form (POST /api/jobApply).

    This bypasses external ATS systems and email — the application is sent
    through SwissDevJobs' own form, which forwards it to the company.

    Honeypot fields (yearsOfExperience, personal_website_url, address,
    required_confirmation) are intentionally left empty.

    Auto-marks job as applied on success. Returns {"already_applied": true} if
    already applied (use --force to override).
    """
    from . import db

    if not args.name or not args.email:
        print(
            "Error: applicant identity is required. Pass --name/--email, or set\n"
            "       the SDJ_NAME and SDJ_EMAIL environment variables.",
            file=sys.stderr,
        )
        return 1

    jobs = with_retry(api.list_jobs)
    job = api.resolve_id(jobs, args.id)
    if not job:
        print(f"No job matching {args.id!r}", file=sys.stderr)
        return 1

    # Check for existing application (dedup as data, not error)
    existing = db.is_applied(job["_id"])
    if existing and not args.force:
        if args.json:
            print(json.dumps({"already_applied": True, "application": existing}, indent=2))
            return 0  # Success exit - agent handles this
        print(f"Already applied on {existing['applied_at']} via {existing['method']}")
        print("Use --force to apply again.")
        return 1

    d = with_retry(api.get_job, job["_id"])

    # Non-deliverable detection. The native POST /api/jobApply only reaches the
    # company when SwissDevJobs holds a real forwarding channel — i.e. the
    # posting has candidateContactWay == "Email" with emailAddressForApplications
    # set. Two cases silently black-hole (endpoint returns 200, company never
    # receives the submission):
    #   1. Aggregator syndication (talent.com / jometer) — no forwarding channel.
    #   2. candidateContactWay == "CompanyWebsite" — SDJ merely links out to the
    #      company's own ATS (umantis, Personio, applytojob, etc.); there is no
    #      native form delivery. emailAddressForApplications is null for these.
    # In both cases refuse and route the agent to chrome MCP on redirectJobUrl.
    AGGREGATOR_HOSTS = ("talent.com", "tnl2.jometer.com", "jometer.com")
    redirect_raw = d.get("redirectJobUrl") or ""
    redirect_lc = redirect_raw.lower()
    contact_way = d.get("candidateContactWay")
    company_email = d.get("emailAddressForApplications")
    matched_host = next((h for h in AGGREGATOR_HOSTS if h in redirect_lc), None)
    is_aggregator = matched_host is not None
    is_company_website = contact_way == "CompanyWebsite" and not company_email
    is_external = is_aggregator or is_company_website
    if is_external and not args.force:
        reason = "aggregator_posting" if is_aggregator else "company_website_posting"
        if is_aggregator:
            why = f"the posting is syndicated via {matched_host}"
        else:
            why = "the posting links out to the company's own ATS (no native form delivery)"
        if args.json:
            print(json.dumps({
                "error": reason,
                "next_action": "use_chrome_mcp",
                "apply_url": redirect_raw,
                "aggregator_host": matched_host,
                "contact_way": contact_way,
                "company": d.get("company"),
                "role": d.get("name"),
                "message": (
                    f"USE CHROME MCP: visit {redirect_raw} and drive the ATS form. "
                    f"SwissDevJobs would silently black-hole this submission because "
                    f"{why}. Override with --force if you really mean it."
                ),
            }, indent=2))
        else:
            print(
                f"USE CHROME MCP — visit this URL and drive the apply form:\n"
                f"  {redirect_raw or '(no redirect URL on posting)'}\n"
                f"(SwissDevJobs would silently black-hole this submission because "
                f"{why}. Override with --force.)",
                file=sys.stderr,
            )
        return 2

    motivation = args.motivation.strip()
    # If it looks like a file path and the file exists, read it
    if motivation and os.path.exists(motivation):
        motivation = open(motivation).read().strip()
    if not motivation:
        print("Error: --motivation TEXT_OR_PATH is required", file=sys.stderr)
        return 1

    # Validate no HTML in motivation (site rejects < and >)
    if "<" in motivation or ">" in motivation:
        print("Error: motivation letter must not contain < or > characters", file=sys.stderr)
        return 1

    if not args.json:
        print(f"Submitting direct application to SwissDevJobs...")
        print(f"  Role:    {d.get('name')} @ {d.get('company')} ({d.get('actualCity')})")
        print(f"  Salary:  {_fmt_salary(d)}")
        print(f"  CV:      {args.cv}")
        print(f"  Name:    {args.name}")
        print(f"  Email:   {args.email}")
        print()

    result = with_retry(
        api.direct_apply,
        d,
        name=args.name,
        email=args.email,
        motivation=motivation,
        cv_path=args.cv,
        is_from_europe=not args.not_eu,
        lang_skills=args.lang_skills,
    )

    # Auto-mark as applied on success
    application = None
    if result["status"] == 200:
        application = db.mark_applied(
            job_id=d["_id"],
            company=d.get("company", ""),
            role=d.get("name", ""),
            method="direct",
        )

    if args.json:
        result["application"] = application
        print(json.dumps(result, indent=2))
    else:
        print(f"✓ Submitted — HTTP {result['status']}")
        resp = result.get("response", "")
        if resp:
            print(f"  Response: {resp[:200]}")
        if application:
            print(f"  Marked as applied (id: {application['id']})")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="swissdevjobs",
        description="CLI for swissdevjobs.ch — Swiss dev/IT jobs with salary info.",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    lp = sub.add_parser("list", help="Search & list jobs")
    lp.add_argument("query", nargs="?", help="free-text search")
    lp.add_argument("--tech", action="append", default=[], help="repeatable, e.g. --tech Python --tech Kubernetes")
    lp.add_argument("--tech-all", action="store_true", help="require ALL --tech tags (default any)")
    lp.add_argument("--location", help="city substring, e.g. Zurich")
    lp.add_argument("--remote", action="store_true", help="remote or hybrid only")
    lp.add_argument("--onsite", action="store_true", help="exclude remote")
    lp.add_argument("--visa", action="store_true", help="visa sponsorship only")
    lp.add_argument("--level", choices=["Junior", "Regular", "Senior", "Principal", "CLevel"])
    lp.add_argument("--language", help="e.g. English, German")
    lp.add_argument("--company")
    lp.add_argument("--min-salary", type=int)
    lp.add_argument("--max-salary", type=int)
    lp.add_argument(
        "--sort",
        choices=["salary", "date", "posted", "company"],
        default="posted",
        help="salary=highest, date=newest activeFrom (re-bump-aware), "
             "posted=true creation time from ObjectId, company=A-Z. Default: posted.",
    )
    lp.add_argument("--limit", type=int, default=0,
                    help="cap output length (0 = no cap, default). Use --page/--per-page for windowed views.")
    lp.add_argument("--page", type=int, default=1,
                    help="1-indexed page number. Combine with --per-page (default page size 50).")
    lp.add_argument("--per-page", type=int, default=50,
                    help="page size when --page is used (default 50).")
    lp.add_argument("--json", action="store_true")
    lp.add_argument("--refresh", action="store_true", help="bypass cache")
    lp.add_argument("--include-applied", action="store_true",
                    help="show jobs you've already applied to (hidden by default)")
    lp.set_defaults(func=cmd_list)

    sp = sub.add_parser("show", help="Show full job details")
    sp.add_argument("id", help="job _id, jobUrl slug, or substring")
    sp.add_argument("--json", action="store_true")
    sp.add_argument("--refresh", action="store_true")
    sp.set_defaults(func=cmd_show)

    op = sub.add_parser("open", help="Open job page in your browser")
    op.add_argument("id")
    op.set_defaults(func=cmd_open)

    tp = sub.add_parser("tech", help="Top technology tags across current listings")
    tp.add_argument("--limit", type=int, default=40)
    tp.add_argument("--json", action="store_true")
    tp.set_defaults(func=cmd_tech)

    apl = sub.add_parser("apply", help="Surface apply mechanism (email / ATS URL / questions)")
    apl.add_argument("id")
    apl.add_argument("--json", action="store_true")
    apl.add_argument("--open", action="store_true", help="also open the apply URL in a browser")
    apl.add_argument("--complete", choices=["email", "browser", "linkedin"],
                     help="mark job as applied via this method")
    apl.add_argument("--notes", default=None, help="notes to store with the application")
    apl.set_defaults(func=cmd_apply)

    ap = sub.add_parser("auth", help="Open the site to resolve a Cloudflare challenge")
    ap.set_defaults(func=cmd_auth)

    da = sub.add_parser(
        "direct-apply",
        help="Submit via SwissDevJobs native form (POST /api/jobApply)",
    )
    da.add_argument("id", help="job _id, jobUrl slug, or substring")
    da.add_argument("--name", default=os.environ.get("SDJ_NAME"),
                    help="Applicant full name (default: $SDJ_NAME)")
    da.add_argument("--email", default=os.environ.get("SDJ_EMAIL"),
                    help="Applicant email address (default: $SDJ_EMAIL)")
    da.add_argument("--cv", required=True, help="Path to PDF CV file")
    da.add_argument("--motivation", default="", help="Cover letter text or path to a .txt file")
    da.add_argument("--not-eu", action="store_true", help="Set isFromEurope=No (default: Yes)")
    da.add_argument(
        "--lang-skills",
        default="native",
        choices=["native", "fluent", "good", "basic"],
        help="Self-rated language skill in the posting's language (default: native). "
             "Only sent when the posting has hasLangCheck=true.",
    )
    da.add_argument("--json", action="store_true")
    da.add_argument("--force", action="store_true", help="apply even if already marked as applied")
    da.set_defaults(func=cmd_direct_apply)

    # applications command
    apps = sub.add_parser("applications", help="List tracked applications")
    apps.add_argument("--limit", type=int, default=100)
    apps.add_argument("--json", action="store_true")
    apps.set_defaults(func=cmd_applications)

    # stats command
    st = sub.add_parser("stats", help="Show database statistics")
    st.add_argument("--json", action="store_true")
    st.set_defaults(func=cmd_stats)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except api.CaptchaRequired as e:
        print(f"Cloudflare challenge unresolved: {e}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
