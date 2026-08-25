"""Composition root: the only module allowed to wire every layer together."""

from __future__ import annotations

from dataclasses import dataclass, field

from swissdevjobs_cli.adapters import envfile, paths
from swissdevjobs_cli.adapters.boards.registry import BOARDS
from swissdevjobs_cli.adapters.boards.worldwide.devitjobs.client import DevITJobsClient
from swissdevjobs_cli.adapters.http.client import HttpClient
from swissdevjobs_cli.adapters.persistence.unit_of_work import SqliteUnitOfWork
from swissdevjobs_cli.domain.model.job import Job
from swissdevjobs_cli.domain.ports.board_port import BoardPort
from swissdevjobs_cli.domain.ports.unit_of_work import UnitOfWork
from swissdevjobs_cli.service_layer import config as config_service


@dataclass(frozen=True)
class Runtime:
    """Everything an entrypoint needs, wired once.

    ``boards`` holds a client for every known board so a cached job from a
    currently-disabled country can still be shown or applied to; ``enabled``
    is the subset searches actually query.
    """

    boards: dict[str, BoardPort]
    uow: UnitOfWork
    enabled: list = field(default_factory=list)

    def enabled_boards(self) -> list:
        """The clients searches fan out over, in registry order."""
        countries = self.enabled or list(self.boards)
        return [self.boards[c] for c in countries if c in self.boards]

    def board_for(self, job: Job) -> BoardPort:
        """The client responsible for one job's board."""
        return self.boards[job.board.country]


def build_runtime(countries: list | None = None) -> Runtime:
    """Wire the real adapters for every board; enable per config."""
    clients: dict[str, BoardPort] = {}
    for code, board in BOARDS.items():
        http = HttpClient(board.base_url, paths.COOKIE_FILE)
        clients[code] = DevITJobsClient(board, http)
    uow = SqliteUnitOfWork(paths.DB_PATH, paths.CACHE_DIR, paths.CONFIG_DIR)
    enabled = countries or config_service.enabled_countries(list(BOARDS))
    return Runtime(boards=clients, uow=uow, enabled=enabled)


def resolved_paths() -> dict:
    """The filesystem locations `sdj config` reports."""
    return {
        "cache_dir": str(paths.CACHE_DIR),
        "config_dir": str(paths.CONFIG_DIR),
        "cookie_file": str(paths.COOKIE_FILE),
        "db_path": str(paths.DB_PATH),
        "env_files_loaded": envfile.LOADED,
    }
