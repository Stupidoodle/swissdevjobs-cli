"""Board rows for the discovery surfaces (list_boards, sdj boards)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from swissdevjobs_cli.domain.model.board import Board


@dataclass(frozen=True)
class BoardDTO:
    """One board as data — what prose used to claim, now queryable."""

    source: str
    name: str
    country: str
    platform: str
    base_url: str
    currency: str
    scope: str
    salary_published: bool
    search_driven: bool
    native_apply: bool
    categories: list[str]
    enabled: bool

    @classmethod
    def from_domain(
        cls, board: Board, *, categories: list[str], enabled: bool
    ) -> BoardDTO:
        """Build from a registry Board plus its runtime state."""
        return cls(
            source=board.source,
            name=board.name,
            country=board.country,
            platform=board.platform,
            base_url=board.base_url,
            currency=board.currency,
            scope=board.scope,
            salary_published=board.salary_published,
            search_driven=board.search_driven,
            native_apply=board.native_apply,
            categories=categories,
            enabled=enabled,
        )

    def as_dict(self) -> dict[str, Any]:
        """The frozen wire shape, key order included."""
        return {
            "source": self.source,
            "name": self.name,
            "country": self.country,
            "platform": self.platform,
            "base_url": self.base_url,
            "currency": self.currency,
            "scope": self.scope,
            "salary_published": self.salary_published,
            "search_driven": self.search_driven,
            "native_apply": self.native_apply,
            "categories": self.categories,
            "enabled": self.enabled,
        }
