# youtube-kit

[![CI](https://github.com/eukosh/youtube-kit/actions/workflows/ci.yml/badge.svg)](https://github.com/eukosh/youtube-kit/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/youtube-kit)](https://pypi.org/project/youtube-kit/)
[![Python](https://img.shields.io/pypi/pyversions/youtube-kit)](https://pypi.org/project/youtube-kit/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue)](https://github.com/eukosh/youtube-kit/blob/main/LICENSE)

Your YouTube channel from the terminal and from AI agents. `ytk` is a CLI over the YouTube Data and Analytics APIs that prints JSON, and `ytk mcp` serves the same operations to MCP clients.

```sh
ytk channel get @mkbhd | jq '{title, subscribers: .stats.subscribers}'
ytk analytics --by video --since 90d --limit 5     # your top videos of the last 90 days
ytk comment list --status held                     # comments waiting for review on your channel
```

- **Built for agents, pleasant for people.** One JSON document on stdout, structured errors on stderr, a distinct exit code per failure. Coding agents with a shell use it through a short [skill](#use-it-from-an-agent) that they load only when a YouTube task comes up.
- **One core, two surfaces.** Every operation is a typed function. The CLI and the MCP server are thin adapters over it, and a test fails if either one misses an operation.
- **Safe deletes.** Deleting needs a confirmation that names the exact target, and popular or long-public videos can't be deleted at all. [Details below.](#deleting)
- **Quota-aware.** Each command's `--help` (and each MCP tool description) states its quota cost.

## What it covers

| Area | Commands |
|---|---|
| Search | `search` across videos, channels and playlists |
| Videos | get, upload (resumable), update, thumbnail, processing status, rate, delete |
| Playlists | list, get, items, create, update, thumbnail, add, remove, move, delete |
| Comments | list (including held for review and likely spam), replies, post, reply, edit, delete, approve, hold, reject and ban |
| Channel | get, recent activity, about info, banner, watermark, home page sections |
| Subscriptions | list, subscribe, unsubscribe |
| Analytics | totals or breakdowns by day, month, video, country, device, traffic source, age, gender and more |

`ytk --help` lists everything; the [skill](https://github.com/eukosh/youtube-kit/blob/main/skills/youtube/SKILL.md) has the full command map.

## Install

`ytk` installs as a global command in its own isolated environment, with [uv](https://docs.astral.sh/uv/):

```sh
uv tool install youtube-kit
ytk --help
```

No uv yet? Install it first with `brew install uv` or `curl -LsSf https://astral.sh/uv/install.sh | sh`. uv fetches a suitable Python by itself.

- Upgrade with `uv tool upgrade youtube-kit`, and remove with `uv tool uninstall youtube-kit`.
- With pipx instead: `pipx install youtube-kit` (needs Python 3.12 or newer).
- To try it without installing: `uvx --from youtube-kit ytk --help`.

## Credentials

Public data (search, videos, channels, playlists, comments) works with an API key. Anything on your own channel (uploads, edits, deletes, comment moderation, branding, subscriptions, ratings, analytics) needs an OAuth login.

1. In the [Google Cloud Console](https://console.cloud.google.com), create a project and enable **YouTube Data API v3**, plus **YouTube Analytics API** for `ytk analytics`.
2. **API key** for public data: create one and `export YOUTUBE_API_KEY=...`. Without a key, `ytk` uses your OAuth login for public data too.
3. **OAuth** for your channel:
   1. Configure the OAuth consent screen (user type *External*) and add your Google account as a test user.
   2. Create an OAuth client ID of type *Desktop app*, download its JSON, and save it where `ytk auth status` says `client_secrets_file` lives.
   3. Run `ytk auth login`. It opens a browser and stores a token that the CLI and the MCP server share.

> [!NOTE]
> While the consent screen is in *Testing* status, Google expires the login after 7 days and you need to run `ytk auth login` again. To keep it, set the publishing status to *In production*. Google then shows an "unverified app" warning at login, which is expected for your own client; continue past it.

Credentials and `config.toml` live in the user config directory (`~/Library/Application Support/youtube-kit/` on macOS, `~/.config/youtube-kit/` on Linux); `ytk auth status` prints the exact paths. These environment variables override them:

| Variable | Purpose |
|---|---|
| `YOUTUBE_API_KEY` | API key for public data |
| `YOUTUBE_CLIENT_SECRETS` | Path to the OAuth client JSON |
| `YOUTUBE_TOKEN_FILE` | Path to the stored login |
| `YOUTUBE_CONFIG_FILE` | Path to `config.toml` (delete limits) |

## Use it from an agent

**Shell agents (Claude Code, Codex and others)** use the CLI through the skill. For Claude Code:

```sh
mkdir -p ~/.claude/skills/youtube
curl -fsSL https://raw.githubusercontent.com/eukosh/youtube-kit/main/skills/youtube/SKILL.md \
  -o ~/.claude/skills/youtube/SKILL.md
```

**MCP clients** run the server with `ytk mcp`. The examples below use `uvx`, which comes with [uv](https://docs.astral.sh/uv/). For Claude Code:

```sh
claude mcp add youtube -- uvx --from youtube-kit ytk mcp
```

For clients configured with JSON (Claude Desktop, Cursor and others):

```json
{
  "mcpServers": {
    "youtube": {
      "command": "uvx",
      "args": ["--from", "youtube-kit", "ytk", "mcp"],
      "env": { "YOUTUBE_API_KEY": "..." }
    }
  }
}
```

The API key is optional; without it the server uses your `ytk auth login` token.

## Output and exit codes

Every command prints one JSON document on stdout, with null fields left out. On failure stdout stays empty and stderr gets:

```json
{"error": {"type": "not_found", "message": "Video abc123def45 not found."}}
```

The exit code names the type: 2 bad input, 3 not found, 4 not authorized, 5 quota exceeded, 6 forbidden, 7 network, 8 confirmation required, 9 protected, 10 timeout, 1 anything else. The [skill](https://github.com/eukosh/youtube-kit/blob/main/skills/youtube/SKILL.md#output-contract) says what an agent should do about each.

Video, channel and playlist arguments take IDs or pasted URLs; channels also take an `@handle`.

## Deleting

Agents make mistakes, so deleting videos, playlists and comments is guarded:

- **Two steps.** The first call deletes nothing. At a terminal you get a `[y/N]` prompt. An agent gets exit 8 with a description of the target and must run the command again with `--confirm <id>`, so the approval always names the exact thing being deleted.
- **Damage limit.** A video with more than 100 views, or one that is public and was uploaded more than 7 days ago, can't be deleted here at all; use YouTube Studio. The limits live in `config.toml` (`ytk auth status` shows where):

  ```toml
  [delete_protection]
  max_views = 100
  max_public_age_days = 7
  ```
- **Harness approval.** Have your agent ask you before every delete; the skill has a Claude Code permission snippet for it.
- **Idempotent.** Deleting something that is already gone succeeds with `"already_gone": true`.

This stops mistakes, not a determined agent: anything holding your OAuth token can call the API directly.

## Quota

Google gives each Cloud project 10,000 units a day, resetting at midnight Pacific time. Reads cost 1 unit per request, `search` 100 per page of 50 results, most writes 50 (deletes a couple more, for the lookup and ownership check), and an upload 1,600. Analytics has its own separate quota.

## Contributing

Bug reports and pull requests are welcome. See [CONTRIBUTING.md](https://github.com/eukosh/youtube-kit/blob/main/CONTRIBUTING.md) for the development setup, [CHANGELOG.md](https://github.com/eukosh/youtube-kit/blob/main/CHANGELOG.md) for what changed, and [ADR 0001](https://github.com/eukosh/youtube-kit/blob/main/docs/adr/0001-shared-core-cli-and-mcp.md) for how the code fits together. Report security issues privately, as described in [SECURITY.md](https://github.com/eukosh/youtube-kit/blob/main/SECURITY.md).

## License

[MIT](https://github.com/eukosh/youtube-kit/blob/main/LICENSE). youtube-kit is not affiliated with or endorsed by Google or YouTube. YouTube is a trademark of Google LLC.
