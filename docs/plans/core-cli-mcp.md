# Plan: shared YouTube core, exposed through a CLI and an MCP server

Status: implemented 2026-10-16. The design as built (which refines this plan) is recorded in
[ADR 0001](../adr/0001-shared-core-cli-and-mcp.md); this file is kept as history.

## Goal

Turn `youtube-mcp` from "an MCP server" into "a YouTube Data API toolkit with
two front-ends":

- a **CLI** (`ytk …`): the main interface for coding agents (Claude Code,
  Codex), scripts and humans. It pipes into `jq`, costs no context until it is
  called, and agents learn it from a small Agent Skill.
- an **MCP server** (`ytk mcp`): for hosts that have no shell, such as Claude
  Desktop / claude.ai and other MCP clients.

Both front-ends are thin adapters over one **core** that owns all YouTube
logic. Neither adapter talks to `googleapiclient` directly.

## Why (industry context, Oct 2026)

- For coding agents that have a shell, the current default is a CLI that
  prints JSON, plus a SKILL.md. It costs fewer tokens and composes with pipes
  and `jq`. Sources:
  - Willison on Skills: https://simonwillison.net/2025/Oct/16/claude-skills/
  - Anthropic, code execution with MCP: https://www.anthropic.com/engineering/code-execution-with-mcp
  - Cloudflare Code Mode: https://blog.cloudflare.com/code-mode/
  - Microsoft playwright-cli: https://github.com/microsoft/playwright-cli
  - Google `gws`, which dropped its `mcp` command in v0.8.0: https://github.com/googleworkspace/cli/releases/tag/v0.8.0
- MCP still matters for hosts with no shell, for remote/OAuth distribution, and
  for tool annotations. Zechner measured no real gap between the two when the
  tool is well designed: https://mariozechner.at/posts/2025-08-15-mcp-vs-cli/
- No single standard exists for sharing code between the two. The closest
  prior art:
  - Sentry's `getsentry/toolkit`: a small shared core, with separate `cli` and
    `mcp-server` packages that each own their own errors and UX.
  - Playwright: one tool registry serves both the CLI and MCP.
  - Chrome DevTools MCP: the CLI is generated from the MCP tools.
  - GitHub, Supabase, Stripe and Hugging Face: two separate codebases.
