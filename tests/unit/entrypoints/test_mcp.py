"""MCP server tests. No network: a fake board port + a sandboxed database."""

from __future__ import annotations

import json

import pytest

from conftest import job
from fakes.fake_board_port import FakeBoard
from swissdevjobs_cli.adapters.http.client import CaptchaRequired
from swissdevjobs_cli.bootstrap import Runtime
from swissdevjobs_cli.entrypoints import mcp


@pytest.fixture
def board():
    return FakeBoard(
        feed=[job()],
        detail_wire=job(description="<p>Build things</p>", applyQuestions=[]),
    )


@pytest.fixture
def runtime(board, fresh_uow):
    return Runtime(boards={"ch": board}, uow=fresh_uow, enabled=["ch"])


def call(runtime, tool, /, **arguments):
    """Invoke a tool the way a client would, and decode its payload.

    `tool` is positional-only so it can't collide with a tool argument
    that is itself called `name`.
    """
    response = mcp.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": tool, "arguments": arguments},
        },
        runtime,
    )
    return json.loads(response["result"]["content"][0]["text"])


# --- protocol ---------------------------------------------------------------


def test_initialize_reports_the_protocol_version():
    result = mcp.handle_request({"jsonrpc": "2.0", "id": 1, "method": "initialize"})[
        "result"
    ]
    assert result["protocolVersion"] == mcp.PROTOCOL_VERSION
    assert result["serverInfo"]["name"] == "swissdevjobs"
    assert "tools" in result["capabilities"]


def test_notifications_get_no_response():
    assert (
        mcp.handle_request({"jsonrpc": "2.0", "method": "notifications/initialized"})
        is None
    )


def test_tools_list_is_well_formed():
    tools = mcp.handle_request({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})[
        "result"
    ]["tools"]
    assert {t["name"] for t in tools} == set(mcp.HANDLERS)
    for tool in tools:
        assert tool["description"]
        assert tool["inputSchema"]["type"] == "object"
        assert "handler" not in tool, "the callable must not leak into the wire format"


def test_only_the_write_tools_are_marked_mutating():
    tools = {t["name"]: t["annotations"] for t in mcp.TOOL_SPECS}
    assert tools["search_jobs"]["readOnlyHint"] is True
    assert tools["get_job"]["readOnlyHint"] is True
    assert tools["apply_to_job"]["readOnlyHint"] is False
    assert tools["apply_to_job"]["idempotentHint"] is False
    assert tools["mark_applied"]["readOnlyHint"] is False


def test_unknown_tool_is_a_protocol_error(runtime):
    response = mcp.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "nope"},
        },
        runtime,
    )
    assert response["error"]["code"] == -32602


def test_unknown_method_is_a_protocol_error():
    response = mcp.handle_request({"jsonrpc": "2.0", "id": 1, "method": "nope/nope"})
    assert response["error"]["code"] == -32601


def test_a_failing_tool_returns_an_error_result_not_a_crash(runtime, board):
    board.raises = RuntimeError("boom")
    response = mcp.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "search_jobs", "arguments": {}},
        },
        runtime,
    )
    assert response["result"]["isError"] is True
    assert "boom" in response["result"]["content"][0]["text"]


def test_a_cloudflare_challenge_tells_the_user_how_to_clear_it(runtime, board):
    board.raises = CaptchaRequired("https://swissdevjobs.ch/", 403, "")
    response = mcp.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "search_jobs", "arguments": {}},
        },
        runtime,
    )
    payload = json.loads(response["result"]["content"][0]["text"])
    assert payload["error"] == "cloudflare_challenge"
    assert "sdj auth" in payload["message"]


# --- tools ------------------------------------------------------------------


def test_search_returns_compact_rows(runtime):
    result = call(runtime, "search_jobs", min_salary=100000)
    assert result["total_matching"] == 1
    row = result["jobs"][0]
    assert row["salary"] == "CHF 130'000–160'000"
    assert row["url"].startswith("https://swissdevjobs.ch/jobs/")
    assert "description" not in row, "full text belongs to get_job, to save context"


def test_search_filters_are_applied(runtime):
    assert call(runtime, "search_jobs", tech=["rust"])["total_matching"] == 0
    assert call(runtime, "search_jobs", min_salary=200000)["total_matching"] == 0


