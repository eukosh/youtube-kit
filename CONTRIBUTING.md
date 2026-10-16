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
## Pull request titles

Pull requests are squash-merged, and the title becomes both the commit message and the
changelog line. Titles follow [Conventional Commits](https://www.conventionalcommits.org/),
and a check enforces it:

| Type | Use for | In the changelog |
|---|---|---|
| `feat` | something users can now do | Added |
| `fix` | a bug users could hit | Fixed |
| `perf`, `revert` | other behavior changes | Changed |
| `docs`, `refactor`, `test`, `build`, `ci`, `chore` | everything else | hidden |

Write the title for users: `feat: list comments held for review`, not
`feat: add moderationStatus param`. Mark a breaking change with `!` (`feat!: rename
--since to --from`) and explain the migration in the description.

To correct the changelog entry of a pull request that is already merged, edit its
description and add the text to use instead:

```
BEGIN_COMMIT_OVERRIDE
fix: report a clear error when the token file is corrupt
END_COMMIT_OVERRIDE
```

## Releasing (maintainers)

[Release Please](https://github.com/googleapis/release-please) keeps a release pull
request open that bumps the version in `pyproject.toml` and `uv.lock` and adds the
changelog entry. Merging it tags the release, creates the GitHub release, and publishes
to PyPI.

One-time setup:

- Create a GitHub environment named `pypi`, and add the repository as a
  [trusted publisher](https://docs.pypi.org/trusted-publishers/) on PyPI (workflow
  `release.yml`, environment `pypi`).
- In Settings → Actions → General, allow GitHub Actions to create pull requests.

If publishing fails, rerun the failed jobs, or run the Release workflow by hand with the
release's tag.
