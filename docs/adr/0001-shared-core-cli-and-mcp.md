# 0001. One core, two adapters: CLI first, MCP alongside

Date: 2026-10-16. Status: accepted.

## Context

The project started as a FastMCP server. Coding agents that have a shell increasingly prefer CLIs plus a short skill over MCP tool schemas. A CLI costs no context until it is called, composes with `jq`, and its intermediate results never pass through the model. MCP still matters for clients without a shell. Prior art splits three ways:

- Sentry's toolkit shares a small core between its CLI and MCP packages.
- Chrome DevTools MCP and FastMCP's `generate-cli` derive a CLI from MCP tools.
- GitHub, Stripe and Supabase maintain two separate codebases.

## Decision

`youtube_kit.core` holds every operation as a plain, synchronous, typed function. Each function has a Google-style docstring and a Pydantic return type. `cli.py` (cyclopts) and `mcp_server.py` (FastMCP) register those functions directly. The signature and docstring are the single source of truth for CLI flags and `--help`, and also for the MCP input schema and descriptions.

Rules that keep it that way:

- Core never prints, exits, or imports FastMCP or cyclopts. It raises `core.errors.YouTubeError` subclasses, and each carries a `kind` and a CLI `exit_code`.
- `@operation` records quota cost and side effects. It appends the cost to the docstring and translates API, auth, and network exceptions into domain errors. Adapters read the metadata to render MCP annotations.
- Primary inputs are positional and everything else is keyword-only, so the CLI never takes an option positionally.
- Pagination lives in core as `limit` plus `page_token`, so both front ends get the same semantics without adapter-side loops.
- Core normalises inputs: IDs or pasted URLs, `@handles`, plain dates.
- Cross-cutting concerns that must not appear in signatures (upload progress) travel through a `ContextVar` (`core.progress`). Each adapter installs its own reporter: a TTY progress line, or MCP progress notifications.
- The MCP adapter wraps each operation to turn `YouTubeError` into `ToolError`. FastMCP masks any other exception before middleware runs, so the translation has to sit in that wrapper.
- `tests/test_surface.py` fails if either adapter misses an operation. `tests/snapshots/mcp/` (one file per tool) pins the MCP tool surface and gates FastMCP upgrades.

## Alternatives rejected

- **Generate the CLI from the MCP server (`fastmcp generate-cli`).** Every call would spawn the server and run an MCP handshake. The generated file goes stale. It drops empty-list arguments, so tags could never be cleared.
- **CLI only.** Clients without a shell would lose access. The MCP adapter is about 80 lines.
- **A service class instead of free functions.** It adds nothing until operations share state. Free functions register one-to-one with both libraries.

## Consequences

- Adding an operation means writing one decorated function in `core/ops/` and naming its CLI command in `cli.py`. MCP picks it up automatically.
- An MCP-only composite tool, built from several core operations to save round trips, can be added to `mcp_server.TOOLS` later. The surface test should then gain an explicit exception list.
- Changing a core signature changes both front ends at once. The MCP snapshot makes that change visible in review.
