"""The JobCloud ACL: wire docs → normalized raw + domain objects."""

from __future__ import annotations

from swissdevjobs_cli.adapters.boards.registry import BOARDS
from swissdevjobs_cli.adapters.boards.switzerland.jobcloud import acl

JOBSCH = BOARDS["jobsch"]
JOBUP = BOARDS["jobup"]


def doc(**overrides):
    """A trimmed /api/v1/public/search document (recorded 2026-08-25)."""
    base = {
        "job_id": "f667bc34-c8c9-47c0-b554-9050fdcdcf5f",
        "datapool_id": "f667bc34-c8c9-47c0-b554-9050fdcdcf5f",
        "slug": "f667bc34-full-stack-developer-python",
        "title": "Full-Stack Developer (m/w/d) Python",
        "company_name": "SEPPmail Deutschland GmbH",
        "place": "Zürich",
        "publication_date": "2026-07-31T17:27:59+02:00",
        "initial_publication_date": "2026-07-31T15:27:59+00:00",
        "language_skills": [{"language": "de", "level": 3}],
        "employment_grades": [100],
        "is_active": True,
        "_links": {
            "detail_en": {
                "href": (
                    "https://www.jobs.ch/en/vacancies/detail/"
                    "f667bc34-c8c9-47c0-b554-9050fdcdcf5f/"
                )
            }
        },
    }
    base.update(overrides)
    return base


def detail_doc(**overrides):
    base = doc(
        application_method="application_url",
        application_url="https://stats.the-network.com/redirect/ea120acc",
        external_url="",
        application_questions=[],
        skills=[],
        template_text="<h2>Full-Stack Developer</h2><p>Seit 25 Jahren…</p>",
        template_lead_text="Lead text",
    )
    base.update(overrides)
    return base


def test_a_search_doc_normalizes_to_the_shared_raw_keys():
    j = acl.job_from_wire(doc(), JOBSCH)
    raw = j.raw
    assert raw["_id"] == "f667bc34-c8c9-47c0-b554-9050fdcdcf5f"
    assert raw["jobUrl"] == "f667bc34-full-stack-developer-python"
    assert raw["name"].startswith("Full-Stack Developer")
    assert raw["company"] == "SEPPmail Deutschland GmbH"
    assert raw["actualCity"] == "Zürich"
    assert raw["language"] == "German"
    assert raw["activeFrom"] == "2026-07-31T17:27:59+02:00"
    assert raw["source"] == "jobsch"
    assert raw["country"] == "ch"
    # original wire keys survive for agents that want them
    assert raw["title"] == raw["name"]
    assert raw["datapool_id"]


def test_posted_at_comes_from_the_initial_publication_date():
    j = acl.job_from_wire(doc(), JOBSCH)
    assert j.posted_at_unix == 1785511679
    assert j.raw["postedAt"] == "2026-07-31T15:27:59+00:00"


def test_a_missing_publication_date_yields_none_not_a_crash():
    j = acl.job_from_wire(doc(initial_publication_date=None), JOBSCH)
    assert j.posted_at_unix is None
    assert j.raw["postedAt"] is None


def test_no_salary_exists_on_this_platform():
    j = acl.job_from_wire(doc(), JOBSCH)
    assert j.salary.lower is None
    assert j.salary.upper is None
    assert j.salary.format() == "—"


def test_language_maps_the_primary_iso_code():
    assert acl.job_from_wire(doc(), JOBSCH).raw["language"] == "German"
    fr = doc(language_skills=[{"language": "fr", "level": 4}])
    assert acl.job_from_wire(fr, JOBUP).raw["language"] == "French"
    none = doc(language_skills=[])
    assert acl.job_from_wire(none, JOBSCH).raw["language"] is None
    odd = doc(language_skills=[{"language": "rm", "level": 1}])
    assert acl.job_from_wire(odd, JOBSCH).raw["language"] == "rm"


def test_skills_become_technologies_whatever_their_shape():
    d = acl.detail_from_wire(
        detail_doc(skills=[{"name": "Python"}, "Docker", {"skill": "AWS"}]), JOBSCH
    )
    assert d.raw["technologies"] == ["Python", "Docker", "AWS"]
    assert d.raw["filterTags"] == ["Python", "Docker", "AWS"]


def test_a_detail_carries_the_ats_redirect_and_stripped_keys():
    d = acl.detail_from_wire(detail_doc(), JOBSCH)
    assert d.redirect_url == "https://stats.the-network.com/redirect/ea120acc"
    assert d.contact_way == "application_url"
    assert d.apply_email is None
    assert d.raw["description"].startswith("<h2>Full-Stack Developer</h2>")
    assert d.raw["redirectJobUrl"] == d.redirect_url
    assert d.raw["candidateContactWay"] == "application_url"
    assert d.questions == ()
    assert d.board is JOBSCH


def test_a_form_posting_has_no_redirect():
    d = acl.detail_from_wire(
        detail_doc(application_method="form", application_url=""), JOBSCH
    )
    assert d.redirect_url is None
    assert d.contact_way == "form"


def test_posting_url_prefers_the_wire_links():
    j = acl.job_from_wire(doc(), JOBSCH)
    assert acl.posting_url(JOBSCH, j.raw) == (
        "https://www.jobs.ch/en/vacancies/detail/f667bc34-c8c9-47c0-b554-9050fdcdcf5f/"
    )


def test_posting_url_falls_back_to_a_constructed_path():
    j = acl.job_from_wire(doc(_links={}), JOBSCH)
    assert acl.posting_url(JOBSCH, j.raw) == (
        "https://www.jobs.ch/en/vacancies/detail/f667bc34-c8c9-47c0-b554-9050fdcdcf5f/"
    )


def test_the_original_wire_mapping_is_not_mutated():
    wire = doc()
    acl.job_from_wire(wire, JOBSCH)
    assert "name" not in wire
    assert "source" not in wire


def test_contract_and_workload_are_normalized_onto_the_row():
    job = acl.job_from_wire(
        doc(employment_type_ids=["5"], employment_grades=[80, 85, 90, 95, 100]),
        JOBSCH,
    )
    assert job.raw["contractTypes"] == ["permanent"]
    assert job.raw["workloadFrom"] == 80
    assert job.raw["workloadTo"] == 100
