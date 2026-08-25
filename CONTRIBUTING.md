# Contributing

Thanks for stopping by. A few honest ground rules so nobody wastes time.

## Want another job board supported?

Open a [board request](https://github.com/Stupidoodle/swissdevjobs-cli/issues/new?template=board_request.yml)
— **the maintainer implements boards.** Board adapters involve
reverse-engineering, anti-bot behavior, and an irreversible apply flow, so
they need hands-on verification against the real site. What genuinely helps:
the board's URL, which country it covers, and anything you know about how
its apply flow works.

## Bugs and small fixes

Bug reports with reproduction steps are always welcome. Small PRs (typos,
error messages, a missing edge case with a test) too. For anything larger,
open an issue first so we agree on the shape before you spend a weekend
on it.

## Working on the code

```sh
git clone https://github.com/Stupidoodle/swissdevjobs-cli
cd swissdevjobs-cli
make install     # needs uv
make check       # lint + typecheck + layering + tests with the coverage gate
```

The architecture, layering rules, Python-version constraints, and hard
invariants are documented in [CLAUDE.md](CLAUDE.md) — written for AI agents,
equally binding for humans. The short version: cosmic-python layering
(domain → adapters → service_layer → dto → entrypoints), zero runtime
dependencies, Python 3.9 floor, conventional commits, and **never submit a
real application from tests or development**.

Tests are offline by default; `make test-live` runs a read-only smoke
against the real boards.
