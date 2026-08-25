"""The plugin pin and the package version move together, or installs skew."""

from __future__ import annotations

from pathlib import Path

from swissdevjobs_cli import __version__

REPO = Path(__file__).resolve().parents[2]


def test_the_plugin_mcp_pin_matches_the_package_version():
    """The pin and the version bump belong to the same release commit.

    plugin/.mcp.json pins a git tag; a forgotten bump ships an old server
    against a skill written for main.
    """
    text = (REPO / "plugin" / ".mcp.json").read_text()
    assert f"@v{__version__}" in text


def test_the_plugin_and_marketplace_manifests_match_the_package_version():
    import json

    plugin = json.loads(
        (REPO / "plugin" / ".claude-plugin" / "plugin.json").read_text()
    )
    market = json.loads((REPO / ".claude-plugin" / "marketplace.json").read_text())
    assert plugin["version"] == __version__
    versions = {p["version"] for p in market["plugins"]}
    assert versions == {__version__}
