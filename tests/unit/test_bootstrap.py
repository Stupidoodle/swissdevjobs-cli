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
    assert runtime.enabled == ["ch", "de"]
    assert set(runtime.boards) == set(BOARDS), (
        "disabled boards stay wired so cached jobs from them remain actionable"
    )
    assert [b.board.country for b in runtime.enabled_boards()] == ["ch", "de"]


def test_board_for_returns_the_jobs_own_client(monkeypatch):
    monkeypatch.delenv("SDJ_COUNTRIES", raising=False)
    from conftest import domain_job

    runtime = bootstrap.build_runtime()
    assert runtime.board_for(domain_job()).board is BOARDS["ch"]


def test_resolved_paths_report_the_sandbox():
    paths = bootstrap.resolved_paths()
    assert "sdj-tests-" in paths["cache_dir"]
    assert paths["db_path"].endswith("swissdevjobs.db")
