"""Offline tests for dotenv."""

from __future__ import annotations

import os

from swissdevjobs_cli import dotenv


def test_parse_handles_the_shapes_a_real_env_file_uses():
    parsed = dotenv.parse(
        "\n".join(
            [
                "# a comment",
                "",
                'SDJ_NAME="Ada Lovelace"',
                "export SDJ_EMAIL=ada@example.com",
                "SDJ_CV='/tmp/cv.pdf'",
                "SDJ_CACHE_DIR=/tmp/cache   # trailing comment",
                "not a pair",
                'SDJ_MULTI="line one\\nline two"',
            ]
        )
    )
    assert parsed["SDJ_NAME"] == "Ada Lovelace"
    assert parsed["SDJ_EMAIL"] == "ada@example.com"
    assert parsed["SDJ_CV"] == "/tmp/cv.pdf"
    assert parsed["SDJ_CACHE_DIR"] == "/tmp/cache"
    assert parsed["SDJ_MULTI"] == "line one\nline two"
    assert "not a pair" not in parsed


def test_single_quotes_do_not_process_escapes():
    assert dotenv.parse(r"X='a\nb'")["X"] == r"a\nb"


def test_load_fills_unset_keys(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("SDJ_NAME=From File\n")
    monkeypatch.setenv("SDJ_ENV_FILE", str(env))
    monkeypatch.delenv("SDJ_NAME", raising=False)
    monkeypatch.setattr(dotenv, "LOADED", [])
    monkeypatch.chdir(tmp_path)

    dotenv.load()
    assert os.environ["SDJ_NAME"] == "From File"


def test_the_real_environment_always_wins(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("SDJ_NAME=From File\n")
    monkeypatch.setenv("SDJ_ENV_FILE", str(env))
    monkeypatch.setenv("SDJ_NAME", "From Shell")
    monkeypatch.setattr(dotenv, "LOADED", [])
    monkeypatch.chdir(tmp_path)

    dotenv.load()
    assert os.environ["SDJ_NAME"] == "From Shell"


def test_an_earlier_file_wins_over_a_later_one(tmp_path, monkeypatch):
    explicit = tmp_path / "explicit.env"
    explicit.write_text("SDJ_NAME=Explicit\n")
    config = tmp_path / "config"
    config.mkdir()
    (config / ".env").write_text("SDJ_NAME=Config\nSDJ_EMAIL=only-here@example.com\n")

    monkeypatch.setenv("SDJ_ENV_FILE", str(explicit))
    monkeypatch.setenv("SDJ_CONFIG_DIR", str(config))
    monkeypatch.delenv("SDJ_NAME", raising=False)
    monkeypatch.delenv("SDJ_EMAIL", raising=False)
    monkeypatch.setattr(dotenv, "LOADED", [])
    monkeypatch.chdir(tmp_path)

    dotenv.load()
    assert os.environ["SDJ_NAME"] == "Explicit"
    # the later file still fills in keys the earlier one didn't set
    assert os.environ["SDJ_EMAIL"] == "only-here@example.com"


def test_missing_files_are_not_an_error(tmp_path, monkeypatch):
    monkeypatch.setenv("SDJ_ENV_FILE", str(tmp_path / "nope.env"))
    monkeypatch.setenv("SDJ_CONFIG_DIR", str(tmp_path / "nope"))
    monkeypatch.setattr(dotenv, "LOADED", [])
    monkeypatch.chdir(tmp_path)
    assert dotenv.load() == []


def test_write_template_refuses_to_clobber(tmp_path):
    target = tmp_path / ".env"
    dotenv.write_template(target)
    assert "SDJ_NAME" in target.read_text()
    assert oct(target.stat().st_mode)[-3:] == "600"
    try:
        dotenv.write_template(target)
    except FileExistsError:
        pass
    else:
        raise AssertionError("expected FileExistsError")
