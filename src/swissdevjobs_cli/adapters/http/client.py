"""HTTP client: urllib + persistent cookie jar + Cloudflare challenge detection.

The boards are served through Cloudflare; under heavy load or automated
patterns CF may return a JS challenge ("Just a moment...") or a
managed-challenge interstitial. Those responses are detected and surfaced as
CaptchaRequired so the entrypoint can walk the user through clearing them.
"""

from __future__ import annotations

import contextlib
import gzip
import time
import urllib.error
import urllib.request
import uuid
from collections.abc import Mapping
from http.cookiejar import Cookie, MozillaCookieJar
from pathlib import Path
from typing import Any

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


class CaptchaRequired(Exception):
    """Raised when Cloudflare returns a challenge page instead of data."""

    def __init__(self, url: str, status: int, body_snippet: str):
        """Capture the URL, HTTP status, and a snippet of the challenge body."""
        self.url = url
        self.status = status
        self.body_snippet = body_snippet
        super().__init__(f"Cloudflare challenge at {url} (HTTP {status})")


def _looks_like_challenge(status: int, body: bytes, headers: Mapping[str, str]) -> bool:
    if status in (403, 503, 429):
        return True
    if headers.get("cf-mitigated", "").lower() == "challenge":
        return True
    sniff = body[:4096].lower()
    return (
        b"just a moment" in sniff
        or b"cf-chl-" in sniff
        or b"challenge-platform" in sniff
        or b"attention required" in sniff
    )


def build_multipart(
    fields: dict[str, str],
    files: dict[str, tuple[str, bytes, str]] | None = None,
) -> tuple[bytes, str]:
    """Build a multipart/form-data body.

    Args:
        fields: {field_name: value}
        files:  {field_name: (filename, data_bytes, mime_type)}

    Returns:
        (body_bytes, Content-Type header value)
    """
    boundary = uuid.uuid4().hex.encode()
    parts: list = []

    for name, value in fields.items():
        if value is None:
            continue
        header = (
            b"--" + boundary + b"\r\n"
            b'Content-Disposition: form-data; name="' + name.encode() + b'"\r\n\r\n'
        )
        parts.append(header + str(value).encode("utf-8") + b"\r\n")

    for field_name, (filename, data, mime_type) in (files or {}).items():
        header = (
            b"--" + boundary + b"\r\n"
            b'Content-Disposition: form-data; name="'
            + field_name.encode()
            + b'"; filename="'
            + filename.encode()
            + b'"\r\n'
            b"Content-Type: " + mime_type.encode() + b"\r\n\r\n"
        )
        parts.append(header + data + b"\r\n")

    body = b"".join(parts) + b"--" + boundary + b"--\r\n"
    content_type = f"multipart/form-data; boundary={boundary.decode()}"
    return body, content_type


class HttpClient:
    """One board's HTTP transport, sharing a Netscape cookie jar on disk."""

    def __init__(self, base_url: str, cookie_file: Path, user_agent: str = USER_AGENT):
        """One transport per board, sharing the on-disk cookie jar."""
        self.base_url = base_url
        self.cookie_file = cookie_file
        self.user_agent = user_agent

    def _jar(self) -> MozillaCookieJar:
        jar = MozillaCookieJar(str(self.cookie_file))
        if self.cookie_file.exists():
            with contextlib.suppress(Exception):
                jar.load(ignore_discard=True, ignore_expires=True)
        return jar

    def _opener(self, jar: MozillaCookieJar) -> urllib.request.OpenerDirector:
        return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))

    def get(self, path: str, *, accept_json: bool = True, timeout: int = 20) -> bytes:
        """GET a path (or absolute URL); raises CaptchaRequired on a challenge."""
        url = path if path.startswith("http") else f"{self.base_url}{path}"
        jar = self._jar()
        opener = self._opener(jar)
        # S310: the scheme is always https — base_url comes from the board
        # registry and `path` is a fixed API route, never user input.
        req = urllib.request.Request(  # noqa: S310
            url,
            headers={
                "User-Agent": self.user_agent,
                "Accept": (
                    "application/json, text/plain, */*" if accept_json else "*/*"
                ),
                "Accept-Language": "en-US,en;q=0.9,de;q=0.8",
                "Accept-Encoding": "gzip, deflate",
                "Referer": f"{self.base_url}/",
            },
        )
        try:
            resp = opener.open(req, timeout=timeout)  # noqa: S310 — scheme is fixed https, host comes from the board registry
            status = resp.status
            headers = {k.lower(): v for k, v in resp.headers.items()}
            raw = resp.read()
        except urllib.error.HTTPError as e:
            status = e.code
            headers = {
                k.lower(): v for k, v in (e.headers.items() if e.headers else [])
            }
            raw = e.read() or b""
            e.close()

        if headers.get("content-encoding") == "gzip":
            with contextlib.suppress(Exception):
                raw = gzip.decompress(raw)

        jar.save(ignore_discard=True, ignore_expires=True)

        if _looks_like_challenge(status, raw, headers):
            raise CaptchaRequired(
                url, status, raw[:500].decode("utf-8", errors="replace")
            )
        if status >= 400:
            raise RuntimeError(f"HTTP {status} for {url}: {raw[:200]!r}")
        return raw

    def post_multipart(
        self,
        path: str,
        fields: dict[str, str],
        files: dict[str, tuple[str, bytes, str]],
        *,
        referer: str,
        timeout: int = 30,
    ) -> dict[str, Any]:
        """POST multipart/form-data. Returns {"status": int, "response": str}."""
        body, content_type = build_multipart(fields, files)
        jar = self._jar()
        opener = self._opener(jar)
        # S310: same as get() — https-only, registry-controlled host.
        req = urllib.request.Request(  # noqa: S310
            f"{self.base_url}{path}",
            data=body,
            headers={
                "User-Agent": self.user_agent,
                "Content-Type": content_type,
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "en-US,en;q=0.9,de;q=0.8",
                "Referer": referer,
                "Origin": self.base_url,
            },
            method="POST",
        )
        try:
            resp = opener.open(req, timeout=timeout)  # noqa: S310 — scheme is fixed https, host comes from the board registry
            status = resp.status
            raw = resp.read()
        except urllib.error.HTTPError as e:
            status = e.code
            raw = e.read() or b""
            e.close()

        jar.save(ignore_discard=True, ignore_expires=True)

        if status >= 400:
            raise RuntimeError(
                f"HTTP {status} from {path}: "
                f"{raw[:300].decode('utf-8', errors='replace')!r}"
            )
        return {"status": status, "response": raw.decode("utf-8", errors="replace")}


def store_clearance(cookie_file: Path, value: str, domain: str) -> None:
    """Persist a cf_clearance cookie into the Netscape jar."""
    jar = MozillaCookieJar(str(cookie_file))
    if cookie_file.exists():
        with contextlib.suppress(Exception):
            jar.load(ignore_discard=True, ignore_expires=True)
    jar.set_cookie(
        Cookie(
            version=0,
            name="cf_clearance",
            value=value.strip(),
            port=None,
            port_specified=False,
            domain=domain,
            domain_specified=True,
            domain_initial_dot=domain.startswith("."),
            path="/",
            path_specified=True,
            secure=True,
            expires=int(time.time()) + 60 * 60 * 24 * 30,
            discard=False,
            comment=None,
            comment_url=None,
            rest={"HttpOnly": "", "SameSite": "None"},
            rfc2109=False,
        )
    )
    jar.save(ignore_discard=True, ignore_expires=True)
