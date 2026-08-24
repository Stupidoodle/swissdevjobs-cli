"""MCP server tests. No network: api and db are stubbed per test."""
from __future__ import annotations

import json

import pytest

from conftest import job
from swissdevjobs_cli import mcp


@pytest.fixture
def stub(monkeypatch):
    """Stub the network and the database; record any submission attempt."""
    sent = []

    monkeypatch.setattr(mcp.api, "list_jobs", lambda **kw: [job()])
    monkeypatch.setattr(mcp.api, "get_job", lambda jid, **kw: job(
        description="<p>Build things</p>", applyQuestions=[],
    ))
    monkeypatch.setattr(mcp.db, "is_applied", lambda jid: None)
    monkeypatch.setattr(mcp.db, "is_job_applied", lambda j: False)
    monkeypatch.setattr(mcp.db, "mark_applied", lambda **kw: {"id": 1, **kw})

    def _record(*args, **kwargs):
        sent.append(kwargs)
        return {"status": 200, "response": "ok"}

    monkeypatch.setattr(mcp.api, "direct_apply", _record)
    return sent


def call(tool, /, **arguments):
    """Invoke a tool the way a client would, and decode its payload.

    `tool` is positional-only so it can't collide with a tool argument
    that is itself called `name`.
    """
    response = mcp.handle_request({
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": tool, "arguments": arguments},
    })
    return json.loads(response["result"]["content"][0]["text"])


# --- protocol ---------------------------------------------------------------


def test_initialize_reports_the_protocol_version():
    result = mcp.handle_request({"jsonrpc": "2.0", "id": 1, "method": "initialize"})["result"]
    assert result["protocolVersion"] == mcp.PROTOCOL_VERSION
    assert result["serverInfo"]["name"] == "swissdevjobs"
    assert "tools" in result["capabilities"]


