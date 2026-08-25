"""The ACL is the only place wire field names are read; pin its behavior."""

from __future__ import annotations

import pytest

from conftest import job
from swissdevjobs_cli.adapters.boards.registry import BOARDS
from swissdevjobs_cli.adapters.boards.worldwide.devitjobs import acl

FAMILY = sorted(s for s, b in BOARDS.items() if b.platform == "devitjobs")


@pytest.mark.parametrize("source", FAMILY)
def test_jobs_carry_their_board_and_currency(source):
    board = BOARDS[source]
    j = acl.job_from_wire(job(), board)
    assert j.board is board
    assert j.salary.currency == board.currency
    assert j.raw["country"] == board.country
    assert j.raw["source"] == source


@pytest.mark.parametrize("source", FAMILY)
def test_posting_urls_point_at_the_right_board(source):
    board = BOARDS[source]
    assert acl.posting_url(board, "some-slug") == f"{board.base_url}/jobs/some-slug"


def test_posted_at_is_decorated_from_the_object_id():
    j = acl.job_from_wire(job(), BOARDS["swissdevjobs"])
    assert j.raw["postedAtUnix"] == 0x62ECCD7A
    assert j.raw["postedAt"].startswith("2022-08-05")
    assert j.posted_at_unix == 0x62ECCD7A


def test_a_malformed_id_decorates_none_not_a_crash():
    j = acl.job_from_wire(job(_id="not-hex!"), BOARDS["swissdevjobs"])
    assert j.raw["postedAtUnix"] is None
    assert j.raw["postedAt"] is None


def test_detail_keeps_the_wire_payload_and_tags_the_country():
    d = acl.detail_from_wire(job(description="<p>x</p>"), BOARDS["germantechjobs"])
    assert d.raw["description"] == "<p>x</p>"
    assert d.raw["country"] == "de"
    assert d.board is BOARDS["germantechjobs"]
    assert d.salary.currency == "EUR"


def test_the_original_wire_mapping_is_not_mutated():
    wire = job()
    acl.job_from_wire(wire, BOARDS["swissdevjobs"])
    assert "postedAt" not in wire
    assert "country" not in wire


def test_job_type_maps_onto_the_shared_contract_aliases():
    """A Contract row answers to both the freelance and temporary aliases.

    The platform folds contracting and temp work into one jobType value.
    """
    permanent = acl.job_from_wire(
        {"_id": "62eccd7a57370f0152e4950e", "jobType": "Full-Time"},
        BOARDS["swissdevjobs"],
    )
    assert permanent.raw["contractTypes"] == ["permanent"]
    contractor = acl.job_from_wire(
        {"_id": "62eccd7a57370f0152e4950e", "jobType": "Contract"},
        BOARDS["swissdevjobs"],
    )
    assert contractor.raw["contractTypes"] == ["freelance", "temporary"]
