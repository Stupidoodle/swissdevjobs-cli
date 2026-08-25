"""Row mapping edge cases the round-trip tests don't reach."""

from __future__ import annotations

import sqlite3

from swissdevjobs_cli.adapters.persistence.mappers import row_to_job


def _row(**cols):
    base = {
        "_id": "62eccd7a57370f0152e4950e",
        "source": "swissdevjobs",
        "job_url": "acme-role",
        "company": "Acme AG",
        "name": "Role",
        "actual_city": "Zurich",
        "workplace": "hybrid",
        "language": "English",
        "annual_salary_from": 100000,
        "annual_salary_to": 120000,
        "technologies": '["Python"]',
        "filter_tags": '["Python"]',
        "candidate_contact_way": "Email",
        "email_address": "jobs@acme.example",
        "redirect_url": None,
        "active_from": "2026-08-01",
        "light_json": None,
    }
    base.update(cols)
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    keys = ", ".join(base)
    placeholders = ", ".join("?" for _ in base)
    conn.execute(f"CREATE TABLE jobs ({', '.join(base)})")
    conn.execute(
        f"INSERT INTO jobs ({keys}) VALUES ({placeholders})", list(base.values())
    )
    row = conn.execute("SELECT * FROM jobs").fetchone()
    conn.close()
    return row


def test_a_row_without_light_json_falls_back_to_columns():
    j = row_to_job(_row())
    assert j.company == "Acme AG"
    assert j.raw["postedAtUnix"] == 0x62ECCD7A
    assert j.salary.currency == "CHF"


def test_an_unknown_source_falls_back_to_the_ch_board():
    j = row_to_job(_row(source="board-that-was-removed"))
    assert j.board.country == "ch"


def test_a_jobcloud_row_always_round_trips_via_light_json(fresh_uow):
    """light_json is mandatory for jobcloud rows.

    A UUID `_id` would hex-decode to garbage in the column-fallback path.
    """
    import json as jsonlib

    from swissdevjobs_cli.adapters.boards.registry import BOARDS
    from swissdevjobs_cli.adapters.boards.switzerland.jobcloud import acl

    job = acl.job_from_wire(
        {
            "job_id": "f667bc34-c8c9-47c0-b554-9050fdcdcf5f",
            "slug": "f667bc34-role",
            "title": "Role",
            "company_name": "Acme AG",
            "initial_publication_date": "2026-07-31T15:27:59+00:00",
        },
        BOARDS["jobsch"],
    )
    fresh_uow.jobs.store_jobs([job])
    (cached,) = fresh_uow.jobs.cached_jobs("jobsch", 600)
    assert cached.posted_at_unix == 1785511679, "hex-decoded UUID garbage"
    assert cached.raw == jsonlib.loads(jsonlib.dumps(job.raw))
    assert cached.board is BOARDS["jobsch"]