- Known pitfall: MCP tools should be coarse and shaped around workflows, while
  CLI commands can sit close to the API. Mirroring one 1:1 onto the other is a
  smell (https://www.anthropic.com/engineering/writing-tools-for-agents). This
  migration keeps today's 1:1 mapping, but the core is shaped so the two
  surfaces can diverge later (see "Later").

## Current state

- `main.py` (391 lines):
  - Pydantic models.
  - Response mappers (`_video`, `_channel`, `_page`).
  - 12 `@mcp.tool` functions that build API params, call the client and map
    results.
  - The `auth` subcommand.
- `auth.py`: builds the API key and OAuth clients. `token.json` and
  `client_secrets.json` live **next to the source file**, which stops working
  once the package is installed (`uv tool install`).
- `client.py`: smoke test that goes through the FastMCP in-memory client.
- No tests and no error mapping. Raw `HttpError`s leak out to the caller.
- `.env` is untracked and not in `.gitignore`.

The tool functions are already almost a core: typed params go in, Pydantic
models come out. The refactor is mostly moving code and removing the
`@mcp.tool` decorator.

## Target layout

```
src/youtube_kit/
  core/
    __init__.py      # public API: re-exports operations + models
    models.py        # Page, SearchHit, Video, Channel, PlaylistEntry, Comment, write results
    errors.py        # YouTubeError + subclasses, each with an exit_code
    auth.py          # token/secrets paths (platformdirs), OAuth flow, refresh
    client.py        # public()/oauth() resolvers; HttpError -> core errors
    ops.py           # the 12 operations + QUOTA_COST; split once it passes ~200 lines
  mcp_server.py      # FastMCP adapter
  cli.py             # cyclopts adapter, entry point `ytk`
skills/youtube/SKILL.md
tests/
```

`pyproject.toml` gets:

- a `[build-system]` section (`uv_build`). It is needed so that `uv run`
  installs the package editable.
- the dependency pin `fastmcp>=4.0.0b2,<4.1`.
- an explicit `cyclopts` dependency, so the CLI doesn't rely on it arriving
  transitively.
- the console script `ytk = "youtube_kit.cli:main"`.

`ytk mcp` runs the server over stdio, so one install gives you both
front-ends. Register it with `claude mcp add youtube -- uv --directory <repo>
run ytk mcp`, or with `-- ytk mcp` after `uv tool install`.

## Core design rules

1. **Operations are plain sync functions** with fully typed signatures
   (`Annotated[..., Field(ge=…, le=…)]`, `Literal`, Pydantic return types) and
   a **Google-style docstring with an `Args:` section**. That docstring is the
   single source of truth for parameter descriptions:
   - FastMCP 4 moves each `Args:` entry into the input schema.
   - cyclopts reads the `Args:` entries for `--help` but ignores
     `Field(description=…)` on function params.
   - Keep `Field` for constraints only. Both libraries enforce them; this was
     verified, e.g. `max_results=99` is rejected.
2. **No transport concerns in core**: no printing, no `sys.exit`, no FastMCP
   `Context`, no rich. Core raises `core.errors.*` and returns models.
3. **Client resolution, not a parameter.**
   - Operations call `core.client.public()` / `core.client.oauth()`, which
     resolve credentials lazily and cache them per process.
   - Tests swap in a `MagicMock` via `monkeypatch`. A ContextVar override also
     works across FastMCP's worker thread (verified), if that reads better.
   - Any extra parameter would leak into both the MCP schema and the CLI
     flags. FastMCP 4 has no `exclude_args`.
   - Use free functions, not a service class.
4. **`upload_video` takes `on_progress: Callable[[int, int], None] | None`.**
   Neither adapter can register it raw: FastMCP fails on the `Callable` schema,
   and cyclopts exposes a broken `--on-progress` flag. Each adapter therefore
   has a small hand-written wrapper:
   - **MCP:** a sync wrapper that takes `ctx: Context` and bridges with
     `anyio.from_thread.run(ctx.report_progress, done, total)`. Sync tools run
     on a worker thread, so calling `ctx.report_progress` directly would just
     return an un-awaited coroutine.
   - **CLI:** a progress line on stderr.
5. **Error taxonomy.** `client.py` translates `HttpError` by `reason`/status.
   Each class carries its CLI exit code, so the CLI and the skill can't drift.

   | Class | Trigger | Exit code |
   |---|---|---|
   | `QuotaExceeded` | `quotaExceeded` | 5 |
   | `NotAuthorized` | 401 / auth 403 | 4 |
   | `NotFound` | 404 / empty items | 3 |
   | `InvalidRequest` | 400 | 2 |

   Messages tell an agent what to do next, e.g. "Run `ytk auth login`".
6. **Quota cost**: each operation declares its unit cost in `QUOTA_COST`
   (search=100, upload=1600, writes=50, reads=1). The cost goes on one line
   appended to the MCP tool description and to the CLI help.

## Adapters

### Shared error wrapper

FastMCP masks any non-`FastMCPError` exception before middleware can see it
(`fastmcp/server/server.py:1540-1557`). Error mapping therefore has to happen
**per function**:

- `mcp_server.as_tool(op)` is a `functools.wraps` wrapper that catches
  `YouTubeError` and raises `ToolError(str(e))`.
- `ToolError` passes through `mask_error_details=True` unmasked.
- The wrapper keeps the schema, docstring and `Args` descriptions intact
  (verified by the reviewer).

### MCP (`mcp_server.py`)

```python
mcp = FastMCP("YouTube", mask_error_details=True)
for op, annotations in core.OPERATIONS:
    mcp.tool(as_tool(op), annotations=annotations)
mcp.tool(upload_video_tool, annotations=...)  # Context-aware wrapper
```

- Tool names and input schemas stay **identical** to today. A `list_tools()`
  snapshot (`input_schema` / `output_schema`) enforces this and doubles as the
  gate for FastMCP upgrades.
- Annotations:
  - Read operations get `readOnlyHint=True`.
  - Writes get `destructiveHint=False`.
  - `update_video` and `set_thumbnail` also get `idempotentHint=True`.

### CLI (`cli.py`, cyclopts)

Commands are grouped by noun, and their names are generated from the same
functions:

```
ytk search QUERY [--kind video] [--max-results 10] [--order …] [--channel-id …]
ytk video get ID...        ytk video update ID [--title …] [--tags …|--empty-tags]
ytk video upload FILE --title …           ytk video thumbnail ID IMAGE
ytk channel get [--id …|--handle @x]      ytk channel mine
ytk playlist items PLAYLIST_ID [--all]    ytk playlist create TITLE
ytk playlist add PLAYLIST_ID VIDEO_ID
ytk comments VIDEO_ID      ytk categories [--region US]
ytk auth login | status | logout          # status prints resolved token path + source
ytk mcp
```

- **Output:** always JSON on stdout (`model_dump(mode="json",
  exclude_none=True)`), one document per invocation. It is emitted through
  `App(result_action=…)`, which skips `None` (as on `--help`). No TTY
  auto-detection: agents sometimes run under a pty, so output would depend on
  the harness. Humans can use `jq`.
- **Errors:** go to stderr as `{"error": …, "type": …}` JSON.
  - `main()` runs the app with `exit_on_error=False`.
  - It maps `CycloptsError` to exit code 2. cyclopts' default would be 1.
  - It maps `YouTubeError` to its class's `exit_code`.
  - Anything else exits with 1.
- **Pagination:**
  - `--page-token` for parity with MCP.
  - `--all` / `--limit N`, which iterate through a `core.paginate()` generator.
- Use positional args only where they're unambiguous: IDs, the query, file
  paths.
- Per-command wrappers are fine where CLI ergonomics differ, e.g. variadic
  IDs. The CLI does **not** have to mirror MCP 1:1.

### Agent Skill (`skills/youtube/SKILL.md`)

A short skill that covers:

- one line per command,
- the JSON output and exit-code contract,
- quota costs,
- 3–4 recipes, e.g. `ytk channel get --handle @x | jq -r .uploads_playlist_id
  | xargs ytk playlist items --limit 20`.

Bootstrap it from `fastmcp generate-cli`'s SKILL.md output, then edit it by
hand. For Claude Code users it replaces the MCP tool schemas that would
otherwise be loaded into context on every session.

## Auth and config

- Token and secrets move to the `platformdirs` user config dir. Env overrides:
  `YOUTUBE_TOKEN_FILE`, `YOUTUBE_CLIENT_SECRETS`.
- On first use, an existing repo-local `token.json` is migrated.
- `client_secrets.json` is only needed for `auth login`, because `token.json`
  already embeds the client id and secret.
- `YOUTUBE_API_KEY` is unchanged. Both adapters read the same config, so a
  single `ytk auth login` authorizes both.
- Token writes are atomic (temp file + rename).
  - Installed-app refresh tokens don't rotate, so a CLI refresh and an MCP
    refresh happening at the same time are harmless.

## Testing

- **Core:**
  - Fakes are a `MagicMock` that mirrors the `.videos().list(**p).execute()`
    chain. It returns canned responses and allows assertions on params.
  - Coverage: param building, response mapping, `HttpError` translation.
  - Most of the tests live here.
- **MCP:**
  - In-memory `fastmcp.Client`.
  - A `list_tools()` snapshot.
  - One call per error type, asserting the `ToolError` text.
- **CLI:** invoke the app with argv and capture stdout/stderr. Covers JSON
  shape, exit codes, `--all` pagination and `--empty-tags`.
- **Live:** `client.py` becomes `tests/live/`, gated on `YOUTUBE_API_KEY`.

## Migration steps (each step leaves the server working)

0. **Safety net**:
   - Add `.env` to `.gitignore`.
   - Add pytest.
   - Write the `list_tools()` snapshot test against the **current** server.
   - Write the fake-client fixture.
1. **Package + core extraction**:
   - src layout, `[build-system]`.
   - Move models, mappers and auth into `core`.
   - `mcp_server.py` registers plain functions.
   - The snapshot shows no diff.
   - Drop `main.py` and re-register Claude Code as `uv run ytk mcp`.
2. **Errors**: `core/errors.py`, `HttpError` translation, the `as_tool`
   wrapper, `mask_error_details=True`, core and MCP error tests.
3. **Config dir + `ytk auth login/status/logout`**, including the token
   migration.
4. **CLI**: cyclopts app, the output and exit-code contract, pagination, the
   upload wrapper, CLI tests.
5. **Skill + docs**:
   - `SKILL.md`.
   - README rewrite, CLI first and MCP second.
   - `docs/adr/0001-shared-core-cli-and-mcp.md` recording this decision and
     the alternatives below.

Steps 2 and 3 are independent of each other.

## Later (not in this migration)

- Composite, quota-aware MCP tools built from core ops. Example:
  `video_overview` = details + top comments. They would exist in MCP only; the
  CLI gets the same result from pipes.
- `--format table` for humans, but only if someone actually asks for it.
- NDJSON streaming for `--all`, if long listings become common.

## Alternatives considered

- **`fastmcp generate-cli`.** MCP stays the source of truth, and a generated
  script calls the server as an MCP client. Downsides:
  - Every call spawns the server and does an MCP handshake.
  - The generated script goes stale as the tools change.
  - It drops empty lists from arguments, so it could never clear tags.

  Fine as a stopgap, not as the CLI.
- **CLI only, drop MCP.** Viable for Claude Code use alone, but the MCP
  adapter is about 40 lines once the core exists. It is also the only option
  for hosts with no shell.
- **Service class instead of free functions.** Revisit if shared state
  appears, such as caching or quota accounting across calls.

## Decisions on former open questions

- **Name**: the command is `ytk` and the package is `youtube-kit`. `yt` is
  already a PyPI console script (the yt astrophysics package) and is easy to
  confuse with `yt-dlp`. The repo can be renamed whenever; GitHub redirects
  the old URL.
- **Output**: always JSON (see CLI).
- **FastMCP**: `>=4.0.0b2,<4.1`. Upgrade deliberately with `uv lock
  --upgrade-package fastmcp`, with the snapshot test as the gate.
