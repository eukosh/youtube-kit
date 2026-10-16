# Security policy

## Reporting a vulnerability

Please report security issues privately through
[GitHub's private vulnerability reporting](https://github.com/eukosh/youtube-kit/security/advisories/new),
not in a public issue. You can expect a first reply within a week.

Only the latest release gets security fixes.

## What youtube-kit stores

`ytk auth login` stores an OAuth token that can act on your YouTube account. It is
written to the user config directory with owner-only permissions (`0600`) and is
shared by the CLI and the MCP server. Treat it like a password: don't commit it,
and run `ytk auth logout` to delete it. You can also revoke access at any time in
your [Google account settings](https://myaccount.google.com/permissions).

The delete guards protect against mistakes, not against a malicious program that
holds the token. Anything with the token can call the YouTube API directly.
