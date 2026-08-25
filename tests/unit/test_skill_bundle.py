"""The plugin bundles the same skill assets the repo publishes, or they drift."""

from __future__ import annotations

from pathlib import Path

from swissdevjobs_cli.adapters.boards import registry

REPO = Path(__file__).resolve().parents[2]


def test_the_plugin_bundles_the_same_cv_convention_files():
    """skill/cv/ is the source of truth; the plugin ships a byte-equal copy."""
    src = {p.name: p.read_text() for p in (REPO / "skill" / "cv").glob("*.md")}
    dst = {
        p.name: p.read_text()
        for p in (REPO / "plugin" / "skills" / "swissdevjobs" / "cv").glob("*.md")
    }
    assert src, "the cv convention files must exist"
    assert src == dst


def test_every_board_country_has_a_cv_convention_file():
    """A board without country conventions leaves its postings untailorable."""
    countries = {b.country for b in registry.BOARDS.values()}
    files = {p.stem for p in (REPO / "skill" / "cv").glob("*.md")} - {"README"}
    assert countries <= files, f"missing cv files for: {sorted(countries - files)}"
