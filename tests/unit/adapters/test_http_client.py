"""HTTP transport against a real local server — no fakes, no network."""

from __future__ import annotations

import gzip
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from swissdevjobs_cli.adapters.http.client import (
    CaptchaRequired,
    HttpClient,
    build_multipart,
    store_clearance,
)


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # silence
        pass

    def do_GET(self):
        if self.path.startswith("/json"):
            body = json.dumps({"ok": True}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)
        elif self.path.startswith("/gzip"):
            body = gzip.compress(b'{"zipped": true}')
            self.send_response(200)
            self.send_header("Content-Encoding", "gzip")
            self.end_headers()
            self.wfile.write(body)
        elif self.path.startswith("/challenge"):
            self.send_response(403)
            self.end_headers()
            self.wfile.write(b"<html>Just a moment...</html>")
        elif self.path.startswith("/mitigated"):
            self.send_response(200)
            self.send_header("cf-mitigated", "challenge")
            self.end_headers()
            self.wfile.write(b"{}")
        else:
            self.send_response(500)
            self.end_headers()
            self.wfile.write(b"boom")

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        self.send_response(200)
        self.end_headers()
        # Echo back what field names arrived, so the test can assert them.
        self.wfile.write(json.dumps({"got": len(body)}).encode())


@pytest.fixture(scope="module")
def server():
    httpd = HTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_port}"
    httpd.shutdown()
    httpd.server_close()


@pytest.fixture
def client(server, tmp_path):
    return HttpClient(server, tmp_path / "cookies.txt")


def test_get_returns_the_body(client):
    assert json.loads(client.get("/json")) == {"ok": True}


def test_gzip_responses_are_decompressed(client):
    assert json.loads(client.get("/gzip")) == {"zipped": True}


def test_a_cloudflare_challenge_raises_captcha_required(client):
    with pytest.raises(CaptchaRequired):
        client.get("/challenge")


def test_the_cf_mitigated_header_also_raises(client):
    with pytest.raises(CaptchaRequired):
        client.get("/mitigated")


def test_server_errors_raise_runtime_error(client):
    with pytest.raises(RuntimeError):
        client.get("/boom")


def test_post_multipart_round_trips(client):
    result = client.post_multipart(
        "/apply",
        {"name": "Ada"},
        {"cvFile": ("cv.pdf", b"%PDF-1.4", "application/pdf")},
        referer="http://example/jobs/x",
    )
    assert result["status"] == 200
    assert json.loads(result["response"])["got"] > 0


def test_build_multipart_carries_fields_and_files():
    body, content_type = build_multipart(
        {"name": "Ada", "skip": None},
        {"cvFile": ("cv.pdf", b"%PDF-1.4", "application/pdf")},
    )
    assert b'name="name"' in body
    assert b"Ada" in body
    assert b"skip" not in body
    assert b'filename="cv.pdf"' in body
    assert content_type.startswith("multipart/form-data; boundary=")


def test_store_clearance_writes_a_netscape_cookie(tmp_path):
    jar_file = tmp_path / "cookies.txt"
    store_clearance(jar_file, "  token-value  ", ".swissdevjobs.ch")
    text = jar_file.read_text()
    assert "cf_clearance" in text
    assert "token-value" in text
    assert ".swissdevjobs.ch" in text
    # storing again must not crash on the existing jar
    store_clearance(jar_file, "second", ".swissdevjobs.ch")
