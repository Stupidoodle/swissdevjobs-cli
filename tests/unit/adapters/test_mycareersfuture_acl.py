"""The MyCareersFuture ACL: wire docs -> normalized raw + domain objects."""

from __future__ import annotations

from swissdevjobs_cli.adapters.boards.registry import BOARDS
from swissdevjobs_cli.adapters.boards.singapore.mycareersfuture import acl

MCF = BOARDS["mycareersfuture"]


def doc(**overrides):
    """A trimmed /v2/jobs list-row document (recorded 2026-08-26)."""
    base = {
        "uuid": "3a1e2f10-4b6c-4d8e-9f0a-1b2c3d4e5f60",
        "title": "Cloud Engineer (Python, AWS)",
        "description": "<p>We are looking for a <b>Cloud Engineer</b>.</p>",
        "postedCompany": {"name": "PASONA SINGAPORE PTE. LTD.", "uen": "T01FC1234A"},
        "salary": {"minimum": 5000, "maximum": 8000, "type": "Monthly"},
        "categories": [{"id": 21, "category": "Information Technology"}],
        "employmentTypes": [{"id": 8, "employmentType": "Full Time"}],
        "positionLevels": [{"id": 7, "position": "Professional"}],
        "address": {"district": "Central"},
        "skills": [{"name": "Python", "uuid": "sk-1"}, {"name": "AWS", "uuid": "sk-2"}],
        "flexibleWorkArrangements": [],
        "metadata": {
            "jobPostId": "MCF-2026-0000001",
            "createdAt": "2026-08-20T03:00:00.000Z",
            "newPostingDate": "2026-08-20",
            "originalPostingDate": "2026-08-15",
            "expiryDate": "2026-09-15",
            "jobDetailsUrl": (
                "https://www.mycareersfuture.gov.sg/job/information-technology/"
                "cloud-engineer-pasona-3a1e2f10"
            ),
            "isHideSalary": False,
            "emailRecipient": None,
        },
    }
    base.update(overrides)
    return base


def test_a_list_row_normalizes_to_the_shared_raw_keys():
    j = acl.job_from_wire(doc(), MCF)
    raw = j.raw
    assert raw["_id"] == "3a1e2f10-4b6c-4d8e-9f0a-1b2c3d4e5f60"
    assert raw["jobUrl"] == doc()["metadata"]["jobDetailsUrl"]
    assert raw["name"] == "Cloud Engineer (Python, AWS)"
    assert raw["company"] == "PASONA SINGAPORE PTE. LTD."
    assert raw["actualCity"] == "Central"
    assert raw["language"] is None
    assert raw["country"] == "sg"
    assert raw["source"] == "mycareersfuture"
    # original wire keys survive
    assert raw["title"] == raw["name"]
    assert raw["postedCompany"]["uen"] == "T01FC1234A"


def test_monthly_salary_is_annualized():
    j = acl.job_from_wire(doc(), MCF)
    assert j.salary.lower == 60000
    assert j.salary.upper == 96000
    assert j.salary.currency == "SGD"


def test_annual_salary_type_is_used_as_is():
    j = acl.job_from_wire(
        doc(salary={"minimum": 60000, "maximum": 96000, "type": "Annual"}), MCF
    )
    assert j.salary.lower == 60000
    assert j.salary.upper == 96000


def test_an_unrecognized_salary_type_is_never_guessed():
    j = acl.job_from_wire(
        doc(salary={"minimum": 500, "maximum": 800, "type": "Daily"}), MCF
    )
    assert j.salary.lower is None
    assert j.salary.upper is None


def test_a_hidden_salary_is_never_shown():
    j = acl.job_from_wire(
        doc(metadata={**doc()["metadata"], "isHideSalary": True}), MCF
    )
    assert j.salary.lower is None
    assert j.salary.upper is None


def test_skills_become_technologies():
    j = acl.job_from_wire(doc(), MCF)
    assert j.raw["technologies"] == ["Python", "AWS"]
    assert j.raw["filterTags"] == ["Python", "AWS"]


def test_empty_skills_yield_an_empty_list_not_a_crash():
    j = acl.job_from_wire(doc(skills=[]), MCF)
    assert j.raw["technologies"] == []
    assert j.raw["filterTags"] == []


def test_flexi_place_maps_to_remote():
    j = acl.job_from_wire(doc(flexibleWorkArrangements=["Flexi-Place"]), MCF)
    assert j.raw["workplace"] == "remote"


def test_flexi_hours_alone_is_not_remote():
    j = acl.job_from_wire(doc(flexibleWorkArrangements=["Flexi-Hours"]), MCF)
    assert j.raw["workplace"] == "onsite"


def test_no_flexible_arrangements_is_onsite():
    j = acl.job_from_wire(doc(flexibleWorkArrangements=[]), MCF)
    assert j.raw["workplace"] == "onsite"


def test_employment_types_map_to_shared_contract_aliases():
    j = acl.job_from_wire(
        doc(employmentTypes=[{"id": 3, "employmentType": "Contract"}]), MCF
    )
    assert j.raw["contractTypes"] == ["freelance", "temporary"]
    j2 = acl.job_from_wire(
        doc(employmentTypes=[{"id": 7, "employmentType": "Permanent"}]), MCF
    )
    assert j2.raw["contractTypes"] == ["permanent"]


def test_missing_district_yields_none_not_a_crash():
    j = acl.job_from_wire(doc(address={}), MCF)
    assert j.raw["actualCity"] is None


def test_posted_at_uses_the_metadata_dates():
    j = acl.job_from_wire(doc(), MCF)
    assert j.raw["activeFrom"] == "2026-08-20"
    assert j.raw["postedAt"] == "2026-08-15"


def test_detail_from_wire_strips_description_html():
    d = acl.detail_from_wire(doc(), MCF)
    assert "Cloud Engineer" in d.raw["description"]
    assert "<p>" not in d.raw["description"]
    assert d.contact_way is None
    assert d.redirect_url is None
    assert d.board is MCF


def test_posting_url_uses_the_metadata_link():
    j = acl.job_from_wire(doc(), MCF)
    assert acl.posting_url(MCF, j.raw) == doc()["metadata"]["jobDetailsUrl"]


def test_posting_url_falls_back_to_a_constructed_path_without_metadata():
    j = acl.job_from_wire(doc(metadata={**doc()["metadata"], "jobDetailsUrl": ""}), MCF)
    assert acl.posting_url(MCF, j.raw) == (
        "https://www.mycareersfuture.gov.sg/job/3a1e2f10-4b6c-4d8e-9f0a-1b2c3d4e5f60"
    )


def test_the_original_wire_mapping_is_not_mutated():
    wire = doc()
    acl.job_from_wire(wire, MCF)
    assert "name" not in wire
    assert "source" not in wire
