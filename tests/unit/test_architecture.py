"""The domain layer is stdlib-only, checked from the inside with ast.

import-linter enforces the same rule from pyproject; this test catches it
in the plain pytest lane too (import-linter needs Python >= 3.10, and this
suite also runs on 3.9).
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import swissdevjobs_cli.domain

DOMAIN_DIR = Path(swissdevjobs_cli.domain.__file__).parent


def _imported_roots(tree: ast.AST) -> set:
    roots = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                roots.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module.split(".")[0])
    return roots


def test_domain_imports_only_stdlib_and_itself():
    stdlib = set(sys.stdlib_module_names)
    offenders = {}
    for path in DOMAIN_DIR.rglob("*.py"):
        roots = _imported_roots(ast.parse(path.read_text(encoding="utf-8")))
        bad = {r for r in roots if r != "swissdevjobs_cli" and r not in stdlib}
        if bad:
            offenders[str(path.relative_to(DOMAIN_DIR))] = sorted(bad)
    assert not offenders, f"domain reaches outside the stdlib: {offenders}"


def test_domain_never_imports_outward_layers():
    offenders = {}
    for path in DOMAIN_DIR.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        bad = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                for layer in ("adapters", "service_layer", "entrypoints", "dto"):
                    if node.module.startswith(f"swissdevjobs_cli.{layer}"):
                        bad.add(node.module)
        if bad:
            offenders[str(path.relative_to(DOMAIN_DIR))] = sorted(bad)
    assert not offenders, f"domain imports outward layers: {offenders}"
