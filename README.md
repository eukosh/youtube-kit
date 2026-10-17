# youtube-kit

[![CI](https://github.com/eukosh/youtube-kit/actions/workflows/ci.yml/badge.svg)](https://github.com/eukosh/youtube-kit/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/youtube-kit)](https://pypi.org/project/youtube-kit/)
[![Python](https://img.shields.io/pypi/pyversions/youtube-kit)](https://pypi.org/project/youtube-kit/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue)](https://github.com/eukosh/youtube-kit/blob/main/LICENSE)

Most YouTube CLIs and MCP servers do one thing. They upload, or they pull analytics, or they search and stop there. `ytk` does 44 things, which is most of what the YouTube Data and Analytics APIs allow for a channel, and it prints JSON. `ytk mcp` serves the same 44 operations to MCP clients.

```sh
ytk channel get @mkbhd | jq '{title, subscribers: .stats.subscribers}'
ytk analytics --by video --since 90d --limit 5     # your top videos of the last 90 days
ytk comment list --status held                     # comments waiting for review on your channel
```

## What it covers

| Area | Operations |
|---|---|
| Search | videos, channels and playlists, filtered by channel or date |
| Videos | get, categories, upload (resumable, with progress), update metadata, set thumbnail, wait for processing, like or dislike, check your rating, delete |
| Playlists | list, get, items, create, update, set image, add, remove, move, delete |
| Comments | list (published, held for review, likely spam, rejected), replies, post, reply, edit, delete, approve, hold, reject, ban the author |
| Channel | get, recent activity, your logged-in channels (several at once), about info (description, keywords, country, language, trailer), banner, watermark, home page sections |
| Subscriptions | list, subscribe, unsubscribe |
| Analytics | totals, or breakdowns by day, month, video, country, device, OS, traffic source, playback location, age, gender or subscribed status |

Not covered: captions, localizations, live streaming and channel memberships. `ytk --help` lists every command, and the [skill](https://github.com/eukosh/youtube-kit/blob/main/skills/youtube/SKILL.md) fits them all on one page with `jq` recipes.

A few decisions you'll notice once a script or an agent drives it:

- One JSON document on stdout, a JSON error on stderr, and an exit code per failure type. `jq` and agents branch on the code instead of parsing messages.
- The CLI and the MCP server are thin adapters over one core, and a test fails if either misses an operation. The two never disagree about what exists.
- Deleting takes two calls, and the second must name the exact target. Videos past 100 views or a week of being public can't be deleted here at all. See [Deleting](#deleting).
- Each command's `--help` and each MCP tool description states its quota cost, so you know what a loop will burn before you run it.
- Arguments take IDs or pasted YouTube URLs, channels also take an `@handle`, and `--since` takes dates or spans like `90d`.

## Install

`ytk` installs as a global command in its own isolated environment, with [uv](https://docs.astral.sh/uv/):

```sh
uv tool install youtube-kit
ytk --help
```

No uv yet? Install it with `brew install uv` or `curl -LsSf https://astral.sh/uv/install.sh | sh`. uv fetches a suitable Python by itself.

- Upgrade with `uv tool upgrade youtube-kit`, and remove with `uv tool uninstall youtube-kit`.
- With pipx instead: `pipx install youtube-kit` (needs Python 3.12 or newer).
- To try it without installing: `uvx --from youtube-kit ytk --help`.

## Credentials

Public data (search, videos, channels, playlists, comments) works with an API key. Anything on your own channel (uploads, edits, deletes, comment moderation, branding, subscriptions, ratings, analytics) needs an OAuth login.

1. In the [Google Cloud Console](https://console.cloud.google.com), create a project and enable **YouTube Data API v3**, plus **YouTube Analytics API** for `ytk analytics`.
2. For public data, create an **API key** and `export YOUTUBE_API_KEY=...`. Without a key, `ytk` uses your OAuth login for public data too.
3. For your own channel, set up **OAuth**:
   1. Configure the OAuth consent screen (user type *External*) and add your Google account as a test user.
   2. Create an OAuth client ID of type *Desktop app*, download its JSON, and save it where `ytk auth status` says `client_secrets_file` lives.
   3. Run `ytk auth login`. It opens a browser, asks which channel to authorize, and stores a token that the CLI and the MCP server share. Run it again for each further channel (see [Several channels](#several-channels)).

> [!NOTE]
> While the consent screen is in *Testing* status, Google expires the login after 7 days and you need to run `ytk auth login` again. To keep it, set the publishing status to *In production*. Google then shows an "unverified app" warning at login, which is expected for your own client. Continue past it.

Credentials and `config.toml` live in the user config directory (`~/Library/Application Support/youtube-kit/` on macOS, `~/.config/youtube-kit/` on Linux). `ytk auth status` prints the exact paths. These environment variables override them:

| Variable | Purpose |
|---|---|
| `YOUTUBE_API_KEY` | API key for public data |
| `YOUTUBE_CLIENT_SECRETS` | Path to the OAuth client JSON |
| `YOUTUBE_TOKEN_DIR` | Directory of stored logins, one file per channel |
| `YOUTUBE_CHANNEL` | Channel to work on by default (UC… ID or @handle), overriding `ytk auth switch` |
| `YOUTUBE_CONFIG_FILE` | Path to `config.toml` (delete limits) |

### Several channels

A Google login authorizes one channel, so each channel you manage gets its own `ytk auth login`. That includes brand-account channels under the same Google account: pick the channel when Google asks which account to use. The OAuth client and API key stay the same for all of them.

```sh
ytk auth login                            # once per channel
ytk channel mine                          # logged-in channels; one is marked "default": true
ytk auth switch @second                   # change the default
ytk video upload clip.mp4 --title Hi --my-channel @third   # use another channel for one command
ytk auth logout @third
```

The first channel you log in to becomes the default. Every command that calls YouTube works on the default unless `--my-channel` names another logged-in channel, and `YOUTUBE_CHANNEL` overrides the default for one shell or one MCP server. Deleting a video, playlist or comment checks it belongs to the channel you're working on, so picking the wrong channel makes the delete fail instead of reaching the other channel.

All channels share the Cloud project's daily quota of 10,000 units. `ytk` remembers each channel's handle from the moment you logged in, so after renaming a channel on YouTube, name it by its UC… ID or run `ytk auth login` for it again.

## Use it from an agent

**Shell agents (Claude Code, Codex, Cursor and others)** use the CLI through a short skill that loads only when a YouTube task comes up. Install it with [skills](https://github.com/vercel-labs/skills), which asks which agents to add it to:

```sh
npx skills add eukosh/youtube-kit -g
```

`npx skills update` pulls newer versions of the skill later.

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

The API key is optional. Without it, the server uses your `ytk auth login` token.

With several channels logged in, MCP tools work on the default channel. Each tool also takes a `my_channel` argument, and `list_my_channels` tells the model which channels it can choose from, so you can name the channel in your request ("upload this to my gaming channel"). To give a server its own default channel, add `"YOUTUBE_CHANNEL": "@handle"` to its `env`. Tools can still name another of your channels with `my_channel`.

In the ChatGPT desktop app, open Settings → MCP servers → Add server, choose STDIO, and enter `uvx --from youtube-kit ytk mcp` as the command. ChatGPT shares this setting with Codex, so `codex mcp add youtube -- uvx --from youtube-kit ytk mcp` does the same from a terminal.

## Output and exit codes

Every command prints one JSON document on stdout, with null fields left out. On failure stdout stays empty and stderr gets:

```json
{"error": {"type": "not_found", "message": "Video abc123def45 not found."}}
```

The exit code names the type: 2 bad input, 3 not found, 4 not authorized, 5 quota exceeded, 6 forbidden, 7 network, 8 confirmation required, 9 protected, 10 timeout, 1 anything else. The [skill](https://github.com/eukosh/youtube-kit/blob/main/skills/youtube/SKILL.md#output-contract) tells agents what to do about each.

## Deleting

YouTube has no trash, and agents make mistakes. So deleting videos, playlists and comments is guarded:

- **Two steps.** The first call deletes nothing. At a terminal you get a `[y/N]` prompt. An agent gets exit 8 with a description of the target and must run the command again with `--confirm <id>`, so the approval always names the exact thing being deleted.
- **Damage limit.** A video with more than 100 views, or one that is public and was uploaded more than 7 days ago, can't be deleted here at all (exit 9). Delete those in YouTube Studio. The limits live in `config.toml` (`ytk auth status` shows where):

  ```toml
  [delete_protection]
  max_views = 100
  max_public_age_days = 7
  ```
- **Harness approval.** Have your agent ask you before every delete. In Claude Code, add this to `.claude/settings.json`:

  ```json
  {"permissions": {"ask": ["Bash(ytk video delete:*)", "Bash(ytk playlist delete:*)", "Bash(ytk comment delete:*)"]}}
  ```
- **Idempotent.** Deleting something that is already gone succeeds with `"already_gone": true`.

This stops mistakes, not a determined agent. Anything holding your OAuth token can call the API directly.

## Quota

Google gives each Cloud project 10,000 units a day, resetting at midnight Pacific time. Reads cost 1 unit per request, `search` 100 per page of 50 results, most writes 50, guarded deletes 52 (they look up the target and check ownership first), and an upload 1,600. `ytk analytics` uses the separate YouTube Analytics API quota.

## Contributing

See [CONTRIBUTING.md](https://github.com/eukosh/youtube-kit/blob/main/CONTRIBUTING.md) for the development setup, [CHANGELOG.md](https://github.com/eukosh/youtube-kit/blob/main/CHANGELOG.md) for what changed, and [ADR 0001](https://github.com/eukosh/youtube-kit/blob/main/docs/adr/0001-shared-core-cli-and-mcp.md) for how the core and adapters fit together. Report security issues privately, as [SECURITY.md](https://github.com/eukosh/youtube-kit/blob/main/SECURITY.md) describes.

## License

[MIT](https://github.com/eukosh/youtube-kit/blob/main/LICENSE). youtube-kit is not affiliated with or endorsed by Google or YouTube. YouTube is a trademark of Google LLC.
