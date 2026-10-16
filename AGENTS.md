# youtube-kit

YouTube Data API v3 toolkit: the `ytk` CLI (primary) and an MCP server, both thin adapters over `src/youtube_kit/core`. Read `docs/adr/0001-shared-core-cli-and-mcp.md` before changing how the layers fit.

## Working on it

- Tests: `uv run pytest` (offline, API faked via the `api` fixture in `tests/conftest.py`). Lint and format: `uv run ruff check --fix . && uv run ruff format .`
- An operation is one `@operation`-decorated function in `core/ops/`, with a Google-style `Args:` docstring. That docstring is the user-facing help on both surfaces, so word it for both and refer to other operations by what they do, never by a CLI or tool name. Then give it a command in `cli.py`; MCP registers it automatically.
- Core stays transport-free: it returns Pydantic models and raises `core.errors` types. Printing, exit codes, and FastMCP live in the adapters.
- A change to any operation's signature, docstring, or model changes the MCP tool surface: regenerate with `UPDATE_SNAPSHOTS=1 uv run pytest tests/test_mcp.py` and review the diff.
- The CLI's JSON-on-stdout and exit-code contract is documented in `skills/youtube/SKILL.md`; keep them in step.

## Agent skills

### Issue tracker

Issues are tracked as GitHub Issues, operated via the `gh` CLI. See `docs/agents/issue-tracker.md`.

### Domain docs

Single-context: `CONTEXT.md` and `docs/adr/` at the repo root. See `docs/agents/domain.md`.
