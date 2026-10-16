# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/). Until 1.0, minor versions may change
command names, flags and JSON fields.

## [Unreleased]

## [0.2.0]

First public release.

### Added

- `ytk` CLI and `ytk mcp` server over one shared core of typed operations.
- Search, videos (get, upload, update, thumbnail, processing status, rate), playlists
  (list, items, create, update, thumbnail, add, remove, move), channels and activity.
- Comment management: list including held and likely-spam comments, replies, post,
  reply, edit, approve, hold, reject and ban.
- Channel branding: about info, banner, watermark and home page sections.
- Subscriptions and video ratings.
- YouTube Analytics reports: totals or breakdowns by day, month, video, country,
  device, traffic source and more.
- Guarded deletes for videos, playlists and comments: target-bound confirmation,
  configurable damage limits for videos, ownership checks, idempotency.
- JSON output on stdout, structured errors on stderr and distinct exit codes.

[Unreleased]: https://github.com/eukosh/youtube-kit/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/eukosh/youtube-kit/releases/tag/v0.2.0
