---
name: swissdevjobs
description: Search swissdevjobs.ch and help the user apply to roles — handles the site's native apply form, direct-email postings, and third-party ATS postings (driven with a browser MCP). Trigger when the user asks to find, filter, review, or apply to Swiss dev/IT jobs, or mentions swissdevjobs.ch.
---

# swissdevjobs skill

Drives the `swissdevjobs-cli` tool to search, inspect, and apply to Swiss
dev/IT jobs from swissdevjobs.ch.

## Setup

Install the CLI (`pipx install swissdevjobs-cli`, or `pip install -e .` from a
checkout), then set the applicant identity once:

```sh
export SDJ_NAME="Your Name"
export SDJ_EMAIL="you@example.com"
```

Without those, `sdj direct-apply` refuses to run unless `--name` / `--email`
are passed explicitly.

## Tooling

CLI binary: `sdj` (alias `swissdevjobs`). Every command accepts `--json` for
machine-readable output — **prefer `--json` whenever you're going to act on
the results**.

```sh
sdj list --tech Python --remote --min-salary 130000 --json
sdj show <id|slug> --json
sdj apply <id|slug> --json                    # surface the apply mechanism
sdj apply <id|slug> --json --complete email   # mark as applied via email
sdj direct-apply <id|slug> --cv /path/to/cv.pdf \
    --motivation "text or /path/to/letter.txt"
sdj applications --json                       # list tracked applications
sdj stats                                     # cache + application counts
sdj auth                                      # clear a Cloudflare challenge
```

Agent-friendly behaviour:

- `sdj list` hides jobs already applied to (`--include-applied` to override).
- `sdj apply --json` returns an `applied` field — `null` when not yet applied.
- `sdj direct-apply --json` returns `{"already_applied": true, ...}` for a
  duplicate rather than failing.
- Applications are tracked automatically in SQLite at
  `~/.cache/swissdevjobs-cli/swissdevjobs.db`.

## Workflow: search → shortlist → apply

1. **Search.** `sdj list … --json`. Already-applied jobs are filtered out.
2. **Check the apply route.** `sdj apply <id> --json` returns a `mode` and a
   `fallback_mode`.
3. **Inspect.** `sdj show <id> --json` for any candidate you're unsure about.
4. **Apply** via the mode below. On success the application is recorded in the
   local database.

### mode == "direct"

```sh
sdj direct-apply <id> --cv /path/to/cv.pdf --motivation /path/to/letter.txt
```

Submits through the site's own apply form (`POST /api/jobApply`, multipart).
`--motivation` takes either inline text or a path to a `.txt` file. The
motivation letter must not contain `<` or `>` — the site rejects them.

`direct-apply` refuses with exit code 2 when the posting is syndicated from an
aggregator, or when it merely links out to the company's own ATS. In both cases
the submission would be accepted by the endpoint but never reach the company,
so the command routes you to the ATS URL instead. Follow the browser mode.

### mode == "email"

`apply_email` is populated. Draft a motivation letter in the posting's
`language`, attach a CV matching that language, and send it through the user's
mail client.

1. Save the draft to a file first so the user can review it.
2. Send via the user's configured mail client, or open a `mailto:` link.
3. Afterwards: `sdj apply <id> --json --complete email`.

### mode == "browser"

`apply_url` points at a third-party ATS (Recruitee, Workday, Greenhouse, Lever,
SmartRecruiters, Personio, JobCloud, and similar). Drive it with a browser MCP:

1. Load the browser MCP tools if they are deferred.
2. Open a new tab for this job — don't reuse a tab another task owns.
3. Navigate to `apply_url`.
4. Read the page's interactive elements to map the form.
5. Fill each field; upload the CV that matches the posting's language.
6. Answer the `questions` from the apply payload using the user's profile.
7. **Before the final submit button**: stop, summarise exactly what is about to
   be submitted, and wait for the user to confirm in chat.
8. After submitting, capture the confirmation page text.
9. `sdj apply <id> --json --complete browser`.

If the ATS shows a CAPTCHA or "I'm not a robot" check, stop and hand off to the
user — don't try to solve it.

### mode == "unknown"

Fall back to `posting_url`: open it in the browser, find the apply button, and
continue as browser mode.

## Cloudflare challenges

`sdj` prompts interactively when Cloudflare blocks a request. In a
non-interactive context, run `sdj auth` first: it opens the site so the user can
clear the challenge and paste the `cf_clearance` cookie, after which subsequent
calls resume.

## Rules

- **Never auto-submit** a browser application without explicit user
  confirmation in chat for each submit click. Submitting is irreversible.
- **Never** enter financial details, social-security or national ID numbers,
  passport numbers, or bank details into a form — defer to the user.
- Match the CV language to the posting language.
- Keep motivation letters under 250 words unless the posting asks otherwise.
- Write one bespoke letter per posting; don't reuse a template across companies.
- Flag postings below the user's salary floor rather than applying to them.
- After an email or browser submission, always run
  `sdj apply <id> --complete <method>` so the tracking database stays accurate.
