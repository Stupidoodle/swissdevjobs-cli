"""The composition root wires every board without touching the network."""

from __future__ import annotations

from swissdevjobs_cli import bootstrap
from swissdevjobs_cli.adapters.boards.registry import BOARDS


def test_build_runtime_wires_every_known_board(monkeypatch):
    monkeypatch.delenv("SDJ_COUNTRIES", raising=False)
    runtime = bootstrap.build_runtime()
    assert set(runtime.boards) == set(BOARDS)
    assert runtime.enabled == list(BOARDS)


def test_enabled_subset_still_wires_all_clients(monkeypatch):
    monkeypatch.setenv("SDJ_COUNTRIES", "ch,de")
    runtime = bootstrap.build_runtime()
    assert runtime.enabled == ["swissdevjobs", "germantechjobs", "jobsch", "jobup"]
    assert set(runtime.boards) == set(BOARDS), (
        "disabled boards stay wired so cached jobs from them remain actionable"
    )
    assert {b.board.country for b in runtime.enabled_boards()} == {"ch", "de"}


def test_a_source_selector_enables_exactly_one_board(monkeypatch):
    monkeypatch.setenv("SDJ_COUNTRIES", "jobsch")
    runtime = bootstrap.build_runtime()
    assert runtime.enabled == ["jobsch"]


def test_board_for_routes_by_source_not_country(monkeypatch):
    """Two CH boards exist; a jobcloud job must reach the jobcloud client."""
    monkeypatch.delenv("SDJ_COUNTRIES", raising=False)
    from swissdevjobs_cli.adapters.boards.switzerland.jobcloud import acl as jc_acl
    from swissdevjobs_cli.adapters.boards.switzerland.jobcloud.client import (
        JobCloudClient,
    )

    runtime = bootstrap.build_runtime()
    job = jc_acl.job_from_wire(
        {"job_id": "f667bc34-c8c9-47c0-b554-9050fdcdcf5f", "title": "X"},
        BOARDS["jobsch"],
    )
    client = runtime.board_for(job)
    assert isinstance(client, JobCloudClient)
    assert client.board is BOARDS["jobsch"]


def test_board_for_returns_the_jobs_own_client(monkeypatch):
    monkeypatch.delenv("SDJ_COUNTRIES", raising=False)
    from conftest import domain_job

    runtime = bootstrap.build_runtime()
    assert runtime.board_for(domain_job()).board is BOARDS["swissdevjobs"]


def test_resolved_paths_report_the_sandbox():
    paths = bootstrap.resolved_paths()
    assert "sdj-tests-" in paths["cache_dir"]
    assert paths["db_path"].endswith("swissdevjobs.db")
