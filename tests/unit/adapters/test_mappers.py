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
