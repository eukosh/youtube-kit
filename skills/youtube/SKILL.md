---
name: youtube
description: YouTube through the `ytk` CLI. Use for any task that reads YouTube data (search, videos, channels, playlists, comments, activity) or changes the user's own channel (upload, edit, delete, thumbnails, playlists, comments and moderation).
---

# YouTube via `ytk`

`ytk` wraps the YouTube Data API v3. Commands:

```
ytk search QUERY [--since D]
ytk analytics [--since D] [--until D] [--by day|video|country|device|traffic-source|…] [--metrics M]... [--videos V]...

ytk video get VIDEO...             ytk video categories
ytk video upload FILE --title T    ytk video status VIDEO [--wait]  ytk video update VIDEO
ytk video thumbnail VIDEO IMAGE    ytk video delete VIDEO
ytk video rate VIDEO like|dislike|none                              ytk video rating VIDEO...

ytk playlist list [CHANNEL]        ytk playlist get PLAYLIST...     ytk playlist items PLAYLIST
ytk playlist create TITLE          ytk playlist update PLAYLIST     ytk playlist thumbnail PLAYLIST IMAGE
ytk playlist add PLAYLIST VIDEO    ytk playlist remove PLAYLIST VIDEO
ytk playlist move PLAYLIST VIDEO --position N                       ytk playlist delete PLAYLIST

ytk comment list [VIDEO] [--status held|spam|rejected] [--search Q]
ytk comment replies COMMENT        ytk comment post VIDEO TEXT      ytk comment reply COMMENT TEXT
ytk comment edit COMMENT TEXT      ytk comment delete COMMENT
ytk comment approve|hold COMMENT...                                 ytk comment reject COMMENT... [--ban-author]

ytk channel get [CHANNEL]          ytk channel activity [CHANNEL]
ytk channel update [--description] [--keywords K]... [--country] [--language] [--trailer VIDEO]
ytk channel banner IMAGE           ytk channel watermark set IMAGE  ytk channel watermark remove
ytk channel section list [CHANNEL] | add KIND | update SECTION | delete SECTION

ytk subscription list              ytk subscription add CHANNEL     ytk subscription remove CHANNEL
ytk auth status | login | logout
```

An omitted CHANNEL means the user's own channel; an omitted VIDEO in `comment list` means all of the user's videos. COMMENT takes a comment ID or its link (a video URL with `&lc=`).

`ytk <command> --help` is the source of truth for flags. Inputs are forgiving: VIDEO, CHANNEL, and PLAYLIST take IDs or pasted YouTube URLs, CHANNEL also takes `@handle`, and dates take `2026-01-01`, full ISO datetimes, or (for `--since`) spans like `90d` / `4w`. Options are flags (`--limit 20`); list options repeat (`--tags a --tags b`; `--empty-tags` clears). In usage lines, `[ARGS]` is the optional positional named in the parameter table. A video ID starting with `-` would read as a flag: put it after `--` or pass the URL.

## Output contract

- stdout: exactly one JSON document, null fields omitted. Pipe it into `jq`.
- Listings are `{"items": [...], "next_page_token": "..."}`. `--limit N` fetches across pages for you; pass `--page-token` to continue past it.
- Failure: stdout is empty, stderr is `{"error": {"type", "message", "details"?}}`, and the exit code names the type:

| exit | type | what to do |
|---|---|---|
| 2 | `invalid_request` / usage | fix the arguments (message says which) |
| 3 | `not_found` | the ID or handle doesn't exist or isn't visible |
| 4 | `not_authorized` | ask the user to run `ytk auth login` (interactive, opens a browser) or set `YOUTUBE_API_KEY`; also when an older login lacks analytics access |
| 5 | `quota_exceeded` | stop; quota resets at midnight Pacific Time |
| 6 | `forbidden` | YouTube refuses (comments disabled, unverified channel for thumbnails, …) |
| 7 | `network` | retry once |
| 8 | `confirmation_required` | a delete needs approval: show `details` to the user, and only after they approve run `details.rerun` |
| 9 | `protected` | the video is past the delete protection limits; stop and give the user `details.studio_url` |
| 10 | `timeout` | `video status --wait` ran out of time; processing continues, check again later |

## Deletes

`video delete`, `playlist delete` and `comment delete` never delete on the first call: they exit 8 with what would be deleted. Never add `--confirm` on your own initiative; it exists so the user's approval names the exact target. Deleting something already gone succeeds with `"already_gone": true`. Videos with more than 100 views, or public and uploaded more than 7 days ago, can't be deleted here at all (limits in `config.toml`, see README).

To make Claude Code ask before every delete, add to `.claude/settings.json`:

```json
{"permissions": {"ask": ["Bash(ytk video delete:*)", "Bash(ytk playlist delete:*)", "Bash(ytk comment delete:*)"]}}
```

## Quota

The project has 10,000 units a day. Reads cost 1 unit per request, `search` 100 per page of 50, writes 50, `video upload` 1600 (each command's `--help` states its cost). Prefer the cheap path: to find a channel's recent videos, use `channel get` → `uploads_playlist_id` → `playlist items` → `video get`, rather than `search --channel`.

## Recipes

```bash
# Titles of the 10 most-viewed videos of the last 90 days
ytk analytics --by video --since 90d --limit 10 | jq -r '.rows[].video' | xargs ytk video get | jq -r '.[].title'

# Daily views and watch time for one video
ytk analytics --by day --videos VIDEO --metrics views --metrics estimatedMinutesWatched

# Latest 10 uploads of a channel, with view counts
ytk playlist items "$(ytk channel get @mkbhd | jq -r .uploads_playlist_id)" --limit 10 \
  | jq -r '.items[].video_id' | xargs ytk video get | jq '.[] | {title, views: .stats.views}'

# Videos longer than 20 minutes from a list of URLs
ytk video get URL1 URL2 | jq '.[] | select(.duration_seconds > 1200) | .url'

# Schedule a private upload, then add it to a playlist
id=$(ytk video upload clip.mp4 --title "Launch" --publish-at 2026-07-01T15:00:00Z | jq -r .id)
ytk playlist add PLxxxx "$id"
```

Commands that change things (`video upload/update/thumbnail/delete`, `playlist create/update/thumbnail/add/remove/move/delete`, `comment post/reply/edit/delete/approve/hold/reject`, `channel update/banner`, `channel watermark set/remove`, `channel section add/update/delete`, `subscription add/remove`, `video rate`) act on the user's real account: confirm with the user before running them.
