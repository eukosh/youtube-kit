---
name: youtube
description: YouTube through the `ytk` CLI. Use when a task reads YouTube (search, videos, channels, playlists, comments), changes the user's own channel (uploads, metadata, playlists, comment moderation, branding, subscriptions, ratings), asks for channel analytics, or needs data behind a youtube.com or youtu.be link.
compatibility: Needs the ytk CLI (uv tool install youtube-kit) and YouTube API credentials.
---

# YouTube via `ytk`

`ytk` wraps the YouTube Data and Analytics APIs and prints JSON. If it isn't on PATH, install it with `uv tool install youtube-kit`, or run one-off commands as `uvx --from youtube-kit ytk ...`. Before the first use, see Setup.

Commands:

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

ytk comment list [VIDEO] [--status held|spam] [--search Q]
ytk comment replies COMMENT        ytk comment post VIDEO TEXT      ytk comment reply COMMENT TEXT
ytk comment edit COMMENT TEXT      ytk comment delete COMMENT
ytk comment approve|hold COMMENT...                                 ytk comment reject COMMENT... [--ban-author]

ytk channel get [CHANNEL]          ytk channel activity [CHANNEL]   ytk channel mine
ytk channel update [--description] [--keywords K]... [--country] [--language] [--trailer VIDEO]
ytk channel banner IMAGE           ytk channel watermark set IMAGE  ytk channel watermark remove
ytk channel section list [CHANNEL] | add KIND | update SECTION | delete SECTION

