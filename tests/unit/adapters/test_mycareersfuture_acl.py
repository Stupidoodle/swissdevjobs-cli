"""The MyCareersFuture ACL: wire docs -> normalized raw + domain objects.

The fixtures below are trimmed from real `/v2/jobs` rows recorded
2026-08-26, not invented: every nested shape here (skills keyed `skill`,
`salary.type` as an object, `flexibleWorkArrangements` as objects,
`address.districts` plural) is what the live wire actually returns.
"""

from __future__ import annotations

from swissdevjobs_cli.adapters.boards.registry import BOARDS
from swissdevjobs_cli.adapters.boards.singapore.mycareersfuture import acl

MCF = BOARDS["mycareersfuture"]


def doc(**overrides):
    """A trimmed /v2/jobs list row (recorded live 2026-08-26)."""
    base = {
        "uuid": "03c9772125f5d5737a8576c031b3f911",
        "title": "Senior Manager, Digital Lead",
        "description": "<p>Lead a team of <b>Customer Success</b> managers.</p>",
        "postedCompany": {
            "name": "GENESYS CLOUD SERVICES SINGAPORE PTE. LTD.",
            "uen": "199801892C",
        },
        "salary": {
            "maximum": 25500,
            "minimum": 14500,
            "type": {"id": 4, "salaryType": "Monthly"},
        },
        "categories": [{"id": 7, "category": "Consulting"}],
        "employmentTypes": [{"id": 8, "employmentType": "Full Time"}],
        "positionLevels": [{"id": 3, "position": "Manager"}],
        "address": {
            "isOverseas": False,
            "postalCode": None,
            "districts": [
                {
                    "id": 998,
                    "location": "Islandwide",
                    "region": "Islandwide",
                    "sectors": [],
                    "regionId": "Islandwide",
                }
            ],
        },
        "skills": [
            {
                "skill": "Tableau",
                "uuid": "020982e25cf5c16928fcf3c24a2058aa",
                "confidence": None,
                "isKeySkill": False,
            },
            {
                "skill": "Digital",
                "uuid": "0bb8309239953b782fec18706fe60b4a",
                "confidence": None,
                "isKeySkill": False,
            },
        ],
        "flexibleWorkArrangements": [],
        "minimumYearsExperience": 8,
        "metadata": {
            "jobPostId": "MCF-2026-1485808",
            "createdAt": "2026-08-26T02:32:12.000Z",
            "newPostingDate": "2026-08-26",
            "originalPostingDate": "2026-08-20",
            "expiryDate": "2026-09-09",
            "jobDetailsUrl": (
                "https://www.mycareersfuture.gov.sg/job/consulting/"
                "senior-manager-digital-lead-genesys-cloud-services-singapore-"
                "03c9772125f5d5737a8576c031b3f911"
            ),
            "isHideSalary": False,
            "emailRecipient": "79764457-161d-460d-ada6-7039ee3fa5c9",
        },
    }
    base.update(overrides)
    return base


def _district(**overrides):
    """One `address.districts` entry, in the real wire shape."""
    base = {
        "id": 1,
        "location": "D01 Marina, Raffles Place, People's Park, Cecil",
        "region": "Central",
        "sectors": [],
        "regionId": "Central",
    }
    base.update(overrides)
    return {"isOverseas": False, "districts": [base]}


def test_a_list_row_normalizes_to_the_shared_raw_keys():
    j = acl.job_from_wire(doc(), MCF)
    raw = j.raw
    assert raw["_id"] == "03c9772125f5d5737a8576c031b3f911"
    assert raw["jobUrl"] == doc()["metadata"]["jobDetailsUrl"]
    assert raw["name"] == "Senior Manager, Digital Lead"
    assert raw["company"] == "GENESYS CLOUD SERVICES SINGAPORE PTE. LTD."
    assert raw["language"] is None
    assert raw["country"] == "sg"
    assert raw["source"] == "mycareersfuture"
    # original wire keys survive for agents that want them
    assert raw["title"] == raw["name"]
    assert raw["postedCompany"]["uen"] == "199801892C"
    assert raw["minimumYearsExperience"] == 8


