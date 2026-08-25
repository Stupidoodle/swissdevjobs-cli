"""Offline tests for salary formatting, HTML stripping, and apply payloads."""

from __future__ import annotations

from conftest import domain_detail, job
from swissdevjobs_cli.domain.model.job import strip_html
from swissdevjobs_cli.domain.model.salary import SalaryRange
from swissdevjobs_cli.dto.job import JobDetailDTO
from swissdevjobs_cli.service_layer.apply import fallback_mode, undeliverable


def fmt_salary(wire) -> str:
    return SalaryRange.from_wire(wire).format()


def test_salary_uses_swiss_thousands_separators():
    assert fmt_salary(job()) == "CHF 130'000–160'000"
    assert fmt_salary(job(annualSalaryTo=None)) == "CHF 130'000+"
    assert fmt_salary(job(annualSalaryFrom=None, annualSalaryTo=None)) == "—"


def test_strip_html_turns_markup_into_readable_text():
    assert strip_html("<p>One</p><p>Two</p>") == "One\n\nTwo"
    assert strip_html("a<br>b<br/>c") == "a\nb\nc"
    assert strip_html("<ul><li>x</li></ul>") == "x"
    # jobs.ch templates carry literal entities in their text nodes
    assert strip_html("<p>M&amp;A &uuml;ber 60&nbsp;%</p>") == "M&A \u00fcber 60\u00a0%"


def test_fallback_mode_prefers_a_real_email_address():
    assert fallback_mode(domain_detail()) == "email"
    assert (
        fallback_mode(
            domain_detail(
                candidateContactWay="CompanyWebsite",
                emailAddressForApplications=None,
                redirectJobUrl="https://acme.example/apply",
            )
        )
        == "browser"
    )
    assert (
        fallback_mode(
            domain_detail(
                candidateContactWay=None,
                emailAddressForApplications=None,
                redirectJobUrl=None,
            )
        )
        == "unknown"
    )


def test_a_forwardable_posting_is_not_refused():
    assert undeliverable(domain_detail()) is None


def test_aggregator_syndication_is_refused_and_names_the_host():
    refusal = undeliverable(
        domain_detail(redirectJobUrl="https://ch.talent.com/view?id=9")
    )
    assert refusal is not None
    assert refusal["error"] == "aggregator_posting"
    assert refusal["aggregator_host"] == "talent.com"
    assert refusal["next_action"] == "use_chrome_mcp"
    assert "talent.com" in refusal["apply_url"]


def test_jometer_syndication_is_refused():
    refusal = undeliverable(domain_detail(redirectJobUrl="https://tnl2.jometer.com/x"))
    assert refusal["error"] == "aggregator_posting"


def test_company_website_without_an_address_is_refused():
    refusal = undeliverable(
        domain_detail(
            candidateContactWay="CompanyWebsite",
            emailAddressForApplications=None,
            redirectJobUrl="https://acme.wd3.myworkdayjobs.com/x",
        )
    )
    assert refusal["error"] == "company_website_posting"
    assert refusal["aggregator_host"] is None


def test_company_website_that_still_has_an_address_is_deliverable():
    # SwissDevJobs can forward this one, so it must not be refused.
    assert (
        undeliverable(
            domain_detail(
                candidateContactWay="CompanyWebsite",
                emailAddressForApplications="jobs@acme.example",
                redirectJobUrl="https://acme.example/careers",
            )
        )
        is None
    )


def apply_payload(detail, *, posting_url, applied=None):
    return JobDetailDTO.from_domain(
        detail, posting_url=posting_url, applied=applied
    ).as_dict()


def test_apply_payload_carries_what_a_caller_needs_to_act():
    payload = apply_payload(
        domain_detail(), posting_url="https://swissdevjobs.ch/jobs/acme"
    )
    assert payload["mode"] == "direct"
    assert payload["fallback_mode"] == "email"
    assert payload["job_id"] == job()["_id"]
    assert payload["apply_email"] == "jobs@acme.example"
    assert payload["salary"] == "CHF 130'000–160'000"
    assert payload["applied"] is None
    assert payload["questions"] == []


def test_apply_payload_reports_an_existing_application():
    record = {"id": 7, "method": "direct", "applied_at": "2026-08-01"}
    payload = apply_payload(domain_detail(), posting_url="x", applied=record)
    assert payload["applied"] == record


def test_apply_payload_flattens_html_description_fields():
    payload = apply_payload(
        domain_detail(description="<p>Build <b>things</b></p>"), posting_url="x"
    )
    assert payload["description"] == "Build things"


def test_a_single_point_salary_renders_as_one_value():
    assert fmt_salary(
        job(annualSalaryFrom=65000, annualSalaryTo=65000)
    ) == "GBP 65'000".replace("GBP", "CHF")


def test_a_syndicated_listing_is_refused_even_off_the_known_host_list():
    """isPartner/cpc mark paid syndication; the page has no native apply form.

    Real example shape from germantechjobs.de — the redirect host (jobg8) is
    NOT in AGGREGATOR_HOSTS, so only the flag catches it.
    """
    refusal = undeliverable(
        domain_detail(
            isPartner=True,
            cpc=6.91,
            candidateContactWay="CompanyWebsite",
            emailAddressForApplications=None,
            redirectJobUrl="https://www.jobg8.com/Traffic.aspx?f7Xneet",
        )
    )
    assert refusal is not None
    assert refusal["error"] == "syndicated_posting"
    assert refusal["next_action"] == "use_chrome_mcp"
    assert "jobg8.com" in refusal["message"]
    assert refusal["apply_url"].startswith("https://www.jobg8.com/")


def test_a_native_posting_without_partner_flags_is_still_deliverable():
    assert undeliverable(domain_detail(isPartner=False)) is None
