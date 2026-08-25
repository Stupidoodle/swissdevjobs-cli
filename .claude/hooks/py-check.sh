#!/usr/bin/env bash
# PostToolUse hook: keep Python edits clean without the agent spending a turn on it.
#
# Runs on every Edit/Write/MultiEdit. Exits silently when everything passes, so a
# clean edit costs zero tokens. On failure it exits 2, which feeds stderr back to
# Claude as a blocking error -- the only time the agent hears about this at all.
#
# Ordering matters: format first (it rewrites the file), then autofix lints, then
# the checks that only report. Running ty before ruff --fix would surface errors
# ruff was about to delete.

set -uo pipefail

# Colour codes are pure token cost when this output is fed back to the agent.
export NO_COLOR=1
export TERM=dumb

payload=$(cat)
file=$(printf '%s' "$payload" | jq -r '.tool_input.file_path // .tool_response.filePath // empty')

# Not a Python edit: nothing to do. Also covers Write to a .md or .toml.
case "$file" in
  *.py) ;;
  *) exit 0 ;;
esac

root=$(cd "$(dirname "$file")" && git rev-parse --show-toplevel 2>/dev/null) || exit 0
cd "$root" || exit 0

before=$(shasum -a 256 "$file" 2>/dev/null | cut -d' ' -f1)

fails=""
uv run ruff format -q "$file" 2>/dev/null
ruff_out=$(uv run ruff check --fix --output-format=concise "$file" 2>&1) || fails+="$ruff_out"$'\n'
ty_out=$(uv run ty check src/ 2>&1) || fails+="$ty_out"$'\n'
# lint-imports only once the layering contracts exist in pyproject.
if grep -q '\[tool.importlinter\]' pyproject.toml; then
  imports_out=$(uv run lint-imports 2>&1) || fails+="$imports_out"$'\n'
fi

if [ -n "$fails" ]; then
  printf 'Automated checks failed for %s:\n\n%s\n' "${file#"$root"/}" "$fails" >&2
  exit 2
fi

after=$(shasum -a 256 "$file" 2>/dev/null | cut -d' ' -f1)
if [ "$before" != "$after" ]; then
  # The agent's in-context copy is now stale; a later Edit would miss.
  echo "note: ${file#"$root"/} was reformatted on save; re-read before editing it again."
fi
exit 0
