"""Typed identifiers and the ObjectId timestamp decoder.

Job ids come from the boards' MongoDB backend; the first 8 hex characters of
an ObjectId encode the creation time as unix epoch seconds. Unlike the
server-side ``activeFrom`` field — which is re-stamped whenever a listing is
bumped back to the top — that timestamp never changes, so it is the only
honest "posted at" signal the API offers.
"""

from __future__ import annotations

from typing import NewType

JobId = NewType("JobId", str)
ApplicationId = NewType("ApplicationId", int)


def posted_at_from_object_id(object_id: str) -> int | None:
    """Decode unix epoch seconds from a MongoDB ObjectId, or None if malformed."""
    try:
        return int(object_id[:8], 16)
    except (ValueError, TypeError):
        return None
