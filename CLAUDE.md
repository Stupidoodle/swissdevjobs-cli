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
      registry.py         every Board, keyed by source; selectors resolve
                          country codes OR source ids (two+ boards per country)
      worldwide/devitjobs/   client.py + acl.py for the six-board family
      switzerland/jobcloud/  client.py + acl.py for jobs.ch + jobup.ch
      singapore/mycareersfuture/  client.py + acl.py for MyCareersFuture
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
  Contract state since 0.6: summary rows are omit-empty (None/empty keys
  dropped) with numeric-only salary (`salary_from`/`salary_to` +
  `currency`, no formatted string); `sdj list --json` emits that summary
  envelope capped at 50 by default, and `--raw` reproduces the pre-0.6 raw
  wire rows exactly; MCP in-band error codes are stable strings
  (`unknown_selector`, `job_not_found`, `internal_error`, …) — never
  Python class names.

## Boards

Three platforms, nine boards; `adapters/boards/registry.py` is the single
source of truth, keyed by `source` (the value in the DB `source` column).
Board facts surface as data through `list_boards` (MCP) / `sdj boards`
(CLI) via `dto/board.py` — never hardcode board counts, category lists, or
capabilities in prose or schemas: the MCP `category` enum and the CLI
`--category` choices derive from `registry.known_categories()`, and a
`Board` entry declares `scope` ("it" or "all-industries") and
`salary_published` alongside `search_driven`/`native_apply`.

**Filter parity — every filter behaves the same on every board.** A board
whose wire lacks a filter dimension declares it in
`Board.filters_unavailable` ("salary", "remote", "visa", "level", "tech").
Filtering on a missing dimension must never silently drop the board's rows
(that reads as "searched, nothing matched" — a lie): `search.
split_by_filterability` excludes the board up front and the result says so
in `boards_excluded` plus the in-band `note`. One exception: a
search-driven board missing only "tech" folds the tech terms into its
server-side query (`search.server_query`; JobCloud ANDs multi-term
queries, verified live) and its rows skip the client tag filter
(`search.tech_for`). `tests/unit/service_layer/test_filter_parity.py`
enforces the matrix over the live registry — a new board or a new filter
param fails it until classified. Contract types work the same way as
categories: shared aliases (`registry.known_contracts()`) that each
platform maps onto its own taxonomy (devitjobs `jobType` in its ACL,
JobCloud `employment-type-ids` — platform-wide, verified on both boards);
`workload` percent exists only on the JobCloud wire (`employment_grades`),
so the devitjobs and mycareersfuture boards declare it unavailable. Search-driven boards run
contract/workload server-side via `fetch_jobs` params — post-fetch
filtering would waste their 2000-row result window.
Selectors — `--board` (aliases `--source`, `--country`), `SDJ_BOARDS`
(fallback: the pre-0.5.1 `SDJ_COUNTRIES`), the MCP `board` param (deprecated
alias `country`) — accept a source id (`jobsch`) or a country code (expands
to every board in that country: `ch` is three boards now). Never key
anything by country: `Runtime` routes by `job.board.source`.

- **devitjobs** (worldwide/devitjobs/): swissdevjobs.ch, germantechjobs.de,
  devitjobs.uk, devitjobs.com (US+CA), devitjobs.nl, devitjobs.fr. Full-feed
  boards: one `/api/jobsLight` call mirrors the inventory; the cache serves
  browsing for 10 minutes; native apply exists (with the deliverability
  refusals below).
- **jobcloud** (switzerland/jobcloud/): jobs.ch, jobup.ch. All industries,
  `Board.search_driven=True`: the ~45k-job inventory cannot be mirrored
  (rows hard-capped at 20/page, result window at 2,000), so every browse
  passes the user's query server-side (`sort=date`) and the cache serves
  RESOLUTION only (`search.resolve_jobs`) — never treat it as a browse
  corpus. `Board.native_apply=False`: application_method is an external ATS
  redirect or JobCloud's own authenticated form, so apply always refuses
  with `no_native_apply` + the ATS URL. No salary data exists on the wire —
  keep salary optional for every future board. `category-ids[]` taxonomies
  are per board (IT root: jobs.ch 106, jobup 702; jobup 422s on jobs.ch
  ids). Server-matched rows must skip the client-side query filter
  (`search.query_for`) or description-only hits get dropped.
- **mycareersfuture** (singapore/mycareersfuture/): MyCareersFuture, the
  Singapore government job portal (Workforce Singapore, API host
  `api.mycareersfuture.gov.sg`). `Board.search_driven=True`: the
  Information Technology category alone carries ~9,000 active postings and
  the wire caps `limit` at 100/page, so the query passes server-side
  (newest first) scoped to `categories=Information Technology`. Unlike
  jobcloud it publishes real salary — monthly SGD on the wire, annualized
  ×12 in the ACL and never guessed for any other unit — and a skills array,
  so `tech`/`remote` filter normally rather than folding into the query
  (`remote` maps from `flexibleWorkArrangements`, where `Telecommuting` is
  the only value meaning location flexibility; the rest are time
  flexibility). `visa`/`level`/`workload` are unavailable: no
  sponsorship-eligibility field exists (the employer applies for a specific
  work pass after the fact), the wire's `positionLevels` vocabulary
  ("Professional", "Middle Management", "Fresh/entry level", …) has no
  honest mapping onto the shared Junior→CLevel enum so the raw array is
  left in `job.raw`, and no workload-percentage field exists at all.
  `Board.native_apply=False`: applying happens on the posting page through
  the portal's own flow (the detail payload carries `screeningQuestions`),
  not by redirect to an external ATS — 0 of 300 sampled descriptions
  carried a link of any kind — so apply refuses with `no_native_apply` and
  hands back `jobDetailsUrl`, which really is where an application is made.
  Its `uuid` is a 32-char hex string that is not an ObjectId but decodes as
  one, so `light_json` is mandatory for its cached rows. Queries go to
  `POST /v2/search`, never `GET /v2/jobs?search=`: the GET search param
  504s on anything not already CDN-warm, which took every other board down
  with it (v0.9.1).

A new family board is a registry entry. A new *platform* is a new folder
under `adapters/boards/<country>/` (country-locked) or
`adapters/boards/worldwide/` (multi-country), implementing `BoardPort`
behind its own ACL — see docs/adding-a-board.md for the contract.

Direct apply (`POST /api/jobApply`) only delivers when the board holds a
forwarding channel; `service_layer/apply.undeliverable()` refuses syndicated
(`isPartner`/`cpc` — the majority outside CH), aggregator, and CompanyWebsite
postings — do not weaken it, silent black-holing of a job application is the
worst failure this tool can have. Verified in the browser: syndicated pages
have no native apply form, and every page embeds a honeypot element telling
bots to email a devitjobs.com address — invisible to humans (2px font, 2px
height, white-on-white, aria-hidden) but present in DOM/accessibility dumps.
Never scrape the pages; the API is the only honest surface. Note the API
does not expose `emailAddressForApplications` (always null) — forwarding
for Email postings happens server-side behind POST /api/jobApply.

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
