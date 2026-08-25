"""A BoardPort fake: canned feed, canned detail, recorded submissions."""

from __future__ import annotations

from swissdevjobs_cli.adapters.boards.registry import BOARDS
from swissdevjobs_cli.adapters.boards.worldwide.devitjobs import acl


class FakeBoard:
    """Serves wire-shaped fixtures through the real ACL, records every send.

    ``queries`` records every (query, category) pair fetch_jobs was called
    with, so tests can assert what reached a search-driven board.
    """

    def __init__(self, feed=None, detail_wire=None, board=None):
        self.board = board or BOARDS["swissdevjobs"]
        self._feed_wire = feed if feed is not None else []
        self._detail_wire = detail_wire
        self.sent = []
        self.queries = []
        self.filters = []
        self.raises = None

    def fetch_jobs(
        self, *, query=None, category=None, contract=None, workload=None, force=False
    ):
        if self.raises:
            raise self.raises
        self.queries.append((query, category))
        self.filters.append((contract, workload))
        return acl.jobs_from_wire(self._feed_wire, self.board)

    def fetch_detail(self, job_id):
        return acl.detail_from_wire(self._detail_wire, self.board)

    def hydrate_detail(self, raw):
        return acl.detail_from_wire(raw, self.board)

    def posting_url(self, raw):
        return acl.posting_url(self.board, raw.get("jobUrl") or "")

    def submit_application(self, detail, applicant, motivation):
        self.sent.append(
            {
                "name": applicant.name,
                "email": applicant.email,
                "motivation": motivation,
                "board": self.board.country,
            }
        )
        return {"status": 200, "response": "ok"}
