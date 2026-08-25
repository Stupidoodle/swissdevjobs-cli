# Adding a board

Board requests are welcome as issues; boards are implemented by the
maintainer (or by a PR that follows this contract exactly). This document is
the whole interface — nothing outside your adapter folder should need to
change except the registry.

## Two kinds of additions

1. **A new board of an existing platform** — one `Board(...)` entry in
   `adapters/boards/registry.py`. Done. (This is how five devitjobs sister
   boards and jobup.ch landed.)
2. **A new platform** — a new folder implementing `BoardPort` behind its own
   anti-corruption layer:

```
adapters/boards/<where>/<platform>/
  client.py   # implements BoardPort against the platform's API
  acl.py      # wire JSON → normalized raw + domain Job/JobDetail
```

`<where>` is a country folder (`switzerland/`) for country-locked platforms,
or `worldwide/` for multi-country ones.

## The Board entry

```python
Board(
    platform="jobcloud",          # folder name
    country="ch",                 # ISO 3166-1 alpha-2, lowercase
    base_url="https://www.jobs.ch",
    name="jobs.ch",
    currency="CHF",
    source="jobsch",              # UNIQUE key: registry, runtime routing,
                                  # and the DB `source` column all use it
    search_driven=True,           # True: no full feed exists; queries pass
                                  # through server-side; cache = resolution only
    native_apply=False,           # False: apply refuses with the ATS URL
    scope="all-industries",       # "it" (default) or "all-industries"
    salary_published=False,       # False: the wire carries no salary data
)
```

Selectors resolve country codes and source ids automatically — a new board
is immediately addressable as `--board <source>` and via its country code.
The entry IS the discovery surface: `list_boards` (MCP) and `sdj boards`
(CLI) render it verbatim, and category aliases registered for the board
(see `CATEGORY_IDS` in the platform client) flow into
`registry.known_categories()`, which feeds the MCP `category` enum and the
CLI `--category` choices. Declare the board honestly and every surface
updates itself.

## The port

`domain/ports/board_port.py` is the contract. Five methods:

- `fetch_jobs(*, query=None, category=None, force=False) -> list[Job]` —
  feed boards return everything and may ignore `query`; search-driven boards
  pass it to the server, newest first, and respect a sane page budget.
- `fetch_detail(job_id) -> JobDetail`
- `hydrate_detail(raw) -> JobDetail` — rebuild from a cached raw payload;
  must round-trip with `fetch_detail`'s raw.
- `posting_url(raw) -> str` — public URL from the raw mapping.
- `submit_application(detail, applicant, motivation)` — only if the platform
  has a REAL native apply channel; otherwise raise, and set
  `native_apply=False` so the refusal fires first.

## The ACL and the normalized raw keys

`Job.raw` / `JobDetail.raw` keep every original wire key **plus** the
normalized keys the filter/sort/output paths read. Guarantee these:

| key | meaning |
|---|---|
| `_id` | the job id (whatever shape the platform uses) |
| `jobUrl` | slug / URL identifier |
| `name`, `company`, `actualCity` | title, company, city |
| `language` | primary posting language, English word ("German") or None |
| `technologies`, `filterTags` | lists; empty is fine, never absent |
| `annualSalaryFrom/To` | integers, or absent — salary is OPTIONAL |
| `activeFrom` | the board's own (re-stampable) date |
| `postedAt`, `postedAtUnix` | the immutable first-published time, or None |
| `country`, `source` | copied from the Board |

Detail raws additionally normalize `description` (may contain HTML — the
DTOs strip it), `redirectJobUrl`, and `candidateContactWay`.

Rows must survive the SQLite round-trip via `light_json` — that is automatic
if `store_jobs` sees your normalized raw; add one round-trip test to prove
`postedAtUnix` survives (a UUID `_id` decodes to garbage in the legacy
column-fallback path, so `light_json` is mandatory).

## Non-negotiables

- **The domain stays stdlib-pure.** Your adapter may (with prior approval)
  bring a dependency; the domain and DTOs never do.
- **Never black-hole an application.** If the platform cannot prove native
  delivery, refuse with the real apply URL. Silent 200s are the worst
  failure this tool can have.
- **Never submit an application in tests or smoke checks.** Fakes only.
- **Wire shapes are frozen contracts.** Additive keys fine; renames and
  removals are breaking.
- **Audit the real thing before shipping**: sample postings across the full
  feed (field distributions, apply-method variants, redirect hosts), and
  render a few pages in a browser — devitjobs hides a honeypot element
  instructing bots to email an address; assume other boards are hostile to
  scrapers too. The API is the only honest surface.

## Tests

- `tests/unit/adapters/test_<platform>_acl.py` — normalization, including
  the ugly variants you found in the audit.
- `tests/unit/adapters/test_<platform>_client.py` — driven through a
  hand-written HTTP fake (no `unittest.mock`), covering pagination limits
  and error shapes.
- Registry assertions extend automatically; keep `make check` at ≥90%
  branch coverage on 3.9 and 3.14.
