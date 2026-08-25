"""CLI command tests: parsed args + a fake-board runtime, output via capsys."""

from __future__ import annotations

import json

import pytest

from conftest import job
from fakes.fake_board_port import FakeBoard
from swissdevjobs_cli.adapters.boards.registry import BOARDS
from swissdevjobs_cli.bootstrap import Runtime
from swissdevjobs_cli.entrypoints import cli


@pytest.fixture
def board():
    return FakeBoard(
        feed=[job()],
        detail_wire=job(description="<p>Build things</p>", applyQuestions=[]),
    )


@pytest.fixture
def runtime(board, fresh_uow):
    return Runtime(
        boards={"swissdevjobs": board}, uow=fresh_uow, enabled=["swissdevjobs"]
    )


def run(runtime, *argv):
    args = cli.build_parser().parse_args(list(argv))
    return args.func(args, runtime)


# --- list -------------------------------------------------------------------


def test_list_json_prints_summary_rows_in_an_envelope(runtime, capsys):
    assert run(runtime, "list", "--json") == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["boards_searched"] == ["swissdevjobs"]
    row = payload["jobs"][0]
    assert row["company"] == "Acme AG"
    assert row["country"] == "ch"
    assert "salary" not in row, "summary salary is numeric-only since 0.6"
    assert row["currency"] == "CHF"


def test_list_json_raw_keeps_the_pre_06_wire_shape(runtime, capsys):
    assert run(runtime, "list", "--json", "--raw") == 0
    rows = json.loads(capsys.readouterr().out)
    assert isinstance(rows, list), "--raw stays a flat list, not an envelope"
    assert rows[0]["company"] == "Acme AG"
    assert rows[0]["annualSalaryFrom"] == 130000


def test_list_json_caps_at_50_by_default(runtime, board, capsys):
    board._feed_wire = [
        job(_id=f"62eccd7a57370f0152e4{i:04x}", jobUrl=f"role-{i}") for i in range(60)
    ]
    assert run(runtime, "list", "--json") == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["returned"] == 50
    assert len(payload["jobs"]) == 50
    assert payload["total_after_filters"] == 60


def test_boards_table_lists_the_registry(runtime, capsys):
    assert run(runtime, "boards") == 0
    out = capsys.readouterr().out
    assert "jobsch" in out
    assert "search-driven" in out
    assert "no-native-apply" in out


def test_boards_json_matches_the_registry(runtime, capsys):
    assert run(runtime, "boards", "--json") == 0
    payload = json.loads(capsys.readouterr().out)
    rows = {r["source"]: r for r in payload["boards"]}
    assert rows["jobup"]["native_apply"] is False
    assert rows["jobup"]["categories"] == ["it"]
    assert rows["swissdevjobs"]["enabled"] is True


def test_list_table_has_a_header_and_the_country_column(runtime, capsys):
    assert run(runtime, "list") == 0
    out = capsys.readouterr().out
    assert "1 shown · 1 match filters · 1 in feed" in out
    assert "swissdevjobs" in out
    assert "CHF 130'000–160'000" in out


def test_list_filters_can_empty_the_result(runtime, capsys):
    assert run(runtime, "list", "--tech", "rust") == 1
    assert "No matching jobs." in capsys.readouterr().err


def test_list_hides_applied_jobs_by_default(runtime, fresh_uow, capsys):
    fresh_uow.applications.upsert(
        job_id=job()["_id"], company="Acme AG", role="X", method="direct"
    )
    assert run(runtime, "list") == 1
    run(runtime, "list", "--include-applied")
    assert "1 shown" in capsys.readouterr().out


def test_list_pagination_windows_the_output(runtime, board, capsys):
    board._feed_wire = [
        job(_id=f"62eccd7a57370f0152e4{i:04x}", jobUrl=f"role-{i}") for i in range(7)
    ]
    assert run(runtime, "list", "--json", "--page", "2", "--per-page", "3") == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["page"] == 2
    assert payload["total_pages"] == 3
    assert len(payload["jobs"]) == 3


# --- show / apply -----------------------------------------------------------


def test_show_renders_the_posting(runtime, capsys):
    assert run(runtime, "show", "acme") == 0
    out = capsys.readouterr().out
    assert "# Senior Python Engineer  @  Acme AG" in out
    assert "Build things" in out
    assert "https://swissdevjobs.ch/jobs/" in out


def test_show_unknown_id_fails_cleanly(runtime, capsys):
    assert run(runtime, "show", "zzz-no-match") == 1
    assert "No job matching" in capsys.readouterr().err


