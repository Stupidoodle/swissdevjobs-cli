"""Enabled-countries resolution and applicant identity."""

from __future__ import annotations

from swissdevjobs_cli.domain.model.application import Applicant
from swissdevjobs_cli.service_layer.config import enabled_countries, resolve_applicant

KNOWN = ["ch", "de", "uk", "us", "nl", "fr"]
LABELS = ("name/$SDJ_NAME", "email/$SDJ_EMAIL", "cv/$SDJ_CV")


def test_default_is_every_board(monkeypatch):
    monkeypatch.delenv("SDJ_COUNTRIES", raising=False)
    assert enabled_countries(KNOWN) == KNOWN


def test_all_means_every_board(monkeypatch):
    monkeypatch.setenv("SDJ_COUNTRIES", "all")
    assert enabled_countries(KNOWN) == KNOWN


def test_a_csv_selects_a_subset(monkeypatch):
    monkeypatch.setenv("SDJ_COUNTRIES", "ch, de")
    assert enabled_countries(KNOWN) == ["ch", "de"]


def test_unknown_codes_are_dropped_not_fatal(monkeypatch):
    monkeypatch.setenv("SDJ_COUNTRIES", "ch,atlantis")
    assert enabled_countries(KNOWN) == ["ch"]


def test_all_unknown_falls_back_to_every_board(monkeypatch):
    monkeypatch.setenv("SDJ_COUNTRIES", "atlantis")
    assert enabled_countries(KNOWN) == KNOWN


def test_identity_resolves_from_arguments():
    resolved = resolve_applicant("Ada", "ada@example.com", "/cv.pdf", labels=LABELS)
    assert isinstance(resolved, Applicant)
    assert resolved.name == "Ada"


def test_identity_falls_back_to_the_environment(monkeypatch):
    monkeypatch.setenv("SDJ_NAME", "Env Ada")
    monkeypatch.setenv("SDJ_EMAIL", "env@example.com")
    monkeypatch.setenv("SDJ_CV", "/env-cv.pdf")
    resolved = resolve_applicant(None, None, None, labels=LABELS)
    assert isinstance(resolved, Applicant)
    assert resolved.name == "Env Ada"


def test_missing_identity_reports_the_frontend_labels(monkeypatch):
    for var in ("SDJ_NAME", "SDJ_EMAIL", "SDJ_CV"):
        monkeypatch.delenv(var, raising=False)
    missing = resolve_applicant(None, None, None, labels=LABELS)
    assert missing == list(LABELS)
