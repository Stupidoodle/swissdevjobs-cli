"""Application DTO: the frozen dict shape of one tracked application."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from swissdevjobs_cli.domain.model.application import ApplicationRecord


@dataclass(frozen=True)
class ApplicationDTO:
    """Thin wrapper — the record's dict form IS the wire shape."""

    record: ApplicationRecord

    def as_dict(self) -> dict[str, Any]:
        """The frozen wire shape."""
        return self.record.as_dict()


def as_dict_or_none(record: ApplicationRecord | None) -> dict[str, Any] | None:
    """Convenience for the many payload slots holding `application | None`."""
    return record.as_dict() if record is not None else None
