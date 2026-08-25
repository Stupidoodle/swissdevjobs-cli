"""Composition root: the only module allowed to wire every layer together."""

from __future__ import annotations

from dataclasses import dataclass

from swissdevjobs_cli.adapters import envfile, paths
from swissdevjobs_cli.adapters.boards.registry import BOARDS, DEFAULT_COUNTRY
from swissdevjobs_cli.adapters.boards.worldwide.devitjobs.client import DevITJobsClient
from swissdevjobs_cli.adapters.http.client import HttpClient
from swissdevjobs_cli.adapters.persistence.unit_of_work import SqliteUnitOfWork
from swissdevjobs_cli.domain.model.board import Board
from swissdevjobs_cli.domain.ports.board_port import BoardPort
from swissdevjobs_cli.domain.ports.unit_of_work import UnitOfWork


@dataclass(frozen=True)
class Runtime:
    """Everything an entrypoint needs, wired once."""

    board: BoardPort
    uow: UnitOfWork

    @property
    def board_config(self) -> Board:
        """The active board's configuration."""
        return self.board.board


def build_runtime(country: str = DEFAULT_COUNTRY) -> Runtime:
    """Wire the real adapters for one board."""
    board = BOARDS[country]
    http = HttpClient(board.base_url, paths.COOKIE_FILE)
    client = DevITJobsClient(board, http)
    uow = SqliteUnitOfWork(paths.DB_PATH, paths.CACHE_DIR, paths.CONFIG_DIR, board)
    return Runtime(board=client, uow=uow)


def resolved_paths() -> dict:
    """The filesystem locations `sdj config` reports."""
    return {
        "cache_dir": str(paths.CACHE_DIR),
        "config_dir": str(paths.CONFIG_DIR),
        "cookie_file": str(paths.COOKIE_FILE),
        "db_path": str(paths.DB_PATH),
        "env_files_loaded": envfile.LOADED,
    }
