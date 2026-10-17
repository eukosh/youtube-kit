# Privacy

`ytk` (youtube-kit) runs on your own computer, through an OAuth client in your own Google Cloud project. Nobody else operates a server for it.

- **What it stores:** your OAuth client JSON, one login token per YouTube channel you connect, and `config.toml`. All of them stay in your user config directory (`ytk auth status` shows where). Nothing leaves your machine except calls to Google's APIs.
- **Who it talks to:** Google only (`accounts.google.com`, `oauth2.googleapis.com` and the YouTube Data and Analytics APIs), to do what you ask: read your channel, upload, edit, moderate and report.
- **What it collects:** nothing. There is no telemetry, analytics or crash reporting.
- **How to remove access:** `ytk auth logout CHANNEL` deletes a stored token. To revoke access at Google as well, remove the app at <https://myaccount.google.com/permissions>.

Use of YouTube data also falls under the [YouTube Terms of Service](https://www.youtube.com/t/terms) and the [Google Privacy Policy](https://policies.google.com/privacy).
