from __future__ import annotations

from conftest import job
from swissdevjobs_cli.payloads import (
    apply_payload,
    fallback_mode,
    fmt_salary,
    strip_html,
    undeliverable,
)


def test_salary_uses_swiss_thousands_separators():
    assert fmt_salary(job()) == "CHF 130'000–160'000"
    assert fmt_salary(job(annualSalaryTo=None)) == "CHF 130'000+"
    assert fmt_salary(job(annualSalaryFrom=None, annualSalaryTo=None)) == "—"


def test_strip_html_turns_markup_into_readable_text():
    assert strip_html("<p>One</p><p>Two</p>") == "One\n\nTwo"
    assert strip_html("a<br>b<br/>c") == "a\nb\nc"
    assert strip_html("<ul><li>x</li></ul>") == "x"


def test_fallback_mode_prefers_a_real_email_address():
    assert fallback_mode(job()) == "email"
    assert fallback_mode(job(candidateContactWay="CompanyWebsite",
                            emailAddressForApplications=None,
                            redirectJobUrl="https://acme.example/apply")) == "browser"
    assert fallback_mode(job(candidateContactWay=None,
                            emailAddressForApplications=None,
                            redirectJobUrl=None)) == "unknown"


def test_a_forwardable_posting_is_not_refused():
    assert undeliverable(job()) is None


def test_aggregator_syndication_is_refused_and_names_the_host():
    refusal = undeliverable(job(redirectJobUrl="https://ch.talent.com/view?id=9"))
    assert refusal is not None
    assert refusal["error"] == "aggregator_posting"
    assert refusal["aggregator_host"] == "talent.com"
    assert refusal["next_action"] == "use_chrome_mcp"
    assert "talent.com" in refusal["apply_url"]


def test_jometer_syndication_is_refused():
    refusal = undeliverable(job(redirectJobUrl="https://tnl2.jometer.com/x"))
    assert refusal["error"] == "aggregator_posting"


def test_company_website_without_an_address_is_refused():
    refusal = undeliverable(job(candidateContactWay="CompanyWebsite",
                                emailAddressForApplications=None,
                                redirectJobUrl="https://acme.wd3.myworkdayjobs.com/x"))
    assert refusal["error"] == "company_website_posting"
    assert refusal["aggregator_host"] is None


def test_company_website_that_still_has_an_address_is_deliverable():
    # SwissDevJobs can forward this one, so it must not be refused.
    assert undeliverable(job(candidateContactWay="CompanyWebsite",
                             emailAddressForApplications="jobs@acme.example",
                             redirectJobUrl="https://acme.example/careers")) is None


def test_apply_payload_carries_what_a_caller_needs_to_act():
    payload = apply_payload(job(), posting_url="https://swissdevjobs.ch/jobs/acme")
    assert payload["mode"] == "direct"
    assert payload["fallback_mode"] == "email"
    assert payload["job_id"] == job()["_id"]
    assert payload["apply_email"] == "jobs@acme.example"
    assert payload["salary"] == "CHF 130'000–160'000"
    assert payload["applied"] is None
    assert payload["questions"] == []


def test_apply_payload_reports_an_existing_application():
    record = {"id": 7, "method": "direct", "applied_at": "2026-08-01"}
    payload = apply_payload(job(), posting_url="x", applied=record)
    assert payload["applied"] == record


def test_apply_payload_flattens_html_description_fields():
    payload = apply_payload(
        job(description="<p>Build <b>things</b></p>"), posting_url="x"
    )
    assert payload["description"] == "Build things"
