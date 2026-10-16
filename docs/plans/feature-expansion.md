# Plan: feature expansion and guarded deletes

Status: in progress. Reviewed by three Fable passes (CLI ergonomics, correctness, maintainability).

Scope agreed with the owner (2026-10-16): analytics, comment management, the gap-fillers,
channel branding, subscriptions and ratings. Out of scope: captions, localizations.

Skipped on purpose:
- `videos.batchGetStats`: a strict subset of `videos.list` (duration, publish time, three counts) at the same cost.
- `comments.markAsSpam`: deprecated by YouTube; `comment reject` covers it.

## Guarded deletes

Irreversible deletes only: video, playlist, comment. Everything else (playlist item removal,
unsubscribe, clearing a rating, watermark removal, section delete) is cheap to redo and unguarded.

1. **Two-step confirm bound to the target.** A guarded op takes `confirm: str | None = None`.
   Without the right value, core raises `ConfirmationRequired` (kind `confirmation_required`, exit 8)
   whose `details` carry the plan (what will be deleted) and `confirm`, the exact value to pass back.
   A wrong value is `InvalidRequest`.
   - CLI, human (stdin and stderr are TTYs): `main()` prints the plan to stderr, asks `[y/N]`, and on
     yes re-runs the same arguments plus `--confirm <id>`. The re-run fetches and checks again.
   - CLI, agent (no TTY): exit 8 with `{"error": {"type", "message", "details"}}` on stderr.
   - MCP: `confirm` stays in the schema. The same error reaches the model as a tool error carrying the
     plan and the value. INSTRUCTIONS tell the model to show the plan and re-call only after the user
     approves. Elicitation was considered and dropped: FastMCP 4.1 refuses server-initiated
     elicitation on 2026-07-28 protocol connections, so hiding `confirm` behind it would make deletes
     impossible on modern clients.
2. **Damage limit (videos only).** Core refuses with `Protected` (kind `protected`, exit 9) when the
   video has more than `max_views` views (default 100) or is public and was uploaded more than
   `max_public_age_days` ago (default 7), or when its view count is hidden from us (fail closed).
   No flag overrides it; `details` carry the active limits and the Studio URL. YouTube only exposes
   the upload time, so an old upload made public yesterday counts as old; that errs on the safe side.
   Limits live in `<config dir>/config.toml` (or `YOUTUBE_CONFIG_FILE`):
   ```toml
   [delete_protection]
   max_views = 100
   max_public_age_days = 7
   ```
3. **Harness sign-off.** README and SKILL ship a Claude Code permission snippet
   (`"ask": ["Bash(ytk video delete:*)", "Bash(ytk playlist delete:*)", "Bash(ytk comment delete:*)"]`).
   MCP delete tools carry `destructiveHint=True`. `--confirm` stops wrong-target and blanket-yes
   mistakes; the harness rule is what puts a human in front of the plan.
4. **Idempotent.** Deleting something already gone succeeds with `already_gone: true`, including a
   404 from the delete call itself.

Order inside a delete op: resolve → fetch (missing → already_gone) → protection → confirm → delete.

Shape: `core/guard.py` with `require_confirm(target_id, confirm, plan)` and `check_protected(video, settings)`;
`YouTubeError` gains `details`. No decorator flag.

## Commands

`ytk <noun> <verb>`; `search` and `analytics` are the only top-level leaves.

```
ytk search QUERY [--since D]                      (renamed from --published-after)
ytk analytics [--video V...] [--since D] [--until D] [--by DIM] [--metrics M...] [--sort -views] [--limit N]

ytk video get|categories|upload|update|thumbnail   (existing)
ytk video delete VIDEO [--confirm ID]             guarded, damage-limited
ytk video status VIDEO [--wait] [--timeout S]     processingDetails; timeout = error type `timeout`, exit 1
ytk video rate VIDEO like|dislike|none
ytk video rating VIDEO...

ytk playlist list [CHANNEL]                       omitted = mine
ytk playlist get PLAYLIST...
ytk playlist items|create|add                     (existing)
ytk playlist update PLAYLIST [--title --description --privacy]
ytk playlist delete PLAYLIST [--confirm ID]       guarded
ytk playlist remove PLAYLIST VIDEO                every occurrence
ytk playlist move PLAYLIST VIDEO --position N     0-based; refuses if the video appears more than once
ytk playlist thumbnail PLAYLIST IMAGE

ytk comment list [VIDEO] [--status published|held|spam] [--search Q]   omitted = all on my channel
ytk comment replies COMMENT
ytk comment post VIDEO TEXT | reply COMMENT TEXT | edit COMMENT TEXT
ytk comment delete COMMENT [--confirm ID]         guarded
ytk comment approve|hold COMMENT...
ytk comment reject COMMENT... [--ban-author]

ytk channel get|mine                              (existing)
ytk channel activity [CHANNEL] [--since D]        omitted = mine
ytk channel update [--description --keywords --country --language --trailer VIDEO]
ytk channel banner IMAGE
ytk channel watermark set IMAGE [--corner] [--start] [--duration] | watermark remove
ytk channel section list [CHANNEL] | add | update ID | delete ID

ytk subscription list | add CHANNEL | remove CHANNEL
```

## Analytics

- YouTube Analytics API v2 `reports.query` with `ids=channel==MINE`, via `client.analytics()`.
- Login requests `yt-analytics-monetary.readonly` too. The stored token records the scopes Google
  actually granted (users can untick one); `load_credentials(settings, required)` checks them before
  building credentials, so an old token gets "run `ytk auth login` again to grant analytics access"
  instead of an opaque refresh failure.
- Defaults: the last 28 days ending today, metrics
  `views,estimatedMinutesWatched,averageViewDuration,likes,comments,subscribersGained,subscribersLost`,
  totals (no dimension). `--by` maps friendly names to API dimensions; metrics pass through verbatim.
  `--by video` needs a sort and at most 200 rows, so it defaults to `-views` and caps the limit.
- Output: `{"since", "until", "columns": [...], "rows": [{column: value}, ...]}`.

## Code layout

- Ops by noun in `core/ops/`; `branding.py` holds banner, watermark, sections. `_pick` moves to `_common.pick`,
  plus `_common.one(response, not_found)` for fetch-one-or-NotFound.
- `core/__init__.py` exports errors, `OPERATIONS`, `info` only; `cli.py` and tests import op modules.
- `cli.py` stays one file until hand-written code pushes it past ~300 lines.
- MCP snapshot becomes one file per tool under `tests/snapshots/mcp/`.