def test_monthly_salary_is_annualized_from_the_nested_type_object():
    """`salary.type` is an object on the wire, not a bare string."""
    j = acl.job_from_wire(doc(), MCF)
    assert j.salary.lower == 174000
    assert j.salary.upper == 306000
    assert j.salary.currency == "SGD"
    assert j.raw["annualSalaryFrom"] == 174000
    assert j.raw["annualSalaryTo"] == 306000


def test_annual_salary_type_is_used_as_is():
    j = acl.job_from_wire(
        doc(
            salary={
                "minimum": 60000,
                "maximum": 96000,
                "type": {"id": 5, "salaryType": "Annual"},
            }
        ),
        MCF,
    )
    assert j.salary.lower == 60000
    assert j.salary.upper == 96000


def test_an_unrecognized_salary_type_is_never_guessed():
    j = acl.job_from_wire(
        doc(
            salary={
                "minimum": 500,
                "maximum": 800,
                "type": {"id": 99, "salaryType": "Daily"},
            }
        ),
        MCF,
    )
    assert j.salary.lower is None
    assert j.salary.upper is None


def test_a_missing_salary_block_is_not_a_crash():
    j = acl.job_from_wire(doc(salary=None), MCF)
    assert j.salary.lower is None
    assert j.salary.upper is None


def test_a_hidden_salary_is_never_shown():
    j = acl.job_from_wire(
        doc(metadata={**doc()["metadata"], "isHideSalary": True}), MCF
    )
    assert j.salary.lower is None
    assert j.salary.upper is None


def test_skills_become_technologies_from_the_skill_key():
    """Wire entries are keyed `skill`, not `name`."""
    j = acl.job_from_wire(doc(), MCF)
    assert j.raw["technologies"] == ["Tableau", "Digital"]
    assert j.raw["filterTags"] == ["Tableau", "Digital"]


def test_empty_skills_yield_an_empty_list_not_a_crash():
    j = acl.job_from_wire(doc(skills=[]), MCF)
    assert j.raw["technologies"] == []
    assert j.raw["filterTags"] == []


def test_telecommuting_is_the_remote_signal():
    """Singapore's wire taxonomy has no "Flexi-Place" — remote is Telecommuting."""
    j = acl.job_from_wire(
        doc(
            flexibleWorkArrangements=[
                {"id": 2, "flexibleWorkArrangement": "Telecommuting"}
            ]
        ),
        MCF,
    )
    assert j.raw["workplace"] == "remote"


def test_other_flexible_arrangements_are_not_remote():
    """Flexi-Hours and friends are time flexibility, not location flexibility."""
    for arrangement in (
        "Flexi-Hours",
        "Staggered Time",
        "Compressed Work Schedule",
        "Employees Choice of Days Off",
        "Creative Scheduling",
    ):
        j = acl.job_from_wire(
            doc(
                flexibleWorkArrangements=[
                    {"id": 1, "flexibleWorkArrangement": arrangement}
                ]
            ),
            MCF,
        )
        assert j.raw["workplace"] == "onsite", arrangement


def test_telecommuting_alongside_other_arrangements_still_reads_remote():
    j = acl.job_from_wire(
        doc(
            flexibleWorkArrangements=[
                {"id": 1, "flexibleWorkArrangement": "Flexi-Hours"},
                {"id": 2, "flexibleWorkArrangement": "Telecommuting"},
            ]
        ),
        MCF,
    )
    assert j.raw["workplace"] == "remote"


def test_no_flexible_arrangements_is_onsite():
    j = acl.job_from_wire(doc(flexibleWorkArrangements=[]), MCF)
    assert j.raw["workplace"] == "onsite"


def test_the_district_supplies_city_and_region():
    """`address.districts` is a plural list of objects; there is no `district`."""
    j = acl.job_from_wire(doc(address=_district()), MCF)
    assert j.raw["actualCity"] == "D01 Marina, Raffles Place, People's Park, Cecil"
    assert j.raw["cityCategory"] == "Central"
    assert j.city == "D01 Marina, Raffles Place, People's Park, Cecil"


