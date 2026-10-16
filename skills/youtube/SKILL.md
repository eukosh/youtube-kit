---
name: youtube
description: YouTube through the `ytk` CLI. Use for any task that reads YouTube data (search, videos, channels, playlists, comments) or changes the user's own channel (upload, edit metadata, thumbnails, playlists).
---

# YouTube via `ytk`

`ytk` wraps the YouTube Data API v3. Commands:

```
ytk search QUERY                   ytk channel get CHANNEL      ytk channel mine
ytk video get VIDEO...             ytk video comments VIDEO     ytk video categories
ytk video upload FILE --title T    ytk video update VIDEO       ytk video thumbnail VIDEO IMAGE
ytk playlist items PLAYLIST        ytk playlist create TITLE    ytk playlist add PLAYLIST VIDEO
ytk auth status | login | logout
```

`ytk <command> --help` is the source of truth for flags. Inputs are forgiving: VIDEO, CHANNEL, and PLAYLIST take IDs or pasted YouTube URLs, CHANNEL also takes `@handle`, and dates take `2026-01-01` or full ISO datetimes. Options are flags (`--limit 20`); list options repeat (`--tags a --tags b`; `--empty-tags` clears). A video ID starting with `-` would read as a flag: put it after `--` or pass the URL.

## Output contract

- stdout: exactly one JSON document, null fields omitted. Pipe it into `jq`.
- Listings are `{"items": [...], "next_page_token": "..."}`. `--limit N` fetches across pages for you; pass `--page-token` to continue past it.
- Failure: stdout is empty, stderr is `{"error": {"type", "message"}}`, and the exit code names the type:

| exit | type | what to do |
|---|---|---|
| 2 | `invalid_request` / usage | fix the arguments (message says which) |
| 3 | `not_found` | the ID or handle doesn't exist or isn't visible |
| 4 | `not_authorized` | ask the user to run `ytk auth login` (interactive, opens a browser) or set `YOUTUBE_API_KEY` |
| 5 | `quota_exceeded` | stop; quota resets at midnight Pacific Time |
| 6 | `forbidden` | YouTube refuses (comments disabled, unverified channel for thumbnails, …) |
| 7 | `network` | retry once |

## Quota

The project has 10,000 units a day. Reads cost 1 unit per request, `search` 100 per page of 50, writes 50, `video upload` 1600 (each command's `--help` states its cost). Prefer the cheap path: to find a channel's recent videos, use `channel get` → `uploads_playlist_id` → `playlist items` → `video get`, rather than `search --channel`.

## Recipes

```bash
# Latest 10 uploads of a channel, with view counts
ytk playlist items "$(ytk channel get @mkbhd | jq -r .uploads_playlist_id)" --limit 10 \
  | jq -r '.items[].video_id' | xargs ytk video get | jq '.[] | {title, views: .stats.views}'

# Videos longer than 20 minutes from a list of URLs
ytk video get URL1 URL2 | jq '.[] | select(.duration_seconds > 1200) | .url'

# Schedule a private upload, then add it to a playlist
id=$(ytk video upload clip.mp4 --title "Launch" --publish-at 2026-07-01T15:00:00Z | jq -r .id)
ytk playlist add PLxxxx "$id"
```

Account commands (`channel mine`, `video upload/update/thumbnail`, `playlist create/add`) act on the user's real channel: confirm with the user before running them.
