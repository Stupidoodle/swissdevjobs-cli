"""Reverse-engineered client for swissdevjobs.ch.

Endpoints discovered:
- GET /api/jobsLight              → array of all active jobs (lightweight fields)
- GET /api/job/{_id}              → full job detail incl. description, requirements, responsibilities
- GET /rss                        → RSS feed (alt source)
- POST /api/jobApply              → native SDJ direct apply (multipart/form-data)

Jobs are served through Cloudflare; under heavy load or automated patterns CF may
return a JS challenge ("Just a moment...") or a managed-challenge interstitial.
We detect those responses and surface them to the captcha handler.
"""
from __future__ import annotations

import contextlib
import gzip
import json
import os
import time
import urllib.parse
import urllib.request
import uuid
from http.cookiejar import MozillaCookieJar
from pathlib import Path
from typing import Any, Optional

BASE = "https://swissdevjobs.ch"
UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

CACHE_DIR = Path(os.environ.get("SDJ_CACHE_DIR", Path.home() / ".cache" / "swissdevjobs-cli"))
CONFIG_DIR = Path(os.environ.get("SDJ_CONFIG_DIR", Path.home() / ".config" / "swissdevjobs-cli"))
COOKIE_FILE = CONFIG_DIR / "cookies.txt"
CACHE_DIR.mkdir(parents=True, exist_ok=True)
CONFIG_DIR.mkdir(parents=True, exist_ok=True)


class CaptchaRequired(Exception):
    """Raised when Cloudflare returns a challenge page instead of data."""

    def __init__(self, url: str, status: int, body_snippet: str):
        self.url = url
        self.status = status
        self.body_snippet = body_snippet
        super().__init__(f"Cloudflare challenge at {url} (HTTP {status})")


def _jar() -> MozillaCookieJar:
    jar = MozillaCookieJar(str(COOKIE_FILE))
    if COOKIE_FILE.exists():
        with contextlib.suppress(Exception):
            jar.load(ignore_discard=True, ignore_expires=True)
    return jar


def _opener(jar: MozillaCookieJar) -> urllib.request.OpenerDirector:
    return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))


def _looks_like_challenge(status: int, body: bytes, headers: dict) -> bool:
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


def _get(path: str, *, accept_json: bool = True, timeout: int = 20) -> bytes:
    url = path if path.startswith("http") else f"{BASE}{path}"
    jar = _jar()
    opener = _opener(jar)
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": UA,
            "Accept": "application/json, text/plain, */*" if accept_json else "*/*",
            "Accept-Language": "en-US,en;q=0.9,de;q=0.8",
            "Accept-Encoding": "gzip, deflate",
            "Referer": f"{BASE}/",
        },
    )
    try:
        resp = opener.open(req, timeout=timeout)
        status = resp.status
        headers = {k.lower(): v for k, v in resp.headers.items()}
        raw = resp.read()
    except urllib.error.HTTPError as e:
        status = e.code
        headers = {k.lower(): v for k, v in (e.headers.items() if e.headers else [])}
        raw = e.read() or b""

    if headers.get("content-encoding") == "gzip":
        with contextlib.suppress(Exception):
            raw = gzip.decompress(raw)

    jar.save(ignore_discard=True, ignore_expires=True)

    if _looks_like_challenge(status, raw, headers):
        raise CaptchaRequired(url, status, raw[:500].decode("utf-8", errors="replace"))
    if status >= 400:
        raise RuntimeError(f"HTTP {status} for {url}: {raw[:200]!r}")
    return raw


def _cache_path(key: str) -> Path:
    safe = urllib.parse.quote(key, safe="")
    return CACHE_DIR / f"{safe}.json"


