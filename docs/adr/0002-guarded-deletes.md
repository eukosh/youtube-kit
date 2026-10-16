# 0002. Guarded deletes

Date: 2026-10-16. Status: accepted.

## Context

Most calls come from agents, not people. An agent can delete the wrong upload, or an injected instruction can ask it to delete something valuable. YouTube has no trash: a deleted video loses its views, comments and URL for good. The owner still wants agents to clean up their own fresh mistakes, such as a bad upload from a minute ago.

High-stakes CLIs layer several defences. Heroku's `--confirm <app>`, GitHub's "type the repository name", Terraform's plan-then-apply and kubectl's dry runs all show the target and make approval name it. The agent harness can add its own sign-off on top.

## Decision

Irreversible deletes (video, playlist, comment) are guarded in core, so both adapters inherit the same rules:

1. **Confirmation bound to the target.** A guarded op takes `confirm`. Without it, core raises `ConfirmationRequired` (exit 8) carrying the plan and the exact value to pass back. A wrong value is invalid input. The CLI asks a human at a terminal (`[y/N]`) and reruns with `--confirm <id>`; an agent gets exit 8 with `details.rerun`. The MCP tool fails the same way, and the server instructions tell the model to get the user's approval first.
2. **Damage limit for videos.** A video with more than 100 views, or public and uploaded more than 7 days ago, is refused (`Protected`, exit 9), and no flag overrides it. The limits live in `config.toml`. When the view count is hidden or the upload time unknown, the guard fails closed.
3. **Ownership first.** Deleting another channel's video, playlist or comment is refused before anything is described or confirmed.
4. **Idempotent.** A target that is already gone, before or during the call, is a success with `already_gone: true`.
5. **Harness sign-off.** The skill ships Claude Code `ask` rules for the three delete commands, and MCP delete tools carry `destructiveHint`.

Reversible or cheap-to-redo changes stay unguarded: removing a playlist item, unsubscribing, clearing a rating, removing a watermark or a home-page section, and moderating comments.

## Alternatives rejected

- **A "hide" command (set the video private) instead of deleting.** The owner rejected it.
- **MCP elicitation for the confirmation, with `confirm` hidden from the schema.** FastMCP 4.1 refuses server-initiated elicitation on 2026-07-28 protocol connections, so modern clients could never delete.
- **`--yes`.** Agents learn to append it by reflex. `--confirm <id>` can't be carried over to a different target.
- **A decorator flag (`@operation(guarded=True)`).** Each delete has to fetch its own target anyway. Two plain helper calls (`guard.check_protected`, `guard.require_confirm`) are shorter and easier to read.

## Consequences

- A delete costs a few extra quota units for the lookup and the ownership check.
- This stops mistakes, not a determined attacker: anything holding the OAuth token can call the API directly. The README says so.