def test_notifications_get_no_response():
    assert mcp.handle_request({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None


def test_tools_list_is_well_formed():
    tools = mcp.handle_request({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})["result"]["tools"]
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


def test_unknown_tool_is_a_protocol_error():
    response = mcp.handle_request({
        "jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "nope"},
    })
    assert response["error"]["code"] == -32602


def test_unknown_method_is_a_protocol_error():
    response = mcp.handle_request({"jsonrpc": "2.0", "id": 1, "method": "nope/nope"})
    assert response["error"]["code"] == -32601


def test_a_failing_tool_returns_an_error_result_not_a_crash(monkeypatch):
    monkeypatch.setattr(mcp.api, "list_jobs", lambda **kw: (_ for _ in ()).throw(RuntimeError("boom")))
    response = mcp.handle_request({
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": "search_jobs", "arguments": {}},
    })
    assert response["result"]["isError"] is True
    assert "boom" in response["result"]["content"][0]["text"]


def test_a_cloudflare_challenge_tells_the_user_how_to_clear_it(monkeypatch):
    def _blocked(**kw):
        raise mcp.api.CaptchaRequired("https://swissdevjobs.ch/", 403, "")

    monkeypatch.setattr(mcp.api, "list_jobs", _blocked)
    response = mcp.handle_request({
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": "search_jobs", "arguments": {}},
    })
    payload = json.loads(response["result"]["content"][0]["text"])
    assert payload["error"] == "cloudflare_challenge"
    assert "sdj auth" in payload["message"]


# --- tools ------------------------------------------------------------------


def test_search_returns_compact_rows(stub):
    result = call("search_jobs", min_salary=100000)
    assert result["total_matching"] == 1
    row = result["jobs"][0]
    assert row["salary"] == "CHF 130'000–160'000"
    assert row["url"].startswith("https://swissdevjobs.ch/jobs/")
    assert "description" not in row, "full text belongs to get_job, to save context"


def test_search_filters_are_applied(stub):
    assert call("search_jobs", tech=["rust"])["total_matching"] == 0
    assert call("search_jobs", min_salary=200000)["total_matching"] == 0


def test_search_limit_is_clamped(stub):
    assert call("search_jobs", limit=9999)["returned"] <= 100


def test_get_job_returns_the_full_payload(stub):
    result = call("get_job", job_id="acme")
    assert result["mode"] == "direct"
    assert result["description"] == "Build things"


def test_get_job_rejects_an_unknown_id(monkeypatch, stub):
    monkeypatch.setattr(mcp.api, "resolve_id", lambda jobs, q: None)
    response = mcp.handle_request({
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": "get_job", "arguments": {"job_id": "nope"}},
    })
    assert response["result"]["isError"] is True


# --- the confirmation gate --------------------------------------------------


def test_applying_without_confirm_submits_nothing(stub, tmp_path):
    cv = tmp_path / "cv.pdf"
    cv.write_bytes(b"%PDF-1.4")
    result = call("apply_to_job", job_id="acme", motivation="Hello",
                  cv_path=str(cv), name="Ada", email="ada@example.com")
    assert result["error"] == "confirmation_required"
    assert result["would_submit"]["company"] == "Acme AG"
    assert result["would_submit"]["salary"] == "CHF 130'000–160'000"
    assert sent_nothing(stub)


def test_applying_with_confirm_submits(stub, tmp_path):
    cv = tmp_path / "cv.pdf"
    cv.write_bytes(b"%PDF-1.4")
    result = call("apply_to_job", job_id="acme", motivation="Hello", cv_path=str(cv),
                  name="Ada", email="ada@example.com", confirm=True)
    assert result["submitted"] is True
    assert len(stub) == 1
    assert stub[0]["name"] == "Ada"


def test_a_duplicate_is_reported_before_the_gate(stub, monkeypatch, tmp_path):
    monkeypatch.setattr(mcp.db, "is_applied", lambda jid: {"id": 3, "method": "direct"})
    cv = tmp_path / "cv.pdf"
    cv.write_bytes(b"%PDF-1.4")
    result = call("apply_to_job", job_id="acme", motivation="Hello", cv_path=str(cv),
                  confirm=True, name="Ada", email="ada@example.com")
    assert result["already_applied"] is True
    assert sent_nothing(stub)


def test_an_undeliverable_posting_is_refused_even_with_confirm(stub, monkeypatch, tmp_path):
    monkeypatch.setattr(mcp.api, "get_job", lambda jid, **kw: job(
        candidateContactWay="CompanyWebsite", emailAddressForApplications=None,
        redirectJobUrl="https://acme.wd3.myworkdayjobs.com/x",
    ))
    cv = tmp_path / "cv.pdf"
    cv.write_bytes(b"%PDF-1.4")
    result = call("apply_to_job", job_id="acme", motivation="Hello", cv_path=str(cv),
                  confirm=True, name="Ada", email="ada@example.com")
    assert result["error"] == "company_website_posting"
    assert sent_nothing(stub)


def test_a_missing_cv_is_caught_before_the_gate(stub):
    result = call("apply_to_job", job_id="acme", motivation="Hello",
                  cv_path="/nonexistent.pdf", name="Ada", email="ada@example.com")
    assert result["error"] == "cv_not_found"
    assert sent_nothing(stub)


def test_angle_brackets_in_the_letter_are_rejected(stub, tmp_path):
    cv = tmp_path / "cv.pdf"
    cv.write_bytes(b"%PDF-1.4")
    result = call("apply_to_job", job_id="acme", motivation="a <b> c", cv_path=str(cv),
                  name="Ada", email="ada@example.com")
    assert result["error"] == "invalid_motivation"
    assert sent_nothing(stub)


def test_missing_identity_is_reported(stub, tmp_path, monkeypatch):
    monkeypatch.delenv("SDJ_NAME", raising=False)
    monkeypatch.delenv("SDJ_EMAIL", raising=False)
    cv = tmp_path / "cv.pdf"
    cv.write_bytes(b"%PDF-1.4")
    result = call("apply_to_job", job_id="acme", motivation="Hello", cv_path=str(cv))
    assert result["error"] == "missing_identity"
    assert sent_nothing(stub)


def sent_nothing(recorded) -> bool:
    return recorded == []