def test_search_limit_is_clamped(runtime):
    assert call(runtime, "search_jobs", limit=9999)["returned"] <= 100


def test_get_job_returns_the_full_payload(runtime):
    result = call(runtime, "get_job", job_id="acme")
    assert result["mode"] == "direct"
    assert result["description"] == "Build things"


def test_get_job_rejects_an_unknown_id(runtime):
    response = mcp.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "get_job", "arguments": {"job_id": "zzz-no-match"}},
        },
        runtime,
    )
    assert response["result"]["isError"] is True


# --- the confirmation gate --------------------------------------------------


def test_applying_without_confirm_submits_nothing(runtime, board, tmp_path):
    cv = tmp_path / "cv.pdf"
    cv.write_bytes(b"%PDF-1.4")
    result = call(
        runtime,
        "apply_to_job",
        job_id="acme",
        motivation="Hello",
        cv_path=str(cv),
        name="Ada",
        email="ada@example.com",
    )
    assert result["error"] == "confirmation_required"
    assert result["would_submit"]["company"] == "Acme AG"
    assert result["would_submit"]["salary"] == "CHF 130'000–160'000"
    assert board.sent == []


def test_applying_with_confirm_submits(runtime, board, tmp_path):
    cv = tmp_path / "cv.pdf"
    cv.write_bytes(b"%PDF-1.4")
    result = call(
        runtime,
        "apply_to_job",
        job_id="acme",
        motivation="Hello",
        cv_path=str(cv),
        name="Ada",
        email="ada@example.com",
        confirm=True,
    )
    assert result["submitted"] is True
    assert len(board.sent) == 1
    assert board.sent[0]["name"] == "Ada"


def test_a_duplicate_is_reported_before_the_gate(runtime, board, fresh_uow, tmp_path):
    fresh_uow.applications.upsert(
        job_id=job()["_id"], company="Acme AG", role="X", method="direct"
    )
    cv = tmp_path / "cv.pdf"
    cv.write_bytes(b"%PDF-1.4")
    result = call(
        runtime,
        "apply_to_job",
        job_id="acme",
        motivation="Hello",
        cv_path=str(cv),
        confirm=True,
        name="Ada",
        email="ada@example.com",
    )
    assert result["already_applied"] is True
    assert board.sent == []


def test_an_undeliverable_posting_is_refused_even_with_confirm(fresh_uow, tmp_path):
    board = FakeBoard(
        feed=[job()],
        detail_wire=job(
            candidateContactWay="CompanyWebsite",
            emailAddressForApplications=None,
            redirectJobUrl="https://acme.wd3.myworkdayjobs.com/x",
        ),
    )
    runtime = Runtime(boards={"ch": board}, uow=fresh_uow, enabled=["ch"])
    cv = tmp_path / "cv.pdf"
    cv.write_bytes(b"%PDF-1.4")
    result = call(
        runtime,
        "apply_to_job",
        job_id="acme",
        motivation="Hello",
        cv_path=str(cv),
        confirm=True,
        name="Ada",
        email="ada@example.com",
    )
    assert result["error"] == "company_website_posting"
    assert board.sent == []


def test_a_missing_cv_is_caught_before_the_gate(runtime, board):
    result = call(
        runtime,
        "apply_to_job",
        job_id="acme",
        motivation="Hello",
        cv_path="/nonexistent.pdf",
        name="Ada",
        email="ada@example.com",
    )
    assert result["error"] == "cv_not_found"
    assert board.sent == []


def test_angle_brackets_in_the_letter_are_rejected(runtime, board, tmp_path):
    cv = tmp_path / "cv.pdf"
    cv.write_bytes(b"%PDF-1.4")
    result = call(
        runtime,
        "apply_to_job",
        job_id="acme",
        motivation="a <b> c",
        cv_path=str(cv),
        name="Ada",
        email="ada@example.com",
    )
    assert result["error"] == "invalid_motivation"
    assert board.sent == []


