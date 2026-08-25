"""The apply use case: deliverability, validation, and native submission."""

from __future__ import annotations

from typing import Any

from swissdevjobs_cli.domain.model.application import Applicant, ApplicationRecord
from swissdevjobs_cli.domain.model.job import JobDetail
from swissdevjobs_cli.domain.ports.board_port import BoardPort
from swissdevjobs_cli.domain.ports.unit_of_work import UnitOfWork

# Postings syndicated from these hosts have no forwarding channel on the
# board, so a native submission is accepted and then dropped.
AGGREGATOR_HOSTS = ("talent.com", "tnl2.jometer.com", "jometer.com")


def fallback_mode(detail: JobDetail) -> str:
    """How to apply if the board's own form isn't an option."""
    if detail.contact_way == "Email" and detail.apply_email:
        return "email"
    if detail.contact_way == "CompanyWebsite" and detail.redirect_url:
        return "browser"
    if detail.redirect_url:
        return "browser"
    if detail.apply_email:
        return "email"
    return "unknown"


def undeliverable(detail: JobDetail) -> dict[str, Any] | None:
    """Detect submissions the native form would silently black-hole.

    `POST /api/jobApply` answers 200 even when the board holds no forwarding
    channel for the posting. That happens when the listing was syndicated
    from an aggregator, or when the board merely links out to the company's
    own ATS (contact way "CompanyWebsite" with no application address).

    Returns a refusal payload naming the real apply URL, or None when the
    native form genuinely delivers.
    """
    redirect = detail.redirect_url or ""
    raw = detail.raw

    # Boards without a native apply endpoint (jobs.ch, jobup.ch) can never
    # deliver a direct submission — the posting's ATS is the only channel.
    if not detail.board.native_apply:
        where = (
            "Open apply_url in a browser and drive the form there"
            if detail.redirect_url
            else "Open the posting page in a browser and follow its apply flow"
        )
        return {
            "error": "no_native_apply",
            "next_action": "use_chrome_mcp",
            "apply_url": detail.redirect_url,
            "aggregator_host": None,
            "contact_way": detail.contact_way,
            "company": detail.company,
            "role": detail.title,
            "message": (
                f"{detail.board.name} has no native apply endpoint — every "
                f"posting routes to the company's own application flow. "
                f"{where}, then record it with mark_applied / apply --complete."
            ),
        }

    matched_host = next((h for h in AGGREGATOR_HOSTS if h in redirect.lower()), None)
    # The boards mark paid syndicated listings explicitly (isPartner / cpc).
    # Verified in the browser: those pages carry NO native apply form — the
    # apply button is a bare external link — so a native POST black-holes.
    is_syndicated = bool(raw.get("isPartner") or raw.get("cpc"))
    is_aggregator = matched_host is not None
    is_company_website = (
        detail.contact_way == "CompanyWebsite" and not detail.apply_email
    )

    if not (is_syndicated or is_aggregator or is_company_website):
        return None

    if is_syndicated:
        reason = "syndicated_posting"
        host = matched_host or (redirect.split("/")[2] if "://" in redirect else None)
        why = (
            f"the listing is a paid syndication ({host or 'external network'}) "
            "and the board has no native apply form for it"
        )
    elif is_aggregator:
        reason = "aggregator_posting"
        why = f"the posting is syndicated via {matched_host}"
    else:
        reason = "company_website_posting"
        why = "the posting links out to the company's own ATS (no native form delivery)"

    return {
        "error": reason,
        "next_action": "use_chrome_mcp",
        "apply_url": detail.redirect_url,
        "aggregator_host": matched_host,
        "contact_way": detail.contact_way,
        "company": detail.company,
        "role": detail.title,
        "message": (
            f"Apply in a browser instead: open apply_url and drive the ATS "
            f"form. The native form would silently black-hole this submission "
            f"because {why}. Override with force if you really mean it."
        ),
    }


def validate_motivation(motivation: str) -> str | None:
    """The boards reject angle brackets in the letter; catch it before the POST."""
    if "<" in motivation or ">" in motivation:
        return "The site rejects < and > in the motivation letter."
    return None


def submit_and_track(
    uow: UnitOfWork,
    board: BoardPort,
    detail: JobDetail,
    applicant: Applicant,
    motivation: str,
) -> tuple[dict[str, Any], ApplicationRecord | None]:
    """Submit the native form; on HTTP 200, record the application."""
    result = board.submit_application(detail, applicant, motivation)
    application = None
    if result["status"] == 200:
        application = uow.applications.upsert(
            job_id=str(detail.id),
            company=detail.company,
            role=detail.title,
            method="direct",
            source=board.board.source,
        )
    return result, application
