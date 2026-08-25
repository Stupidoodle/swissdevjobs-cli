"""Pure data shaping shared by the CLI and the MCP server.

Nothing in here prints, prompts, or touches the network — the MCP server
speaks JSON-RPC on stdout, so any stray print would corrupt its transport.
Both front ends build their output from these helpers so the two can't
drift apart.
"""

from __future__ import annotations

import re
from typing import Any

# Postings syndicated from these hosts have no forwarding channel on
# swissdevjobs.ch, so a native submission is accepted and then dropped.
AGGREGATOR_HOSTS = ("talent.com", "tnl2.jometer.com", "jometer.com")


def strip_html(s: str) -> str:
    """Flatten the HTML the API returns in description/requirement fields."""
    s = re.sub(r"<br\s*/?>", "\n", s, flags=re.I)
    s = re.sub(r"</p>", "\n\n", s, flags=re.I)
    s = re.sub(r"<[^>]+>", "", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


def fmt_salary(job: dict[str, Any]) -> str:
    a, b = job.get("annualSalaryFrom"), job.get("annualSalaryTo")
    if a and b:
        return f"CHF {a:,}–{b:,}".replace(",", "'")
    if a:
        return f"CHF {a:,}+".replace(",", "'")
    return "—"


def fallback_mode(detail: dict[str, Any]) -> str:
    """How to apply if the site's own form isn't an option."""
    contact = detail.get("candidateContactWay")
    email = detail.get("emailAddressForApplications")
    redirect = detail.get("redirectJobUrl")

    if contact == "Email" and email:
        return "email"
    if contact == "CompanyWebsite" and redirect:
        return "browser"
    if redirect:
        return "browser"
    if email:
        return "email"
    return "unknown"


def undeliverable(detail: dict[str, Any]) -> dict[str, Any] | None:
    """Detect submissions the native form would silently black-hole.

    `POST /api/jobApply` answers 200 even when swissdevjobs.ch holds no
    forwarding channel for the posting. That happens when the listing was
    syndicated from an aggregator, or when the site merely links out to the
    company's own ATS (candidateContactWay == "CompanyWebsite" with no
    application address).

    Returns a refusal payload naming the real apply URL, or None when the
    native form genuinely delivers.
    """
    redirect = detail.get("redirectJobUrl") or ""
    contact_way = detail.get("candidateContactWay")
    company_email = detail.get("emailAddressForApplications")

    matched_host = next((h for h in AGGREGATOR_HOSTS if h in redirect.lower()), None)
    is_aggregator = matched_host is not None
    is_company_website = contact_way == "CompanyWebsite" and not company_email

    if not (is_aggregator or is_company_website):
        return None

    if is_aggregator:
        reason = "aggregator_posting"
        why = f"the posting is syndicated via {matched_host}"
    else:
        reason = "company_website_posting"
        why = "the posting links out to the company's own ATS (no native form delivery)"

    return {
        "error": reason,
        "next_action": "use_chrome_mcp",
        "apply_url": redirect,
        "aggregator_host": matched_host,
        "contact_way": contact_way,
        "company": detail.get("company"),
        "role": detail.get("name"),
        "message": (
            f"USE CHROME MCP: visit {redirect} and drive the ATS form. "
            f"SwissDevJobs would silently black-hole this submission because "
            f"{why}. Override with --force if you really mean it."
        ),
    }


def apply_payload(
    detail: dict[str, Any],
    *,
    posting_url: str,
    applied: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Everything a caller needs to decide how to apply to one posting."""
    return {
        # `direct` is always the preferred mode — POST /api/jobApply.
        "mode": "direct",
        "fallback_mode": fallback_mode(detail),
        "job_id": detail["_id"],
        "title": detail.get("name"),
        "company": detail.get("company"),
        "location": detail.get("actualCity"),
        "language": detail.get("language"),
        "posting_url": posting_url,
        "apply_email": detail.get("emailAddressForApplications"),
        "apply_url": detail.get("redirectJobUrl"),
        "questions": detail.get("applyQuestions") or [],
        "salary": fmt_salary(detail),
        "must_have": strip_html(detail.get("requirementsMustTextArea") or ""),
        "nice_have": strip_html(detail.get("requirementsNiceTextArea") or ""),
        "responsibilities": strip_html(detail.get("responsibilitiesTextArea") or ""),
        "description": strip_html(detail.get("description") or ""),
        "technologies": detail.get("technologies") or [],
        "applied": applied,
    }
