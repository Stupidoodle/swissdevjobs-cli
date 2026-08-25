"""Cloudflare challenge handler.

swissdevjobs.ch is behind Cloudflare. Under normal load the JSON API is open,
but bursts or datacenter IPs can trigger a managed challenge ("Just a moment...").
Since a headless HTTP client can't solve the CF JS challenge, this module
implements the documented UX: pause the CLI, open the URL in the user's default
browser, let them solve the challenge interactively, then paste the resulting
`cf_clearance` cookie back into the terminal. The cookie is persisted to the
Netscape-format jar in api.COOKIE_FILE so subsequent requests carry it.
"""

from __future__ import annotations

import contextlib
import sys
import time
import webbrowser
from http.cookiejar import Cookie, MozillaCookieJar

from . import api


def _store_clearance(value: str, domain: str = ".swissdevjobs.ch") -> None:
    jar = MozillaCookieJar(str(api.COOKIE_FILE))
    if api.COOKIE_FILE.exists():
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


def interactive_unblock(challenge_url: str) -> bool:
    """Block the CLI, open the URL in a browser, prompt for the cf_clearance cookie.

    Returns True once the cookie is stored so callers may retry; False if aborted.
    Designed to be safely called from any command — it is a synchronous gate.
    """
    print("", file=sys.stderr)
    print("Cloudflare challenge detected.", file=sys.stderr)
    print(f"Opening {challenge_url} in your default browser.", file=sys.stderr)
    print(
        "Solve the challenge, then in DevTools → Application → Cookies copy the\n"
        "value of 'cf_clearance' (on .swissdevjobs.ch) and paste it below.\n"
        "Press Enter with empty input to abort.",
        file=sys.stderr,
    )
    with contextlib.suppress(Exception):
        webbrowser.open(challenge_url, new=2)
    try:
        value = input("cf_clearance cookie value: ").strip()
    except (EOFError, KeyboardInterrupt):
        return False
    if not value:
        return False
    _store_clearance(value)
    print("Saved. Retrying request…", file=sys.stderr)
    return True


def with_retry(fn, *args, **kwargs):
    """Run `fn`; if it raises CaptchaRequired, prompt the user and retry once."""
    try:
        return fn(*args, **kwargs)
    except api.CaptchaRequired as e:
        if interactive_unblock(e.url):
            return fn(*args, **kwargs)
        raise