def test_apply_json_payload_is_apply_ready(runtime, capsys):
    assert run(runtime, "apply", "acme", "--json") == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["mode"] == "direct"
    assert payload["fallback_mode"] == "email"
    assert payload["apply_email"] == "jobs@acme.example"


def test_apply_complete_records_without_submitting(runtime, board, fresh_uow, capsys):
    assert run(runtime, "apply", "acme", "--complete", "email") == 0
    assert "Marked as applied via email" in capsys.readouterr().out
    assert board.sent == []
    assert fresh_uow.applications.get_by_job_id(job()["_id"]) is not None


# --- direct-apply -----------------------------------------------------------


def test_direct_apply_requires_identity(runtime, monkeypatch, capsys):
    for var in ("SDJ_NAME", "SDJ_EMAIL", "SDJ_CV"):
        monkeypatch.delenv(var, raising=False)
    assert run(runtime, "direct-apply", "acme", "--motivation", "Hi") == 1
    assert "--name/$SDJ_NAME" in capsys.readouterr().err


def test_direct_apply_submits_and_tracks(runtime, board, fresh_uow, tmp_path, capsys):
    cv = tmp_path / "cv.pdf"
    cv.write_bytes(b"%PDF-1.4")
    rc = run(
        runtime,
        "direct-apply",
        "acme",
        "--name",
        "Ada",
        "--email",
        "ada@example.com",
        "--cv",
        str(cv),
        "--motivation",
        "Hello there",
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "Submitting direct application to SwissDevJobs..." in out
    assert "✓ Submitted — HTTP 200" in out
    assert len(board.sent) == 1
    assert fresh_uow.applications.get_by_job_id(job()["_id"]).method == "direct"


def test_direct_apply_reads_the_motivation_from_a_file(runtime, board, tmp_path):
    cv = tmp_path / "cv.pdf"
    cv.write_bytes(b"%PDF-1.4")
    letter = tmp_path / "letter.txt"
    letter.write_text("Dear team\n")
    rc = run(
        runtime,
        "direct-apply",
        "acme",
        "--name",
        "Ada",
        "--email",
        "ada@example.com",
        "--cv",
        str(cv),
        "--motivation",
        str(letter),
    )
    assert rc == 0
    assert board.sent[0]["motivation"] == "Dear team"


def test_direct_apply_rejects_angle_brackets(runtime, board, tmp_path, capsys):
    cv = tmp_path / "cv.pdf"
    cv.write_bytes(b"%PDF-1.4")
    rc = run(
        runtime,
        "direct-apply",
        "acme",
        "--name",
        "Ada",
        "--email",
        "ada@example.com",
        "--cv",
        str(cv),
        "--motivation",
        "a <b> c",
    )
    assert rc == 1
    assert "must not contain < or >" in capsys.readouterr().err
    assert board.sent == []


def test_direct_apply_refuses_a_duplicate(runtime, board, fresh_uow, tmp_path, capsys):
    fresh_uow.applications.upsert(
        job_id=job()["_id"], company="Acme AG", role="X", method="direct"
    )
    cv = tmp_path / "cv.pdf"
    cv.write_bytes(b"%PDF-1.4")
    rc = run(
        runtime,
        "direct-apply",
        "acme",
        "--name",
        "Ada",
        "--email",
        "ada@example.com",
        "--cv",
        str(cv),
        "--motivation",
        "Hi",
    )
    assert rc == 1
    assert "Already applied" in capsys.readouterr().out
    assert board.sent == []


def test_direct_apply_refuses_an_undeliverable_posting(fresh_uow, tmp_path, capsys):
    board = FakeBoard(
        feed=[job()],
        detail_wire=job(
            candidateContactWay="CompanyWebsite",
            emailAddressForApplications=None,
            redirectJobUrl="https://acme.wd3.myworkdayjobs.com/x",
        ),
    )
    runtime = Runtime(
        boards={"swissdevjobs": board}, uow=fresh_uow, enabled=["swissdevjobs"]
    )
    cv = tmp_path / "cv.pdf"
    cv.write_bytes(b"%PDF-1.4")
    rc = run(
        runtime,
        "direct-apply",
        "acme",
        "--name",
        "Ada",
        "--email",
        "ada@example.com",
        "--cv",
        str(cv),
        "--motivation",
        "Hi",
    )
    assert rc == 2
    assert "Apply in a browser" in capsys.readouterr().err
    assert board.sent == []


# --- the rest ---------------------------------------------------------------


def test_tech_counts_tags(runtime, capsys):
    assert run(runtime, "tech", "--json") == 0
    top = dict(json.loads(capsys.readouterr().out))
    assert top["Python"] == 1


def test_applications_lists_records(runtime, fresh_uow, capsys):
    fresh_uow.applications.upsert(
        job_id="abc", company="Acme", role="Dev", method="email"
    )
    assert run(runtime, "applications") == 0
    assert "Acme" in capsys.readouterr().out


def test_stats_reports_counters(runtime, fresh_uow, capsys):
    fresh_uow.jobs.store_jobs([])
    assert run(runtime, "stats", "--json") == 0
    stats = json.loads(capsys.readouterr().out)
    assert stats["applications_total"] == 0


def test_config_shows_enabled_boards(runtime, capsys):
    assert run(runtime, "config") == 0
    out = capsys.readouterr().out
    assert "enabled      swissdevjobs" in out
    assert "SDJ_NAME" in out


def test_config_countries_rejects_unknown_codes(runtime, capsys):
    assert run(runtime, "config", "--countries", "ch,atlantis") == 1
    assert "unknown board selector" in capsys.readouterr().err


def test_config_boards_persists_and_countries_stays_an_alias(
    runtime, tmp_path, monkeypatch, capsys
):
    monkeypatch.setenv("SDJ_CONFIG_DIR", str(tmp_path))
    assert run(runtime, "config", "--boards", "jobsch,de") == 0
    assert "Wrote SDJ_BOARDS=jobsch,de" in capsys.readouterr().out
    assert "SDJ_BOARDS=jobsch,de" in (tmp_path / ".env").read_text()
    assert run(runtime, "config", "--countries", "ch,de") == 0
    assert "SDJ_BOARDS=ch,de" in (tmp_path / ".env").read_text()


def test_country_flag_narrows_the_boards(fresh_uow, capsys):
    ch = FakeBoard(feed=[job()], board=BOARDS["swissdevjobs"])
    de = FakeBoard(
        feed=[job(_id="68b0000057370f0152e4950e", jobUrl="de-role")],
        board=BOARDS["germantechjobs"],
    )
    runtime = Runtime(
        boards={"swissdevjobs": ch, "germantechjobs": de},
        uow=fresh_uow,
        enabled=["swissdevjobs", "germantechjobs"],
    )
    assert run(runtime, "list", "--country", "de", "--json") == 0
    payload = json.loads(capsys.readouterr().out)
    assert {r["country"] for r in payload["jobs"]} == {"de"}
    assert payload["boards_searched"] == ["germantechjobs"]


# --- plumbing ---------------------------------------------------------------


def test_open_prints_and_launches_the_url(runtime, monkeypatch, capsys):
    opened = []
    monkeypatch.setattr(cli.webbrowser, "open", lambda url, new=0: opened.append(url))
    assert run(runtime, "open", "acme") == 0
    url = "https://swissdevjobs.ch/jobs/acme-senior-python-engineer"
    assert capsys.readouterr().out.strip() == url
    assert opened == [url]


def test_with_retry_retries_once_after_an_unblock(runtime, monkeypatch):
    from swissdevjobs_cli.adapters.http.client import CaptchaRequired

    calls = []

    def flaky():
        calls.append(1)
        if len(calls) == 1:
            raise CaptchaRequired("https://swissdevjobs.ch/x", 403, "")
        return "ok"

    monkeypatch.setattr(cli, "interactive_unblock", lambda url: True)
    assert cli.with_retry(runtime, flaky) == "ok"
    assert len(calls) == 2


def test_with_retry_reraises_when_the_user_aborts(runtime, monkeypatch):
    from swissdevjobs_cli.adapters.http.client import CaptchaRequired

    def blocked():
        raise CaptchaRequired("https://swissdevjobs.ch/x", 403, "")

    monkeypatch.setattr(cli, "interactive_unblock", lambda url: False)
    with pytest.raises(CaptchaRequired):
        cli.with_retry(runtime, blocked)


def test_main_maps_an_unresolved_challenge_to_exit_2(runtime, monkeypatch, capsys):
    from swissdevjobs_cli.adapters.http.client import CaptchaRequired

    board = runtime.boards["swissdevjobs"]
    board.raises = CaptchaRequired("https://swissdevjobs.ch/", 403, "")
    monkeypatch.setattr(cli, "interactive_unblock", lambda url: False)
    monkeypatch.setattr(cli.bootstrap, "build_runtime", lambda: runtime)
    assert cli.main(["list"]) == 2
    assert "Cloudflare challenge unresolved" in capsys.readouterr().err


def test_main_runs_a_command_end_to_end(runtime, monkeypatch, capsys):
    monkeypatch.setattr(cli.bootstrap, "build_runtime", lambda: runtime)
    assert cli.main(["stats", "--json"]) == 0
    assert "applications_total" in capsys.readouterr().out


def test_config_init_writes_and_refuses_to_clobber(
    runtime, tmp_path, monkeypatch, capsys
):
    monkeypatch.setenv("SDJ_CONFIG_DIR", str(tmp_path))
    assert run(runtime, "config", "--init") == 0
    assert "Wrote" in capsys.readouterr().out
    assert run(runtime, "config", "--init") == 1
    assert "already exists" in capsys.readouterr().err


def test_interactive_unblock_stores_the_pasted_cookie(monkeypatch, capsys):
    stored = []
    monkeypatch.setattr(cli.webbrowser, "open", lambda url, new=0: True)
    monkeypatch.setattr(cli, "store_clearance", lambda f, v, d: stored.append((v, d)))
    monkeypatch.setattr("builtins.input", lambda *a: "  cookie-token  ")
    assert cli.interactive_unblock("https://germantechjobs.de/x") is True
    assert stored == [("cookie-token", ".germantechjobs.de")]
    assert "Cloudflare challenge detected." in capsys.readouterr().err


def test_interactive_unblock_aborts_on_empty_input(monkeypatch):
    monkeypatch.setattr(cli.webbrowser, "open", lambda url, new=0: True)
    monkeypatch.setattr("builtins.input", lambda *a: "")
    assert cli.interactive_unblock("https://swissdevjobs.ch/") is False


def test_interactive_unblock_aborts_on_eof(monkeypatch):
    def _eof(*a):
        raise EOFError

    monkeypatch.setattr(cli.webbrowser, "open", lambda url, new=0: True)
    monkeypatch.setattr("builtins.input", _eof)
    assert cli.interactive_unblock("https://swissdevjobs.ch/") is False


def test_auth_targets_the_requested_board(runtime, monkeypatch):
    seen = []
    monkeypatch.setattr(
        cli, "interactive_unblock", lambda url: seen.append(url) or True
    )
    assert run(runtime, "auth", "--country", "ch") == 0
    assert seen == ["https://swissdevjobs.ch/"]


def test_show_json_prints_the_raw_detail(runtime, capsys):
    assert run(runtime, "show", "acme", "--json") == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["description"] == "<p>Build things</p>"
    assert payload["country"] == "ch"


def test_list_sort_variants_run(runtime, capsys):
    for sort in ("salary", "date", "company"):
        assert run(runtime, "list", "--sort", sort) == 0
    capsys.readouterr()


def test_list_limit_caps_the_rows(runtime, board, capsys):
    board._feed_wire = [
        job(_id=f"62eccd7a57370f0152e4{i:04x}", jobUrl=f"role-{i}") for i in range(5)
    ]
    assert run(runtime, "list", "--limit", "2") == 0
    assert "2 shown · 5 match filters" in capsys.readouterr().out


def test_apply_text_mode_shows_fallback_and_questions(fresh_uow, capsys, monkeypatch):
    board = FakeBoard(
        feed=[job()],
        detail_wire=job(
            candidateContactWay="CompanyWebsite",
            emailAddressForApplications=None,
            redirectJobUrl="https://acme.example/apply",
            applyQuestions=[{"question": "Why us?"}],
        ),
    )
    runtime = Runtime(
        boards={"swissdevjobs": board}, uow=fresh_uow, enabled=["swissdevjobs"]
    )
    opened = []
    monkeypatch.setattr(cli.webbrowser, "open", lambda url, new=0: opened.append(url))
    assert run(runtime, "apply", "acme", "--open") == 0
    out = capsys.readouterr().out
    assert "Fallback:   ATS at https://acme.example/apply" in out
    assert "1. Why us?" in out
    assert opened == ["https://acme.example/apply"]


def test_applications_empty_state(runtime, capsys):
    assert run(runtime, "applications") == 0
    assert "No applications tracked yet." in capsys.readouterr().out


def test_tech_table_output(runtime, capsys):
    assert run(runtime, "tech") == 0
    assert "Python" in capsys.readouterr().out


def test_direct_apply_json_result_carries_the_application(
    runtime, board, tmp_path, capsys
):
    cv = tmp_path / "cv.pdf"
    cv.write_bytes(b"%PDF-1.4")
    rc = run(
        runtime,
        "direct-apply",
        "acme",
        "--json",
        "--name",
        "Ada",
        "--email",
        "ada@example.com",
        "--cv",
        str(cv),
        "--motivation",
        "Hi",
    )
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == 200
    assert payload["application"]["method"] == "direct"


def test_stats_table_output(runtime, capsys):
    assert run(runtime, "stats") == 0
    out = capsys.readouterr().out
    assert "Jobs cached:" in out
    assert "Database:" in out
