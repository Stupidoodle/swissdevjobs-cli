"""A BoardPort fake: canned feed, canned detail, recorded submissions."""

from __future__ import annotations

from swissdevjobs_cli.adapters.boards.registry import BOARDS
from swissdevjobs_cli.adapters.boards.worldwide.devitjobs import acl


class FakeBoard:
    """Serves wire-shaped fixtures through the real ACL, records every send."""

    def __init__(self, feed=None, detail_wire=None, board=None):
        self.board = board or BOARDS["ch"]
        self._feed_wire = feed if feed is not None else []
        self._detail_wire = detail_wire
        self.sent = []
        self.raises = None

    def fetch_jobs(self, *, force=False):
        if self.raises:
            raise self.raises
        return acl.jobs_from_wire(self._feed_wire, self.board)

    def fetch_detail(self, job_id):
        return acl.detail_from_wire(self._detail_wire, self.board)

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