def test_an_islandwide_posting_keeps_its_honest_label():
    j = acl.job_from_wire(doc(), MCF)
    assert j.raw["actualCity"] == "Islandwide"
    assert j.raw["cityCategory"] == "Islandwide"


def test_a_missing_address_yields_none_not_a_crash():
    j = acl.job_from_wire(doc(address={}), MCF)
    assert j.raw["actualCity"] is None
    assert j.raw["cityCategory"] is None


def test_employment_types_map_to_shared_contract_aliases():
    cases = {
        "Full Time": ["permanent"],
        "Permanent": ["permanent"],
        "Part Time": ["permanent"],
        "Contract": ["freelance", "temporary"],
        "Freelance": ["freelance"],
        "Internship/Attachment": ["internship"],
    }
    for wire_value, expected in cases.items():
        j = acl.job_from_wire(
            doc(employmentTypes=[{"id": 1, "employmentType": wire_value}]), MCF
        )
        assert j.raw["contractTypes"] == expected, wire_value


def test_multiple_employment_types_deduplicate():
    j = acl.job_from_wire(
        doc(
            employmentTypes=[
                {"id": 7, "employmentType": "Permanent"},
                {"id": 8, "employmentType": "Full Time"},
            ]
        ),
        MCF,
    )
    assert j.raw["contractTypes"] == ["permanent"]


def test_an_unknown_employment_type_is_dropped_not_guessed():
    j = acl.job_from_wire(
        doc(employmentTypes=[{"id": 99, "employmentType": "Something New"}]), MCF
    )
    assert j.raw["contractTypes"] == []


def test_posted_at_uses_the_metadata_dates():
    j = acl.job_from_wire(doc(), MCF)
    assert j.raw["activeFrom"] == "2026-08-26"
    assert j.raw["postedAt"] == "2026-08-20"


def test_posted_at_unix_is_decoded_from_the_original_posting_date():
    """Never from the 32-hex uuid: that would hex-decode to a 1972 date."""
    j = acl.job_from_wire(doc(), MCF)
    assert j.posted_at_unix == 1787184000
    assert j.raw["postedAtUnix"] == 1787184000


def test_a_missing_posting_date_yields_none_not_a_crash():
    j = acl.job_from_wire(
        doc(metadata={**doc()["metadata"], "originalPostingDate": None}), MCF
    )
    assert j.posted_at_unix is None
    assert j.raw["postedAt"] is None


def test_detail_from_wire_strips_description_html():
    d = acl.detail_from_wire(doc(), MCF)
    assert "Customer Success" in d.raw["description"]
    assert "<p>" not in d.raw["description"]
    assert d.contact_way is None
    assert d.redirect_url is None
    assert d.apply_email is None
    assert d.questions == ()
    assert d.board is MCF


def test_posting_url_uses_the_metadata_link():
    j = acl.job_from_wire(doc(), MCF)
    assert acl.posting_url(MCF, j.raw) == doc()["metadata"]["jobDetailsUrl"]


def test_posting_url_falls_back_to_a_constructed_path_without_metadata():
    j = acl.job_from_wire(doc(metadata={**doc()["metadata"], "jobDetailsUrl": ""}), MCF)
    assert acl.posting_url(MCF, j.raw) == (
        "https://www.mycareersfuture.gov.sg/job/03c9772125f5d5737a8576c031b3f911"
    )


def test_the_original_wire_mapping_is_not_mutated():
    wire = doc()
    acl.job_from_wire(wire, MCF)
    assert "name" not in wire
    assert "source" not in wire
    assert "workplace" not in wire


def test_jobs_from_wire_maps_a_whole_page():
    rows = [doc(), doc(uuid="ffffffffffffffffffffffffffffffff")]
    jobs = acl.jobs_from_wire(rows, MCF)
    assert [str(j.id) for j in jobs] == [
        "03c9772125f5d5737a8576c031b3f911",
        "ffffffffffffffffffffffffffffffff",
    ]
