# Per-country CV conventions

One file per country, loaded on demand: when tailoring a CV or motivation
letter for a posting, read `cv/<country>.md` for the posting's `country`
value (from the job row) and follow it. Don't load countries you aren't
applying to.

## The contract

- **Conventions live here. The user's data never does.** These files
  describe what a CV in that market looks like — never any actual person's
  CV content.
- **Emit source, not PDFs.** Produce LaTeX, typst, or HTML the user can
  render; never render a PDF in-process (the tool has zero runtime
  dependencies and keeps it that way).
- **The posting decides the language.** Match the CV and letter language to
  the posting language and region rules in the country file.
- Conventions are descriptive, not laws. Where a rule is contested, the
  file says so; the user's own preference wins.

## Contributing

These files are contributable units — like boards in the registry. Wrong or
incomplete conventions for your market? Open a PR (see the repo's
contribution flow) or an issue. Anonymized structural examples are welcome
**only** through the consent-gated anonymization flow — never post anyone's
actual CV.
