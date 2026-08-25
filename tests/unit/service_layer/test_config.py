"""Selector-token parsing and applicant identity."""

from __future__ import annotations

from swissdevjobs_cli.domain.model.application import Applicant
from swissdevjobs_cli.service_layer.config import resolve_applicant, selector_tokens

LABELS = ("name/$SDJ_NAME", "email/$SDJ_EMAIL", "cv/$SDJ_CV")


def test_default_is_all(monkeypatch):
    monkeypatch.delenv("SDJ_COUNTRIES", raising=False)
    assert selector_tokens() == ["all"]


def test_a_csv_yields_cleaned_tokens(monkeypatch):
    monkeypatch.setenv("SDJ_COUNTRIES", " CH, jobsch ,, de ")
    assert selector_tokens() == ["ch", "jobsch", "de"]


def test_an_empty_variable_means_all(monkeypatch):
    monkeypatch.setenv("SDJ_COUNTRIES", "   ")
    assert selector_tokens() == ["all"]


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
