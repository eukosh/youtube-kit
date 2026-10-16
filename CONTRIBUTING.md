# Contributing

Thanks for helping. Bug reports, ideas and pull requests are all welcome. For a
larger change, open an issue first so we can agree on the shape.

## Setup

You need [uv](https://docs.astral.sh/uv/).

```sh
git clone https://github.com/eukosh/youtube-kit
cd youtube-kit
uv run ytk --help
```

## Checks

CI runs these on every pull request. Run them before you push:

```sh
uv run pytest                                      # offline; the API is faked
uv run ruff check --fix . && uv run ruff format .  # lint and format
```

`LIVE_YOUTUBE_API_KEY=... uv run pytest -m live` makes a few real, read-only API calls.

## How the code fits together

[ADR 0001](docs/adr/0001-shared-core-cli-and-mcp.md) explains the layout, and
[AGENTS.md](AGENTS.md) has the working rules. In short:

- An operation is one `@operation` function in `src/youtube_kit/core/ops/<noun>.py`.
  Its docstring is the help text on both the CLI and MCP, so write it for both.
- Give it a `ytk <noun> <verb>` command in `cli.py`; the MCP server picks it up
  automatically. Its tests go in `tests/ops/test_<noun>.py`.
- Changing an operation's signature, docstring or model changes the MCP tools.
  Regenerate the snapshots with `UPDATE_SNAPSHOTS=1 uv run pytest tests/test_mcp.py`
  and include the diff in your pull request.
- Irreversible deletes must go through `core/guard.py`; see
  [ADR 0002](docs/adr/0002-guarded-deletes.md).
- Note user-facing changes under `Unreleased` in [CHANGELOG.md](CHANGELOG.md).

## Releasing (maintainers)

One-time setup: create a GitHub environment named `pypi`, and add the repository as a
[trusted publisher](https://docs.pypi.org/trusted-publishers/) on PyPI (workflow
`release.yml`, environment `pypi`).

1. `uv version --bump minor` (or `patch`). In CHANGELOG.md, move the `Unreleased` notes
   under the new version with today's date, and update the compare links at the bottom.
2. Commit and push to `main`, then tag: `git tag v$(uv version --short) && git push origin --tags`.
3. The release workflow checks the tag against the version and the changelog, runs the
   tests, builds, publishes to PyPI and creates the GitHub release from the changelog notes.
