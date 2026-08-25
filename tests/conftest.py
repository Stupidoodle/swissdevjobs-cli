"""Test isolation.

swissdevjobs_cli resolves SDJ_CACHE_DIR / SDJ_CONFIG_DIR at *import* time
(adapters/paths.py) and runs envfile.load() from its __init__, so the
environment has to be redirected before the package is imported anywhere.
Setting it here at conftest module scope is what guarantees that — a fixture
would run far too late and the suite would read and write the developer's
real application database.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

_SANDBOX = Path(tempfile.mkdtemp(prefix="sdj-tests-"))
os.environ["SDJ_CACHE_DIR"] = str(_SANDBOX / "cache")
os.environ["SDJ_CONFIG_DIR"] = str(_SANDBOX / "config")
os.environ["SDJ_ENV_FILE"] = str(_SANDBOX / "nonexistent.env")
for _leaked in ("SDJ_NAME", "SDJ_EMAIL", "SDJ_CV"):
    os.environ.pop(_leaked, None)

import pytest  # noqa: E402

from swissdevjobs_cli.adapters import paths  # noqa: E402
from swissdevjobs_cli.adapters.boards.registry import BOARDS  # noqa: E402
from swissdevjobs_cli.adapters.boards.worldwide.devitjobs import acl  # noqa: E402
from swissdevjobs_cli.adapters.persistence.unit_of_work import (  # noqa: E402
    SqliteUnitOfWork,
)

CH = BOARDS["ch"]


def test_sandbox_is_active():
    """Guard: if this fails, every other test is writing to the real database."""
    assert str(_SANDBOX) in str(paths.DB_PATH)
    assert str(_SANDBOX) in str(paths.CACHE_DIR)
    assert str(_SANDBOX) in str(paths.COOKIE_FILE)


@pytest.fixture
def fresh_uow(tmp_path):
    """A brand-new database per test."""
    uow = SqliteUnitOfWork(tmp_path / "test.db", tmp_path, tmp_path / "config")
    yield uow
    uow.close()


def job(**overrides):
    """A jobsLight-shaped wire record with sensible defaults."""
    base = {
        "_id": "62eccd7a57370f0152e4950e",
        "jobUrl": "acme-senior-python-engineer",
        "company": "Acme AG",
        "name": "Senior Python Engineer",
        "actualCity": "Zurich",
        "cityCategory": "Zurich",
        "workplace": "hybrid",
        "language": "English",
        "expLevel": "Senior",
        "annualSalaryFrom": 130000,
        "annualSalaryTo": 160000,
        "technologies": ["Python", "Kubernetes"],
        "filterTags": ["Python", "Kubernetes", "AWS"],
        "candidateContactWay": "Email",
        "emailAddressForApplications": "jobs@acme.example",
        "redirectJobUrl": None,
        "hasVisaSponsorship": "No",
        "activeFrom": "2026-08-01T00:00:00.000Z",
    }
    base.update(overrides)
    return base


def domain_job(**overrides):
    """The same record, through the ACL, as a domain Job."""
    return acl.job_from_wire(job(**overrides), CH)


def domain_detail(**overrides):
    """The same record, through the ACL, as a domain JobDetail."""
    return acl.detail_from_wire(job(**overrides), CH)
