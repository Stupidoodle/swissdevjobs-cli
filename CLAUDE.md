# CLAUDE.md

Guidance for agents working in this repository.

## Commands

Everything runs through `uv` and `make` — never bare `python`, `pip`, or `pytest`:

```
make install        # uv sync
make check          # the full gate: lint + typecheck + arch + tests w/ coverage
make format         # ruff format, then ruff --fix
make test-unit      # offline tests, no coverage gate
make test-live      # read-only smoke against the real boards (SDJ_LIVE=1)
make arch           # import-linter layering contracts (needs Python >= 3.10)
```

Never hand-edit `pyproject.toml` dependency tables or `uv.lock` — use
`uv add` / `uv add --group dev`. Conventional commits, atomic, one logical
change each. Never squash.

## Layout and the dependency rule

```
src/swissdevjobs_cli/
  bootstrap.py            composition root — the ONLY place layers are wired
  domain/
    model/                one dataclass per file, snake_case = class name
    ports/                one Protocol per file (BoardPort, repositories, UoW)
  adapters/
    http/                 urllib transport, cookie jar, Cloudflare detection
    boards/
      registry.py         every Board, keyed by ISO country code
      worldwide/devitjobs/  client.py + acl.py for the six-board family
    persistence/          tables, imperative mappers, repositories, SQLite UoW
    envfile.py            .env loader — NO import-time path constants (see below)
    paths.py              eager path constants — import only from adapters
  service_layer/          use cases: search, apply, tracking, config
  dto/                    frozen entrypoint-facing shapes; plain dataclasses
  entrypoints/            cli.py and mcp.py — thin, no business logic
```

**Dependency rule — no exceptions:** `entrypoints → dto → service_layer →
adapters → domain`. Higher may import lower, never the reverse. `bootstrap.py`
sits outside the contract on purpose. Enforced twice: import-linter
(pyproject) and `tests/unit/test_architecture.py` (ast, runs on 3.9).

**The domain is stdlib-only, forever.** No pydantic, no HTTP, nothing.

**envfile vs paths:** `envfile.py` must stay free of import-time constants —
it runs from `__init__` before anything reads the environment. Eager path
constants live in `paths.py`, imported only by the adapters that need them.
Merging the two silently breaks `.env`-provided `SDJ_CACHE_DIR`/`SDJ_CONFIG_DIR`.

## Python version — CRITICAL, INVERTED vs sibling repos

This repo floors at **3.9** (`requires-python >= 3.9`, tested on 3.9 and
3.14). Sibling projects (deferent, signal-over-noise, bt-prototype) floor at
3.14 and ban `from __future__ import annotations` — **this repo is the
opposite**:

- `from __future__ import annotations` is REQUIRED in every module. It is
  what makes `list[X]`, `X | None` legal in annotations on 3.9.
- Never use `X | Y` at runtime (isinstance, variable assignment) — only in
  annotations.
- No `match` statements (3.10+), no unparenthesized multi-except (PEP 758 is
  3.14-only and would be a SyntaxError here), no `uuid.uuid7()` (3.14-only;
  use `uuid.uuid4()`).
- ruff `target-version = "py39"` keeps the formatter and pyupgrade honest;
  do not raise it.

## Invariants

- **Zero runtime dependencies.** `dependencies = []` is the product's
  headline claim. Never `uv add` a runtime dependency without Bryan's
  explicit approval. Pre-approved exception, for the release that adds the
  first non-devitjobs platform: pydantic, in `adapters/*/acl.py` wire models
  only — never in domain, never for DTOs.
- **MCP and CLI first.** The agent harness drives this product; every
  feature lands in both entrypoints or it didn't land.
- **stdout belongs to the MCP transport.** Nothing under service_layer or
  adapters may print. Diagnostics go to stderr.
- **Never submit an application in tests, smoke checks, or development.**
  `apply_to_job` without `confirm` returns a preview; that is the only apply
  call ever made against the real boards outside production use. The
  applications table in the developer database is real personal history —
  migrations must never touch it.
- **Wire shapes are frozen contracts.** `Job.raw`/`JobDetail.raw`, the DTO
  `as_dict()` outputs, and the MCP tool results are consumed by agents in
  the wild. Additive keys are fine; renames and removals are breaking.

## Boards

Six boards share one backend (the devitjobs platform): swissdevjobs.ch (ch),
germantechjobs.de (de), devitjobs.uk (uk), devitjobs.com (us — includes
Canada), devitjobs.nl (nl), devitjobs.fr (fr). One client + one ACL covers
all of them; `adapters/boards/registry.py` is the single source of truth.
A new family board is a registry entry. A new *platform* is a new folder
under `adapters/boards/<country>/` (country-locked) or
`adapters/boards/worldwide/` (multi-country), implementing `BoardPort`
behind its own ACL.

Direct apply (`POST /api/jobApply`) only delivers when the board holds a
forwarding channel; `service_layer/apply.undeliverable()` refuses aggregator
and CompanyWebsite postings — do not weaken it, silent black-holing of a
job application is the worst failure this tool can have.

## Parallel agent work

Split by layer or by board platform, never two agents in one file. The
shared contract is the port signatures (`domain/ports/`) plus the domain
dataclasses; agree on those first, then implement independently. Every port
gets a hand-written fake in `tests/fakes/` — that is what makes independent
implementation testable. No `unittest.mock`.

## Testing

`tests/unit` mirrors `src`; `tests/fakes` holds one fake per port;
`tests/live` is the opt-in real-API lane (read-only, `SDJ_LIVE=1`).
Coverage gate: 90 branch. Warnings are errors (Deprecation, ResourceWarning)
— an unclosed handle is a bug, not a note.
