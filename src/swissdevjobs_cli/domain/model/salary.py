"""Salary range with board-currency formatting."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class SalaryRange:
    """An annual salary range as published on a posting.

    Every posting on the devitjobs family must publish a range, but either
    bound can still be missing on syndicated listings.
    """

    lower: int | None
    upper: int | None
    currency: str = "CHF"

    @classmethod
    def from_wire(cls, wire: Mapping[str, Any], currency: str = "CHF") -> SalaryRange:
        """Build from a jobsLight/job-detail wire mapping."""
        return cls(
            lower=wire.get("annualSalaryFrom"),
            upper=wire.get("annualSalaryTo"),
            currency=currency,
        )

    def format(self) -> str:
        """Human-readable range, Swiss-style thousands separators, "—" if unknown."""
        if self.lower and self.upper:
            return f"{self.currency} {self.lower:,}–{self.upper:,}".replace(",", "'")
        if self.lower:
            return f"{self.currency} {self.lower:,}+".replace(",", "'")
        return "—"
