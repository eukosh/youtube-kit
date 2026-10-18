# Changelog

Notable changes in each release. Entries come from the
[Conventional Commits](https://www.conventionalcommits.org/) titles of merged pull requests.
The project uses [Semantic Versioning](https://semver.org/); until 1.0, minor versions may
change command names, flags and JSON fields.

## [0.6.0](https://github.com/eukosh/youtube-kit/compare/v0.5.0...v0.6.0) (2026-10-18)


### Added

* list the MCP server in the official MCP Registry, runnable as `uvx youtube-kit mcp` ([#11](https://github.com/eukosh/youtube-kit/issues/11)) ([43c4bb1](https://github.com/eukosh/youtube-kit/commit/43c4bb10b333f6e09d13cb28573841382b619b77))
* video get shows rejected uploads, and uploads report progress to agents ([#9](https://github.com/eukosh/youtube-kit/issues/9)) ([f80072a](https://github.com/eukosh/youtube-kit/commit/f80072afdbe64f7b80663d99dcb935a5319eef7f))


### Fixed

* playlist thumbnails, watermarks, home sections, channel titles, and partial video updates ([#8](https://github.com/eukosh/youtube-kit/issues/8)) ([ca65bcf](https://github.com/eukosh/youtube-kit/commit/ca65bcfdca8eca0270fdeafb394d4ea7b4fd3318))

## [0.5.0](https://github.com/eukosh/youtube-kit/compare/v0.4.0...v0.5.0) (2026-10-17)


### Added

* answer YouTube's paid promotion and AI use questions on upload and update ([0ae14b7](https://github.com/eukosh/youtube-kit/commit/0ae14b7a8a841c49efbb65697bb79a1d0e24df7a))
* link your own videos to YouTube Studio ([#5](https://github.com/eukosh/youtube-kit/issues/5)) ([363636e](https://github.com/eukosh/youtube-kit/commit/363636ef525c1129af442adf923a5a76e8108097))
* set a playlist's language, copied from your uploads when creating one ([0ae14b7](https://github.com/eukosh/youtube-kit/commit/0ae14b7a8a841c49efbb65697bb79a1d0e24df7a))
* uploads copy category and languages from your recent public uploads, with --language and --audio-language to override ([0ae14b7](https://github.com/eukosh/youtube-kit/commit/0ae14b7a8a841c49efbb65697bb79a1d0e24df7a))

## [0.4.0](https://github.com/eukosh/youtube-kit/compare/v0.3.0...v0.4.0) (2026-10-17)


### Added

* `ytk auth guide` and the `setup_guide` MCP tool tell agents what is left to set up ([870ac7a](https://github.com/eukosh/youtube-kit/commit/870ac7ae2d6dca9bb3a7054a9f148c9907f50e8d))
* colored JSON and readable errors at a terminal ([870ac7a](https://github.com/eukosh/youtube-kit/commit/870ac7ae2d6dca9bb3a7054a9f148c9907f50e8d))
* guided Google Cloud setup in `ytk auth login` ([870ac7a](https://github.com/eukosh/youtube-kit/commit/870ac7ae2d6dca9bb3a7054a9f148c9907f50e8d))
* install the skill as a Claude Code or Codex plugin ([870ac7a](https://github.com/eukosh/youtube-kit/commit/870ac7ae2d6dca9bb3a7054a9f148c9907f50e8d))


### Fixed

* every `ytk analytics --by` breakdown works, and `--limit` returns the top rows ([870ac7a](https://github.com/eukosh/youtube-kit/commit/870ac7ae2d6dca9bb3a7054a9f148c9907f50e8d))

## [0.3.0](https://github.com/eukosh/youtube-kit/compare/v0.2.0...v0.3.0) (2026-10-17)


### Added

* log in to several channels and choose one per command ([#1](https://github.com/eukosh/youtube-kit/issues/1)) ([942059e](https://github.com/eukosh/youtube-kit/commit/942059ee5664ff60ffea6580e1dadfe72f166600))

## [0.2.0](https://github.com/eukosh/youtube-kit/releases/tag/v0.2.0) (2026-10-17)

First public release. (0.1.0 was an unpublished, MCP-only predecessor.)

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
