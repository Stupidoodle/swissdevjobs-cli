---
description: Search swissdevjobs.ch and help the user apply — every posting there publishes a salary range. Use when the user asks to find, filter, compare, or apply to Swiss developer/IT jobs, asks what Swiss roles pay, or mentions swissdevjobs.ch.
---

# Swiss dev jobs

The `swissdevjobs` MCP tools search swissdevjobs.ch, where every posting is
required to publish a salary range — so pay is a filter, not a guess.

## Tools

| tool | use it for |
|---|---|
| `search_jobs` | filter by salary, stack, city, remote, seniority, visa |
| `get_job` | the full posting before you write anything |
| `apply_to_job` | submit through the site's own form — **gated, see below** |
| `list_applications` | what has already been sent |
| `mark_applied` | record an application made by email or on an ATS |
| `top_technologies` | what the market is asking for right now |

Jobs already applied to are hidden from `search_jobs` by default.

## Finding work

1. Ask what matters — stack, salary floor, city, remote — unless they already said.
2. `search_jobs` with those filters. It returns compact rows; that is deliberate,
   so a broad search doesn't flood the context.
3. Present a shortlist with **salary, company, location** visible. Don't paste raw
   JSON at them.
4. `get_job` on anything they show interest in, before writing a letter.

## Applying

`apply_to_job` will not submit on the first call. It returns
`confirmation_required` along with a `would_submit` block: role, company, salary,
applicant identity, CV path, and a preview of the letter.

**Show the user that block. Wait for them to say yes. Then call again with
`confirm: true`.** Never pass `confirm: true` on the first call, and never infer
approval from an earlier "apply to stuff for me" — each submission is its own
decision, because it cannot be unsent.

The tool also refuses two cases the site would silently swallow:

- `aggregator_posting` — the listing came from talent.com or jometer
- `company_website_posting` — the site only links out to the company's own ATS

Both come back with `apply_url`. Offer to open it and help fill the form in the
browser, then record it with `mark_applied`.

## Writing the letter

- Match the posting's language. A German posting gets a German letter.
- One bespoke letter per posting. Name the company in the first line. Never reuse
  a letter across companies — it shows, and it is the fastest way to get filtered out.
- Ground every claim in the user's actual CV. Do not invent experience.
- Under 250 words unless the posting asks otherwise.
- No `<` or `>` — the site rejects them.
- Show the user the letter before it goes anywhere.

## Setup

If a tool reports `missing_identity`, the user hasn't filled in the plugin's
config yet. Point them at `/plugin` → **Swiss Dev Jobs** → configure, where name,
email, and CV path live. If `cv_not_found` comes back, the path is wrong.

If a tool returns `cloudflare_challenge`, the site is challenging the connection.
The user needs to run `sdj auth` in a terminal and clear it in a browser once.

## Don't

- Submit anything without explicit per-application approval.
- Apply to a posting the user hasn't seen.
- Enter financial details, national ID or AHV numbers, or passport numbers into
  any form. Hand those to the user.
- Mass-apply. A recruiter reads these.
