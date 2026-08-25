"""sdj config --countries persists via envfile.set_value."""

from __future__ import annotations

from swissdevjobs_cli.adapters import envfile


def test_set_value_creates_the_file_owner_only(tmp_path):
    target = tmp_path / ".env"
    envfile.set_value("SDJ_COUNTRIES", "ch,de", target)
    assert target.read_text() == "SDJ_COUNTRIES=ch,de\n"
    assert oct(target.stat().st_mode)[-3:] == "600"


def test_set_value_replaces_an_existing_line_in_place(tmp_path):
    target = tmp_path / ".env"
    target.write_text("SDJ_NAME=Ada\nSDJ_COUNTRIES=all\nSDJ_EMAIL=a@example.com\n")
    envfile.set_value("SDJ_COUNTRIES", "ch", target)
    assert (
        target.read_text()
        == "SDJ_NAME=Ada\nSDJ_COUNTRIES=ch\nSDJ_EMAIL=a@example.com\n"
    )


def test_set_value_handles_export_prefixed_lines(tmp_path):
    target = tmp_path / ".env"
    target.write_text("export SDJ_COUNTRIES=all\n")
    envfile.set_value("SDJ_COUNTRIES", "de", target)
    assert target.read_text() == "SDJ_COUNTRIES=de\n"


def test_set_value_appends_when_the_key_is_new(tmp_path):
    target = tmp_path / ".env"
    target.write_text("SDJ_NAME=Ada\n")
    envfile.set_value("SDJ_COUNTRIES", "nl", target)
    assert target.read_text() == "SDJ_NAME=Ada\nSDJ_COUNTRIES=nl\n"