ytk subscription list              ytk subscription add CHANNEL     ytk subscription remove CHANNEL
ytk auth status | guide | login | switch CHANNEL | logout [CHANNEL]
ytk upgrade
```

An omitted CHANNEL means the user's own channel; an omitted VIDEO in `comment list` means all of the user's videos. COMMENT takes a comment ID or its link (a video URL with `&lc=`).

`ytk <command> --help` is the source of truth for flags. Inputs are forgiving: VIDEO, CHANNEL, and PLAYLIST take IDs or pasted YouTube URLs, CHANNEL also takes `@handle`, and dates take `2026-01-01`, full ISO datetimes, or (for `--since`) spans like `90d` / `4w`. List options repeat (`--tags a --tags b`; `--empty-tags` clears). In usage lines, `[ARGS]` is the optional positional named in the parameter table. A video ID starting with `-` would read as a flag: put it after `--` or pass the URL.

## Output contract

- stdout: exactly one JSON document, null fields omitted.
- Listings are `{"items": [...], "next_page_token": "..."}`. `--limit N` fetches across pages for you; pass `--page-token` to continue past it.
- Progress: `video upload` and `video status --wait` print `{"progress": {"done", "total", "percent"}}` lines to stderr as they go, about every 10% (`--wait` only when YouTube reports how far processing is).
- Updates: when a newer release is out, stderr starts with `{"update": {"current", "latest", "command", "changelog"}}`, at most once a day per version, and `usage` errors carry it in `details.update` (the command may be newer than this ytk). Finish the task, then tell the user; run `command` if they ask.
- Failure: stdout is empty, the last stderr line is `{"error": {"type", "message", "details"?}}`, and the exit code names the type:

| exit | type | what to do |
|---|---|---|
| 1 | `error` | unexpected failure, or the user declined a delete; report the message |
| 2 | `invalid_request` / `usage` | fix the arguments (message says which) |
| 3 | `not_found` | the ID or handle doesn't exist or isn't visible |
| 4 | `not_authorized` | not set up or not logged in: see Setup. For public data an exported `YOUTUBE_API_KEY` also works. Also when an older login lacks analytics access, when `--my-channel` names a channel that isn't logged in, and when several channels are logged in with no default (see Several channels) |
| 5 | `quota_exceeded` | stop; quota resets at midnight Pacific Time |
| 6 | `forbidden` | YouTube refuses (comments disabled, unverified channel for thumbnails, …) |
| 7 | `network` | retry once |
| 8 | `confirmation_required` | a delete needs approval: see Changing the user's channel |
| 9 | `protected` | the video is past the delete protection limits; stop and give the user `details.studio_url` |
| 10 | `timeout` | `video status --wait` ran out of time; processing continues, check again later |

## Setup

`ytk auth guide` says what is left: `ready`, the logged-in `channels`, and the remaining `steps`, each with `tasks` (what to click, the `url`, the `values` to enter). Two ways through it:

- The user runs `ytk auth login` in their own terminal. It walks them through every step and Google's sign-in.
- You guide them in the chat, one step at a time. If `gcloud` is installed and `gcloud auth list` shows the account the user wants, offer to run the steps that have a `gcloud` command: pick a unique project ID (6–30 characters, e.g. `youtube-` plus random digits); a brand-new Google account must open console.cloud.google.com once to accept the terms first. Then `ytk auth guide --project ID` gives links with that project selected. The rest (consent screen, Branding, publishing, the OAuth client) only exists in the browser. When they have the JSON, pass on the tips of the last step (Google's "hasn't verified this app" warning is expected), then run `ytk auth login --client-secrets FILE`: it opens Google's sign-in in their browser and waits until they pick the channel.

## Several channels

The user can be logged in to several channels, one `ytk auth login` each. `ytk channel mine` lists them (no API call) and marks the `default` one. Every command that reaches YouTube works on the default channel unless `--my-channel CHANNEL` (UC… ID, @handle or exact title of a logged-in channel) names another; `YOUTUBE_CHANNEL` sets it for a whole shell. `ytk auth switch CHANNEL` changes the stored default for every later command and for the MCP server, so don't run it on the user's behalf; pass `--my-channel` instead.

When the user has several channels and the task touches "my channel" without saying which, ask before writing anything. Read-only commands on someone else's content (`video get`, `search`, `channel get @someone`) don't care which of the user's channels you use. All logged-in channels share the project's daily quota. Handles are the ones stored at login; if one doesn't match after a rename, use the channel's `id` from `ytk channel mine`.

## Changing the user's channel

Commands that change things (`video upload/update/thumbnail/rate/delete`, `playlist create/update/thumbnail/add/remove/move/delete`, `comment post/reply/edit/delete/approve/hold/reject`, `channel update/banner`, `channel watermark set/remove`, `channel section add/update/delete`, `subscription add/remove`) act on the user's real, public channel. Run one when the user asked for that change. When you picked the target or wrote the content yourself (a title, a reply, which comments to reject), show it and get a yes first.

After `video upload` or `video update`, give the user both `url` and `studio_url` (YouTube Studio, for what the API can't do: end screens, cards, subtitles). `studio_url` is set only for videos on channels the user is logged in to here. YouTube keeps processing an upload after `video upload` returns: `video status VIDEO --wait` waits for it, and `video get` shows `upload_status` and `rejection_reason` if YouTube refused the video. YouTube may store tags in its own order.

What `video upload` sets when a flag is left out: category and both languages are copied from the channel's most recent public upload (`--category-id`, `--language`, `--audio-language` override), and YouTube's paid promotion and AI use disclosures are answered no (`--paid-promotion`, `--ai-content`; `--help` says what counts). `video update` changes either answer only when its flag is passed (`--no-ai-content` sets it back to no). `playlist create` copies the title and description language the same way (`--language` overrides). The user's own instructions, such as per-channel categories or languages, take precedence over these defaults.

`video delete`, `playlist delete` and `comment delete` exit 8 on the first call with what would be deleted. `--confirm` carries the user's yes for that exact target: show `details` to the user, and after they approve run `details.rerun`. Deleting something already gone succeeds with `"already_gone": true`. Videos with more than 100 views, or public and uploaded more than 7 days ago, can't be deleted here at all (limits in `config.toml`; `ytk auth status` shows its path). Other removals (`playlist remove`, `channel section delete`, `subscription remove`, `video rate none`, `channel watermark remove`) are easy to redo and run without confirmation.

## Quota

The project has 10,000 units a day. Reads cost 1 unit per request, writes 50 (each command's `--help` states its cost). `search` and `video upload` have their own limits of 100 calls a day: one per page of 50 search results, one per upload. Resolving an `@handle` or channel URL costs 1 more unit, as does acting on "your channel" by default (e.g. `comment list` without a video). A UC… ID needs no lookup. `analytics` uses the separate Analytics API quota. Prefer the cheap path: to find a channel's recent videos, use `channel get` → `uploads_playlist_id` → `playlist items` → `video get`, rather than `search --channel`.

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
