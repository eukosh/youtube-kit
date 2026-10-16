# youtube-kit

The YouTube Data API v3 from your terminal (`ytk`) and from MCP clients, both running the same code.

The CLI comes first. Coding agents with a shell (Claude Code, Codex) use it through a short [skill](skills/youtube/SKILL.md). It costs no context until called, and its output pipes into `jq`. The MCP server (`ytk mcp`) exposes the same operations as tools, for clients that have no shell.

```sh
ytk channel get @mkbhd | jq '{title, subscribers: .stats.subscribers}'
ytk playlist items "$(ytk channel get @mkbhd | jq -r .uploads_playlist_id)" --limit 3 | jq -r '.items[].url'
```

## Install

```sh
uv tool install /path/to/youtube-kit      # puts `ytk` on your PATH
# or, from a checkout:
uv run ytk --help
```

## Credentials

Public data (search, videos, channels, playlists, comments) works with an API key. Your own channel (uploads, edits, deletes, playlists, comment moderation) needs OAuth.

1. In [Google Cloud Console](https://console.cloud.google.com), create a project and enable **YouTube Data API v3** (and **YouTube Analytics API** for `ytk analytics`).
2. Public data: create an API key and `export YOUTUBE_API_KEY=...`. Without a key, `ytk` falls back to your OAuth login for public data too.
3. Your channel: create an OAuth client ID of type *Desktop app* and save its JSON where `ytk auth status` says `client_secrets_file` lives. Then run `ytk auth login` once. It opens a browser and stores a token that the CLI and the MCP server share. It asks for YouTube and YouTube Analytics access; if you logged in before analytics existed here, log in again.

Credentials live in the user config directory (`~/Library/Application Support/youtube-kit/` on macOS). `YOUTUBE_TOKEN_FILE`, `YOUTUBE_CLIENT_SECRETS` and `YOUTUBE_CONFIG_FILE` override the paths.

## CLI

Commands are `ytk <noun> <verb>` (`video`, `playlist`, `comment`, `channel`, `auth`), plus `ytk search`, `ytk analytics` and `ytk mcp`. `ytk --help` lists them, and [the skill](skills/youtube/SKILL.md) has the full map.

Every command prints one JSON document on stdout. On failure stdout stays empty, stderr gets `{"error": {"type", "message", "details"?}}`, and the exit code tells you what went wrong: 2 bad input, 3 not found, 4 not authorized, 5 quota exceeded, 6 forbidden, 7 network, 8 confirmation required, 9 protected, 10 timeout. Video, channel and playlist arguments accept IDs or pasted URLs; channels also take `@handle`.

To let Claude Code use it, link the skill:

```sh
ln -s "$PWD/skills/youtube" ~/.claude/skills/youtube
```

## Deleting

Most usage comes through agents, so deletes are guarded:

- **Two steps.** The first call deletes nothing. At a terminal you get a `[y/N]` prompt. An agent gets exit 8 with a description of the target and must re-run with `--confirm <id>`, so approval always names the exact thing being deleted.
- **Damage limit.** A video with more than 100 views, or public and uploaded more than 7 days ago, can't be deleted here at all; use YouTube Studio. Change the limits in `config.toml` in the config directory (or `YOUTUBE_CONFIG_FILE`):

  ```toml
  [delete_protection]
  max_views = 100
  max_public_age_days = 7
  ```
- **Harness approval.** Have your agent ask you before every delete; see the permission snippet in the skill.
- **Idempotent.** Deleting something already gone succeeds with `"already_gone": true`.

This stops mistakes, not a determined agent: anything holding your OAuth token can call the API directly.

## MCP server

```sh
claude mcp add youtube -- ytk mcp
# from a checkout instead of an installed tool:
claude mcp add youtube -- uv --directory /path/to/youtube-kit run ytk mcp
```

Pass `-e YOUTUBE_API_KEY=...` to `claude mcp add` if the key isn't in the environment the client starts servers with.

## Quota

The default allowance is 10,000 units a day, resetting at midnight Pacific. Reads cost 1 unit per request, `search` 100 per page of 50 results, writes 50, and an upload 1600. Each command's `--help` and each tool description states its cost.

## Development

```sh
uv run pytest                                      # offline; the API is faked
LIVE_YOUTUBE_API_KEY=... uv run pytest -m live     # a few real API calls
UPDATE_SNAPSHOTS=1 uv run pytest tests/test_mcp.py # after an intended MCP tool change
```

How it fits together is in [ADR 0001](docs/adr/0001-shared-core-cli-and-mcp.md). In short, `core/` holds every operation as a plain typed function, and `cli.py` and `mcp_server.py` are thin adapters over it. A test fails if either adapter misses an operation.
