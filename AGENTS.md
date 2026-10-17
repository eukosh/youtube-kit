# youtube-kit

YouTube Data API v3 toolkit: the `ytk` CLI (primary) and an MCP server, both thin adapters over `src/youtube_kit/core`. Read `docs/adr/0001-shared-core-cli-and-mcp.md` before changing how the layers fit.

## Conventions

- An operation is one `@operation` function in `core/ops/<noun>.py` plus a `ytk <noun> <verb>` command in `cli.py`; MCP picks it up automatically. Its `Args:` docstring is the help text on both, so describe other operations by what they do, not by command or tool name.
- Core returns Pydantic models and raises `core.errors` types. Printing, exit codes and FastMCP belong in the adapters.
- `@operation` adds a `my_channel` parameter (which of the user's logged-in channels to work on) to every operation that calls YouTube; mark local-only ones `local=True`.
- Irreversible deletes go through `core/guard.py`. Read `docs/adr/0002-guarded-deletes.md` before adding or loosening one.
- Tests run offline: fake the API with the `api` fixture in `tests/conftest.py`. CI also runs `ruff check` and `ruff format --check`.
- `skills/youtube/SKILL.md` documents the CLI's JSON output and exit codes; change it together with them.
- Commits and PR titles follow Conventional Commits. Write subjects for users; Release Please turns them into the changelog and owns the version.

## Agent skills

### Issue tracker

Issues are tracked as GitHub Issues, operated via the `gh` CLI. See `docs/agents/issue-tracker.md`.

### Domain docs

Single-context: `CONTEXT.md` and `docs/adr/` at the repo root. See `docs/agents/domain.md`.
