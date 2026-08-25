"""Offline tests for db."""

from __future__ import annotations

from conftest import job


def test_upsert_then_read_back_round_trips(fresh_db):
    fresh_db.upsert_jobs_light([job()])
    cached = fresh_db.get_cached_jobs(max_age_seconds=600)
    assert len(cached) == 1
    assert cached[0]["company"] == "Acme AG"
    assert cached[0]["technologies"] == ["Python", "Kubernetes"]


def test_cached_jobs_expire(fresh_db):
    fresh_db.upsert_jobs_light([job()])
    assert fresh_db.get_cached_jobs(max_age_seconds=0) is None


def test_read_back_decodes_posted_at_from_the_id(fresh_db):
    fresh_db.upsert_jobs_light([job()])
    cached = fresh_db.get_cached_jobs()
    assert cached[0]["postedAtUnix"] == 0x62ECCD7A
    assert cached[0]["postedAt"].startswith("2022-08-05")


def test_a_relisted_posting_reusing_a_slug_replaces_the_old_row(fresh_db):
    """The jobs table has UNIQUE(job_url); a re-listed job gets a fresh _id."""
    fresh_db.upsert_jobs_light([job(_id="62eccd7a57370f0152e4950e")])
    fresh_db.upsert_jobs_light([job(_id="68b0000057370f0152e4950e")])
    cached = fresh_db.get_cached_jobs()
    assert len(cached) == 1
    assert cached[0]["_id"] == "68b0000057370f0152e4950e"


def test_mark_applied_then_is_applied(fresh_db):
    assert fresh_db.is_applied("62eccd7a57370f0152e4950e") is None
    record = fresh_db.mark_applied(
        job_id="62eccd7a57370f0152e4950e",
        company="Acme AG",
        role="Senior Python Engineer",
        method="direct",
    )
    assert record["method"] == "direct"
    found = fresh_db.is_applied("62eccd7a57370f0152e4950e")
    assert found["company"] == "Acme AG"
    assert found["status"] == "submitted"


def test_marking_the_same_job_twice_updates_rather_than_duplicates(fresh_db):
    fresh_db.mark_applied(job_id="abc", company="Acme", role="Dev", method="email")
    fresh_db.mark_applied(job_id="abc", company="Acme", role="Dev", method="browser")
    apps = fresh_db.list_applications()
    assert len(apps) == 1
    assert apps[0]["method"] == "browser"


def test_is_job_applied_matches_on_id(fresh_db):
    fresh_db.mark_applied(
        job_id=job()["_id"],
        company="Acme AG",
        role="Senior Python Engineer",
        method="direct",
    )
    assert fresh_db.is_job_applied(job()) is True


def test_is_job_applied_falls_back_to_company_and_role(fresh_db):
    """An application made elsewhere still suppresses the same role here."""
    fresh_db.mark_applied(
        job_id=None,
        company="Acme AG",
        role="Senior Python Engineer",
        method="linkedin",
    )
    assert fresh_db.is_job_applied(job(_id="ffffffffffffffffffffffff")) is True


def test_an_unrelated_job_is_not_considered_applied(fresh_db):
    fresh_db.mark_applied(job_id="abc", company="Other AG", role="Dev", method="direct")
    assert fresh_db.is_job_applied(job()) is False


def test_stats_counts_jobs_and_applications(fresh_db):
    fresh_db.upsert_jobs_light([job()])
    fresh_db.mark_applied(job_id="abc", company="Acme", role="Dev", method="direct")
    stats = fresh_db.get_stats()
    assert stats["jobs_cached"] == 1
    assert stats["applications_total"] == 1
    assert stats["applications_submitted"] == 1


def test_job_detail_is_cached_and_expires(fresh_db):
    fresh_db.upsert_jobs_light([job()])
    fresh_db.upsert_job_detail(job()["_id"], {"_id": job()["_id"], "description": "hi"})
    assert fresh_db.get_cached_detail(job()["_id"])["description"] == "hi"
    assert fresh_db.get_cached_detail(job()["_id"], max_age_seconds=0) is None


def test_markdown_log_import_skips_blocked_rows(fresh_db, tmp_path):
    log = tmp_path / "applications-log.md"
    log.write_text(
        "| # | Company | Role | URL | Method | Status | Escalated | Timestamp |\n"
        "|---|---|---|---|---|---|---|---|\n"
        "| 1 | Acme AG | Dev | https://swissdevjobs.ch/jobs/x (id: abc123) "
        "| email | submitted | no | 2026-08-01 |\n"
        "| 2 | Blocked AG | Dev | url | email | blocked | yes | 2026-08-02 |\n"
    )
    assert fresh_db.import_markdown_log(log) == 1
    apps = fresh_db.list_applications()
    assert [a["company"] for a in apps] == ["Acme AG"]
    assert apps[0]["job_id"] == "abc123"