def _decorate_posted_at(jobs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Add `postedAt` (ISO) and `postedAtUnix` decoded from the MongoDB ObjectId.

    The first 8 hex chars of an ObjectId are a unix epoch (seconds). Unlike
    `activeFrom`, this never changes when SDJ re-promotes a listing.
    """
    from datetime import datetime, timezone
    for j in jobs:
        oid = j.get("_id") or ""
        try:
            ts = int(oid[:8], 16)
            j["postedAtUnix"] = ts
            j["postedAt"] = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
        except (ValueError, TypeError):
            j["postedAtUnix"] = None
            j["postedAt"] = None
    return jobs


def list_jobs(*, max_age_seconds: int = 600, force: bool = False) -> list[dict[str, Any]]:
    from . import db

    if not force:
        cached = db.get_cached_jobs(max_age_seconds)
        if cached is not None:
            return cached

    # On a forced refresh, bust Cloudflare's edge cache. `/api/jobsLight` is
    # served with `Cache-Control: max-age=3600` and CF will happily hand back a
    # HIT that is many hours stale (observed Age ~80k s), which would hide
    # freshly-posted jobs. A unique query string yields a distinct cache key →
    # MISS → origin-fresh data.
    path = "/api/jobsLight"
    if force:
        path += f"?_cb={int(time.time())}"
    data = json.loads(_get(path).decode("utf-8"))
    db.upsert_jobs_light(data)
    return _decorate_posted_at(data)


def get_job(job_id: str, *, max_age_seconds: int = 3600, force: bool = False) -> dict[str, Any]:
    from . import db

    if not force:
        cached = db.get_cached_detail(job_id, max_age_seconds)
        if cached is not None:
            return cached

    data = json.loads(_get(f"/api/job/{job_id}").decode("utf-8"))
    db.upsert_job_detail(job_id, data)
    return data


def job_url(slug_or_id: str) -> str:
    return f"{BASE}/jobs/{slug_or_id}"


def resolve_id(jobs: list[dict[str, Any]], query: str) -> Optional[dict[str, Any]]:
    q = query.lower()
    for j in jobs:
        if j["_id"] == query or j.get("jobUrl", "").lower() == q:
            return j
    for j in jobs:
        if q in j.get("jobUrl", "").lower() or q in j.get("name", "").lower():
            return j
    return None


def _build_multipart(
    fields: dict[str, str], files: dict[str, tuple[str, bytes, str]] | None = None
) -> tuple[bytes, str]:
    """Build a multipart/form-data body.

    Args:
        fields: {field_name: value}
        files:  {field_name: (filename, data_bytes, mime_type)}

    Returns:
        (body_bytes, Content-Type header value)
    """
    boundary = uuid.uuid4().hex.encode()
    parts: list[bytes] = []

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


def direct_apply(
    detail: dict[str, Any],
    *,
    name: str,
    email: str,
    motivation: str,
    cv_path: str,
    is_from_europe: bool = True,
    lang_skills: str = "native",
) -> dict[str, Any]:
    """Submit a direct application via POST /api/jobApply.

    Honeypot fields (yearsOfExperience, personal_website_url, address,
    required_confirmation) are intentionally left empty — they are hidden
    from real users via CSS and serve as bot traps.

    Args:
        detail:         Full job detail dict from get_job().
        name:           Applicant full name.
        email:          Applicant email address.
        motivation:     Cover letter text (no < > characters allowed).
        cv_path:        Absolute path to a PDF file.
        is_from_europe: Whether the applicant is EU/EEA/CH-based.
        lang_skills:    Self-rated proficiency in the posting's language
                        (e.g. "native", "fluent", "good", "basic"). Only
                        sent when the posting has hasLangCheck=true.

    Returns:
        {'status': int, 'response': str}
    """
    from pathlib import Path as _Path

    cv_bytes = _Path(cv_path).read_bytes()
    cv_filename = _Path(cv_path).name

    company_email = detail.get("emailAddressForApplications") or ""
    has_lang_check = detail.get("hasLangCheck", False)
    visa_sponsorship = detail.get("hasVisaSponsorship", "No")

    fields: dict[str, str] = {
        # Hidden metadata fields populated from job data
        "company": detail.get("company", ""),
        "jobName": detail.get("name", ""),
        "techCategory": detail.get("techCategory", ""),
        "hasLangCheck": "Yes" if has_lang_check else "No",
        "doesCompanyAcceptFromOutsideEurope": str(visa_sponsorship),
        "hasCompanyContactEmail": "true" if company_email else "false",
        # Visible fields
        "name": name,
        "email": email,
        "isFromEurope": "Yes" if is_from_europe else "No",
        "motivationLetter": motivation,
        "wantsNewsletter": "No",
    }
    if company_email:
        fields["companyEmail"] = company_email
    if has_lang_check:
        fields["langSkills"] = lang_skills

    files = {"cvFile": (cv_filename, cv_bytes, "application/pdf")}
    body, content_type = _build_multipart(fields, files)

    job_url_slug = detail.get("jobUrl", "")
    jar = _jar()
    opener = _opener(jar)
    req = urllib.request.Request(
        f"{BASE}/api/jobApply",
        data=body,
        headers={
            "User-Agent": UA,
            "Content-Type": content_type,
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9,de;q=0.8",
            "Referer": f"{BASE}/jobs/{job_url_slug}",
            "Origin": BASE,
        },
        method="POST",
    )
    try:
        resp = opener.open(req, timeout=30)
        status = resp.status
        raw = resp.read()
    except urllib.error.HTTPError as e:
        status = e.code
        raw = e.read() or b""

    jar.save(ignore_discard=True, ignore_expires=True)

    if status >= 400:
        raise RuntimeError(
            f"HTTP {status} from /api/jobApply: {raw[:300].decode('utf-8', errors='replace')!r}"
        )

    return {"status": status, "response": raw.decode("utf-8", errors="replace")}
