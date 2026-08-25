"""Offline tests for filter."""

from __future__ import annotations

from conftest import job
from swissdevjobs_cli.filter import _posted_at_from_id, matches, sort_key


def test_tech_any_matches_a_single_tag():
    assert matches(job(), tech=["kubernetes"])
    assert not matches(job(), tech=["rust"])


def test_tech_all_requires_every_tag():
    assert matches(job(), tech=["Python", "AWS"], tech_any=False)
    assert not matches(job(), tech=["Python", "Rust"], tech_any=False)


def test_location_is_a_substring_match():
    assert matches(job(), location="zur")
    assert not matches(job(), location="Bern")


def test_remote_includes_hybrid_but_onsite_excludes_remote():
    assert matches(job(workplace="hybrid"), remote=True)
    assert matches(job(workplace="remote"), remote=True)
    assert not matches(job(workplace="office"), remote=True)
    assert not matches(job(workplace="remote"), remote=False)


def test_visa_filter_requires_an_explicit_yes():
    assert matches(job(hasVisaSponsorship="Yes"), visa=True)
    assert not matches(job(hasVisaSponsorship="No"), visa=True)


def test_salary_bounds_compare_against_opposite_ends_of_the_range():
    # min-salary keeps anything whose ceiling clears the bar
    assert matches(job(annualSalaryTo=160000), min_salary=150000)
    assert not matches(job(annualSalaryTo=140000), min_salary=150000)
    # max-salary keeps anything whose floor is under the bar
    assert matches(job(annualSalaryFrom=130000), max_salary=140000)
    assert not matches(job(annualSalaryFrom=150000), max_salary=140000)


def test_missing_salary_is_excluded_by_a_minimum():
    assert not matches(job(annualSalaryTo=None), min_salary=100000)


def test_free_text_searches_title_company_city_and_tags():
    assert matches(job(), query="senior python")
    assert matches(job(), query="acme")
    assert matches(job(), query="kubernetes")
    assert not matches(job(), query="cobol")


def test_filters_combine_as_and():
    assert matches(job(), tech=["Python"], location="Zurich", min_salary=150000)
    assert not matches(job(), tech=["Python"], location="Bern", min_salary=150000)


def test_posted_at_decodes_the_objectid_timestamp():
    # 62eccd7a -> 2022-08-05T13:52:26Z
    assert _posted_at_from_id(job()) == 0x62ECCD7A


def test_posted_at_survives_a_malformed_id():
    assert _posted_at_from_id({"_id": "not-hex!"}) == 0
    assert _posted_at_from_id({}) == 0


def test_sort_by_salary_puts_the_highest_first():
    jobs = [job(annualSalaryTo=140000), job(annualSalaryTo=180000)]
    jobs.sort(key=lambda j: sort_key(j, by="salary"))
    assert jobs[0]["annualSalaryTo"] == 180000


def test_sort_by_posted_uses_the_id_not_the_rebump_date():
    old_id_recently_bumped = job(
        _id="62eccd7a57370f0152e4950e", activeFrom="2026-08-24T00:00:00Z"
    )
    genuinely_new = job(
        _id="68b0000057370f0152e4950e", activeFrom="2026-01-01T00:00:00Z"
    )
    jobs = [old_id_recently_bumped, genuinely_new]
    jobs.sort(key=lambda j: sort_key(j, by="posted"))
    assert jobs[0] is genuinely_new
    # …whereas sorting by activeFrom is fooled by the bump
    jobs.sort(key=lambda j: sort_key(j, by="date"))
    assert jobs[0] is old_id_recently_bumped
