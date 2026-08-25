"""Spec-compliance behavior pinned by the 2025-06-18 MCP audit."""

from __future__ import annotations

import io
import json

from swissdevjobs_cli.entrypoints import mcp


def call_raw(message):
    return mcp.handle_request(message)


def test_a_non_object_json_line_answers_32600_not_a_crash():
    stdin = io.StringIO('[]\n42\n{"jsonrpc":"2.0","id":1,"method":"ping"}\n')
    stdout = io.StringIO()
    mcp.serve(stdin=stdin, stdout=stdout)
    lines = [json.loads(x) for x in stdout.getvalue().splitlines()]
    assert lines[0]["error"]["code"] == -32600
    assert lines[1]["error"]["code"] == -32600
    assert lines[2] == {"jsonrpc": "2.0", "id": 1, "result": {}}


def test_initialize_echoes_a_supported_requested_version():
    res = call_raw(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": mcp.PROTOCOL_VERSION},
        }
    )
    assert res["result"]["protocolVersion"] == mcp.PROTOCOL_VERSION


def test_initialize_answers_our_version_to_an_unsupported_request():
    res = call_raw(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": "2099-01-01"},
        }
    )
    assert res["result"]["protocolVersion"] == mcp.PROTOCOL_VERSION


def test_an_unknown_cursor_on_tools_list_is_32602():
    res = call_raw(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/list",
            "params": {"cursor": "garbage"},
        }
    )
    assert res["error"]["code"] == -32602


def test_resources_and_prompts_lists_keep_their_own_keys():
    resources = call_raw(
        {"jsonrpc": "2.0", "id": 1, "method": "resources/list", "params": {}}
    )
    prompts = call_raw(
        {"jsonrpc": "2.0", "id": 2, "method": "prompts/list", "params": {}}
    )
    assert resources["result"] == {"resources": []}
    assert prompts["result"] == {"prompts": []}


def test_apply_to_job_does_not_claim_to_be_non_destructive():
    spec = mcp.SPECS["apply_to_job"]
    assert "destructiveHint" not in spec["annotations"], (
        "the spec default (true) must apply — an irreversible submission "
        "marked 'only additive' invites clients to skip confirmation UI"
    )


def test_an_invalid_enum_value_is_a_loud_error_not_zero_matches():
    res = call_raw(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "search_jobs", "arguments": {"level": "Staff"}},
        }
    )
    body = json.loads(res["result"]["content"][0]["text"])
    assert res["result"]["isError"] is True
    assert body["error"] == "invalid_arguments"
    assert "Junior" in body["message"], "the message must name the valid values"


def test_a_wrong_argument_type_is_named():
    res = call_raw(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "search_jobs", "arguments": {"limit": "ten"}},
        }
    )
    body = json.loads(res["result"]["content"][0]["text"])
    assert body["error"] == "invalid_arguments"
    assert "limit expects type integer" in body["message"]


def test_a_missing_required_argument_is_named():
    res = call_raw(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "get_job", "arguments": {}},
        }
    )
    body = json.loads(res["result"]["content"][0]["text"])
    assert body["error"] == "invalid_arguments"
    assert "job_id" in body["message"]


def test_an_unknown_argument_lists_the_known_ones():
    res = call_raw(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "search_jobs", "arguments": {"salary_min": 1}},
        }
    )
    body = json.loads(res["result"]["content"][0]["text"])
    assert body["error"] == "invalid_arguments"
    assert "min_salary" in body["message"]
