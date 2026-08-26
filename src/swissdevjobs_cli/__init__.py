"""swissdevjobs-cli: job-board client, CLI, and MCP server."""

__version__ = "0.9.0"

# Load .env before any adapter resolves paths from the environment. The
# loader itself has no import-time constants (see adapters/envfile.py), so
# a .env-provided SDJ_CACHE_DIR / SDJ_CONFIG_DIR is honored everywhere.
from swissdevjobs_cli.adapters import envfile as _envfile

_envfile.load()