def test_missing_identity_is_reported(runtime, board, tmp_path, monkeypatch):
    monkeypatch.delenv("SDJ_NAME", raising=False)
    monkeypatch.delenv("SDJ_EMAIL", raising=False)
    cv = tmp_path / "cv.pdf"
    cv.write_bytes(b"%PDF-1.4")
    result = call(
        runtime, "apply_to_job", job_id="acme", motivation="Hello", cv_path=str(cv)
    )
    assert result["error"] == "missing_identity"
    assert board.sent == []


# --- the stdio loop ---------------------------------------------------------


def test_serve_answers_line_delimited_json(capsys):
    import io

    stdin = io.StringIO(
        '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}\n'
        "\n"
        "not json\n"
        '{"jsonrpc":"2.0","id":2,"method":"tools/list"}\n'
        '{"jsonrpc":"2.0","method":"notifications/initialized"}\n'
        '{"jsonrpc":"2.0","id":3,"method":"ping"}\n'
    )
    out = io.StringIO()
    assert mcp.serve(stdin=stdin, stdout=out) == 0
    lines = [json.loads(line) for line in out.getvalue().splitlines()]
    by_id = {m.get("id"): m for m in lines}
    assert by_id[1]["result"]["serverInfo"]["name"] == "swissdevjobs"
    assert {t["name"] for t in by_id[2]["result"]["tools"]} == set(mcp.HANDLERS)
    assert by_id[None]["error"]["code"] == -32700
    assert by_id[3]["result"] == {}


def test_search_can_target_one_country(runtime):
    assert call(runtime, "search_jobs", country="ch")["total_matching"] == 1


def test_search_rejects_an_unknown_country(runtime):
    response = mcp.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "search_jobs", "arguments": {"country": "atlantis"}},
        },
        runtime,
    )
    assert response["result"]["isError"] is True


def test_the_preview_names_the_board(runtime, tmp_path):
    cv = tmp_path / "cv.pdf"
    cv.write_bytes(b"%PDF-1.4")
    result = call(
        runtime,
        "apply_to_job",
        job_id="acme",
        motivation="Hello",
        cv_path=str(cv),
        name="Ada",
        email="ada@example.com",
    )
    assert result["would_submit"]["board"] == "SwissDevJobs (ch)"


def test_non_default_language_skills_reach_the_board(runtime, board, tmp_path):
    cv = tmp_path / "cv.pdf"
    cv.write_bytes(b"%PDF-1.4")
    result = call(
        runtime,
        "apply_to_job",
        job_id="acme",
        motivation="Hello",
        cv_path=str(cv),
        name="Ada",
        email="ada@example.com",
        lang_skills="fluent",
        is_from_europe=False,
        confirm=True,
    )
    assert result["submitted"] is True


def test_force_overrides_a_duplicate(runtime, board, fresh_uow, tmp_path):
    fresh_uow.applications.upsert(
        job_id=job()["_id"], company="Acme AG", role="X", method="direct"
    )
    cv = tmp_path / "cv.pdf"
    cv.write_bytes(b"%PDF-1.4")
    result = call(
        runtime,
        "apply_to_job",
        job_id="acme",
        motivation="Hello",
        cv_path=str(cv),
        name="Ada",
        email="ada@example.com",
        confirm=True,
        force=True,
    )
    assert result["submitted"] is True
    assert len(board.sent) == 1


def test_mark_applied_records_via_the_jobs_board(runtime, fresh_uow):
    result = call(runtime, "mark_applied", job_id="acme", method="linkedin")
    assert result["method"] == "linkedin"
    assert result["source"] == "swissdevjobs"
    assert fresh_uow.applications.get_by_job_id(job()["_id"]) is not None


def test_list_applications_returns_the_ledger(runtime, fresh_uow):
    fresh_uow.applications.upsert(
        job_id="abc", company="Acme", role="Dev", method="email"
    )
    result = call(runtime, "list_applications")
    assert result["count"] == 1
    assert result["applications"][0]["company"] == "Acme"


def test_top_technologies_counts_tags(runtime):
    result = call(runtime, "top_technologies", limit=2)
    names = {t["name"] for t in result["technologies"]}
    assert "Python" in names


def test_resources_and_prompts_are_empty_but_answered():
    for method in ("resources/list", "prompts/list"):
        response = mcp.handle_request({"jsonrpc": "2.0", "id": 1, "method": method})
        assert response["result"] == {"resources": [], "prompts": []}
