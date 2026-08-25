"""Offline tests for search filtering and sorting."""

from __future__ import annotations

from conftest import domain_job
from swissdevjobs_cli.domain.model.ids import posted_at_from_object_id
from swissdevjobs_cli.service_layer.search import matches, sort_key


def test_tech_any_matches_a_single_tag():
    assert matches(domain_job(), tech=["kubernetes"])
    assert not matches(domain_job(), tech=["rust"])


def test_tech_all_requires_every_tag():
    assert matches(domain_job(), tech=["Python", "AWS"], tech_any=False)
    assert not matches(domain_job(), tech=["Python", "Rust"], tech_any=False)


def test_location_is_a_substring_match():
    assert matches(domain_job(), location="zur")
    assert not matches(domain_job(), location="Bern")


def test_remote_includes_hybrid_but_onsite_excludes_remote():
    assert matches(domain_job(workplace="hybrid"), remote=True)
    assert matches(domain_job(workplace="remote"), remote=True)
    assert not matches(domain_job(workplace="office"), remote=True)
    assert not matches(domain_job(workplace="remote"), remote=False)


def test_visa_filter_requires_an_explicit_yes():
    assert matches(domain_job(hasVisaSponsorship="Yes"), visa=True)
    assert not matches(domain_job(hasVisaSponsorship="No"), visa=True)


def test_salary_bounds_compare_against_opposite_ends_of_the_range():
    # min-salary keeps anything whose ceiling clears the bar
    assert matches(domain_job(annualSalaryTo=160000), min_salary=150000)
    assert not matches(domain_job(annualSalaryTo=140000), min_salary=150000)
    # max-salary keeps anything whose floor is under the bar
    assert matches(domain_job(annualSalaryFrom=130000), max_salary=140000)
    assert not matches(domain_job(annualSalaryFrom=150000), max_salary=140000)


def test_missing_salary_is_excluded_by_a_minimum():
    assert not matches(domain_job(annualSalaryTo=None), min_salary=100000)


def test_free_text_searches_title_company_city_and_tags():
    assert matches(domain_job(), query="senior python")
    assert matches(domain_job(), query="acme")
    assert matches(domain_job(), query="kubernetes")
    assert not matches(domain_job(), query="cobol")


def test_filters_combine_as_and():
    assert matches(domain_job(), tech=["Python"], location="Zurich", min_salary=150000)
    assert not matches(
        domain_job(), tech=["Python"], location="Bern", min_salary=150000
    )


def test_posted_at_decodes_the_objectid_timestamp():
    # 62eccd7a -> 2022-08-05T13:52:26Z
    assert posted_at_from_object_id("62eccd7a57370f0152e4950e") == 0x62ECCD7A


def test_posted_at_survives_a_malformed_id():
    assert posted_at_from_object_id("not-hex!") is None
    assert posted_at_from_object_id("") is None


def test_sort_by_salary_puts_the_highest_first():
    jobs = [domain_job(annualSalaryTo=140000), domain_job(annualSalaryTo=180000)]
    jobs.sort(key=lambda j: sort_key(j, by="salary"))
    assert jobs[0].raw["annualSalaryTo"] == 180000


def test_sort_by_posted_uses_the_id_not_the_rebump_date():
    old_id_recently_bumped = domain_job(
        _id="62eccd7a57370f0152e4950e", activeFrom="2026-08-24T00:00:00Z"
    )
    genuinely_new = domain_job(
        _id="68b0000057370f0152e4950e", activeFrom="2026-01-01T00:00:00Z"
    )
    jobs = [old_id_recently_bumped, genuinely_new]
    jobs.sort(key=lambda j: sort_key(j, by="posted"))
    assert jobs[0] is genuinely_new
    # …whereas sorting by activeFrom is fooled by the bump
    jobs.sort(key=lambda j: sort_key(j, by="date"))
    assert jobs[0] is old_id_recently_bumped
