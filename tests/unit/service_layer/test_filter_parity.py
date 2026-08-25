"""The cross-platform filter parity contract.

Every filter must behave the same way on every board in the registry:
served, folded into the server query, or *visibly* excluded — never a
silent empty result. These tests iterate the live registry, so a future
board is covered the day its entry lands.
"""

from __future__ import annotations

import inspect

from swissdevjobs_cli.adapters.boards import registry
from swissdevjobs_cli.service_layer import search

# Dimensions a Board may declare unavailable → the matches() params they gate.
GATED = {
    "tech": {"tech": ["Python"]},
    "remote": {"remote": True},
    "visa": {"visa": True},
    "level": {"level": "Senior"},
    "salary": {"min_salary": 1},
}
# Params that must work on every platform's normalized row, no gate allowed.
UNIVERSAL = {"location", "language", "company", "query", "tech_any"}


class _Port:
    def __init__(self, board):
        self.board = board


def test_every_matches_param_is_classified_gated_or_universal():
    """A new filter param must be sorted into a bucket before it ships.

    Unclassified means it could silently empty a board again.
    """
    params = set(inspect.signature(search.matches).parameters) - {"job"}
    gated_params = {"tech", "remote", "visa", "level", "min_salary", "max_salary"}
    assert params == gated_params | UNIVERSAL


def test_boards_only_declare_known_dimensions():
    for b in registry.BOARDS.values():
        assert set(b.filters_unavailable) <= set(GATED), b.source


def test_salary_published_agrees_with_filters_unavailable():
    for b in registry.BOARDS.values():
        assert (not b.salary_published) == ("salary" in b.filters_unavailable), b.source


def test_no_board_can_be_silently_emptied_by_any_filter():
    """The matrix: every registry board × every gated dimension."""
    for b in registry.BOARDS.values():
        for dim, kwargs in GATED.items():
            wanted = search.requested_filters(**kwargs)
            searchable, excluded = search.split_by_filterability([_Port(b)], wanted)
            if dim not in b.filters_unavailable:
                assert searchable and not excluded, (b.source, dim)
            elif dim == "tech" and b.search_driven:
                # Folded, not excluded: the terms travel as the server query.
                assert searchable and not excluded, (b.source, dim)
                assert search.server_query(b, None, ["Python"]) == "Python"
            else:
                assert excluded == {b.source: [dim]}, (b.source, dim)


def test_folding_appends_tech_terms_to_an_existing_query():
    jobsch = registry.BOARDS["jobsch"]
    assert search.server_query(jobsch, "backend", ["Python", "AWS"]) == (
        "backend Python AWS"
    )
    # Feed boards keep their query untouched — they filter tech client-side.
    devit = registry.BOARDS["swissdevjobs"]
    assert search.server_query(devit, "backend", ["Python"]) == "backend"


def test_a_combined_exclusion_names_every_missing_dimension():
    jobsch = registry.BOARDS["jobsch"]
    wanted = search.requested_filters(remote=True, min_salary=100000)
    _, excluded = search.split_by_filterability([_Port(jobsch)], wanted)
    assert set(excluded["jobsch"]) == {"remote", "salary"}


def test_the_coverage_note_explains_exclusions_and_folding():
    jobsch = registry.BOARDS["jobsch"]
    note = search.coverage_note(
        [_Port(jobsch)],
        {"jobup": ["remote"]},
        query=None,
        category=None,
        tech=["Python"],
    )
    assert "jobs.ch matched the tech terms server-side" in note
    assert "jobup: no remote data" in note
    assert "drop those filters" in note
    # Full coverage → no note at all.
    assert (
        search.coverage_note([_Port(jobsch)], {}, query="q", category=None, tech=None)
        is None
    )
