# swissdevjobs-cli

A terminal client for [swissdevjobs.ch](https://swissdevjobs.ch) — search and
inspect Swiss dev/IT jobs (the site requires every posting to publish a salary
range), track what you've applied to, and submit applications without leaving
the shell. Zero runtime dependencies; Python stdlib only.

Not affiliated with swissdevjobs.ch.

## Install

```sh
pipx install git+https://github.com/Stupidoodle/swissdevjobs-cli

# or, from a checkout:
pipx install -e .          # or: pip install -e .

# installs two equivalent binaries: `swissdevjobs` and `sdj`
```

Not on PyPI.

Python 3.9+.

## Usage

```sh
sdj list                                            # all active jobs
sdj list --tech Python --tech Kubernetes --remote   # filter
sdj list --min-salary 130000 --location Zurich --sort salary
sdj list "platform engineer" --level Senior --visa
sdj show 62eccd7a57370f0152e4950e                   # full detail (id or slug)
sdj show acme-corp --json                           # machine-readable
sdj open acme-corp                                  # open in browser
sdj tech --limit 20                                 # most-requested tech tags
sdj apply <id> --json                               # how to apply to this one
sdj applications                                    # what you've applied to
sdj stats                                           # cache + application counts
sdj auth                                            # pre-solve a CF challenge
```

`list` output columns: id, dates, title, company, city, salary, workplace, tags.
The date column shows `p=` (true posting time, decoded from the MongoDB
ObjectId) and `a=` (`activeFrom`, which the site re-stamps whenever it bumps a
listing back to the top).

### Filtering flags

| flag | effect |
|---|---|
| `--tech X` (repeatable) | match any tag; `--tech-all` requires all |
| `--location Zurich` | city substring match |
| `--remote` / `--onsite` | workplace filter |
| `--visa` | visa sponsorship only |
| `--level` | Junior / Regular / Senior / Principal / CLevel |
| `--language` | e.g. English, German |
| `--min-salary` / `--max-salary` | CHF/year |
| `--company` | substring match |
| `--sort` | `posted` (default) / `date` / `salary` / `company` |
| `--limit`, `--page`, `--per-page` | window the output |
| `--include-applied` | show jobs already applied to (hidden by default) |
| `--json` | machine-readable output |

## Applying

`sdj apply <id> --json` surfaces the route a posting uses:

| mode | meaning |
|---|---|
| `direct` | submit through the site's own form (`POST /api/jobApply`) |
| `email` | `apply_email` holds the company's address |
| `browser` | `apply_url` points at a third-party ATS — fill it in yourself |

To submit through the site's native form:

```sh
export SDJ_NAME="Your Name"
export SDJ_EMAIL="you@example.com"

sdj direct-apply <id> --cv ./cv.pdf --motivation ./letter.txt
```

`--motivation` accepts inline text or a path. `--name` / `--email` override the
environment variables; without either, the command refuses to run.

`direct-apply` exits with code 2 when the posting is syndicated from an
aggregator, or when the site merely links out to the company's own ATS. Those
submissions are accepted by the endpoint but never reach the company, so the
command points you at the real apply URL instead of silently black-holing your
application. `--force` overrides.

Applications you submit — plus any you mark with
`sdj apply <id> --complete email|browser|linkedin` — are recorded in SQLite at
`~/.cache/swissdevjobs-cli/swissdevjobs.db`, and `sdj list` hides them from
future results.

## API surface (reverse-engineered)

| endpoint | purpose |
|---|---|
| `GET /api/jobsLight` | array of all active jobs (lightweight fields) |
| `GET /api/job/{_id}` | full detail incl. description and requirements |
| `GET /rss` | RSS feed (alternate bulk source) |
| `POST /api/jobApply` | the site's native apply form (multipart) |

No auth or API key on the read endpoints. Responses are plain JSON, cached in
the SQLite database (10 min for the list, 1 h for detail). Use `--refresh` to
bypass the cache.

## Cloudflare challenges

swissdevjobs.ch sits behind Cloudflare. Under normal use the JSON API is open,
but automation or datacenter IPs can trigger a managed-challenge interstitial
("Just a moment…"). When that happens the CLI:

1. Blocks the current command and prints the URL.
2. Opens the URL in your default browser via `webbrowser.open`.
3. Waits on stdin for you to paste the `cf_clearance` cookie value
   (DevTools → Application → Cookies → `.swissdevjobs.ch`).
4. Persists it in a Netscape cookie jar at `~/.config/swissdevjobs-cli/cookies.txt`
   and retries the original request. Subsequent calls reuse the cookie.

There is no automated challenge solving here — you clear it in a real browser
and hand the cookie back. Run `sdj auth` up front before scripting a batch of
calls.

## Environment variables

| variable | purpose |
|---|---|
| `SDJ_NAME` / `SDJ_EMAIL` | applicant identity for `direct-apply` |
| `SDJ_CACHE_DIR` | override `~/.cache/swissdevjobs-cli` |
| `SDJ_CONFIG_DIR` | override `~/.config/swissdevjobs-cli` |
| `SDJ_APPLICATIONS_LOG` | markdown application log to import on first run |

## Claude Code skill

`skill/SKILL.md` wraps the CLI as a Claude Code skill. To install it:

```sh
mkdir -p ~/.claude/skills/swissdevjobs
cp skill/SKILL.md ~/.claude/skills/swissdevjobs/
```

Then: `/swissdevjobs find senior python jobs in zurich paying over 140k`.

## Layout

```
src/swissdevjobs_cli/
  api.py         HTTP client, cookie jar, CaptchaRequired detection, apply POST
  captcha.py     Interactive CF challenge handler (browser + paste-cookie)
  db.py          SQLite cache and application tracking
  filter.py      Job filtering and sort keys
  cli.py         argparse commands
skill/SKILL.md   Claude Code skill wrapper
```

## Please be reasonable

This talks to someone else's site. Keep your request volume human, don't strip
the caching, and don't mass-apply to postings you haven't read. Check
swissdevjobs.ch's terms before you automate anything on top of this.

## License

MIT — see [LICENSE](LICENSE).
