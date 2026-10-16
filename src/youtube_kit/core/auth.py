"""OAuth token lifecycle: login, load (with refresh), logout, status."""

import json
import os
import tempfile
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

from .config import Settings
from .errors import LOGIN_HINT, NotAuthorized
from .models import AuthStatus

# Full read/write access to the user's YouTube account: uploads, edits, playlists, comments.
YOUTUBE = "https://www.googleapis.com/auth/youtube.force-ssl"
# YouTube Analytics reports, revenue included.
ANALYTICS = "https://www.googleapis.com/auth/yt-analytics-monetary.readonly"
SCOPES = [YOUTUBE, ANALYTICS]


def load_credentials(settings: Settings, scope: str = YOUTUBE) -> Credentials:
    """Stored OAuth credentials, refreshed and re-saved if expired. They must include `scope`."""
    if not settings.token_file.exists():
        raise NotAuthorized(f"No OAuth token at {settings.token_file}. {LOGIN_HINT}")
    info = json.loads(settings.token_file.read_text())
    # The token lists the scopes Google granted; the user may have unticked some, or logged in before
    # a scope was added. Refreshing asks for exactly these, so a missing one can't be refreshed into.
    if scope not in info.get("scopes", []):
        access = "analytics" if scope == ANALYTICS else "YouTube"
        raise NotAuthorized(f"Your login doesn't grant {access} access. {LOGIN_HINT} Allow every requested permission.")
    creds = Credentials.from_authorized_user_info(info)
    if creds.valid:
        return creds
    if not creds.refresh_token:
        raise NotAuthorized(f"OAuth token at {settings.token_file} expired and cannot be refreshed. {LOGIN_HINT}")
    creds.refresh(Request())
    _save_token(settings.token_file, json.loads(creds.to_json()))
    return creds


def login(settings: Settings, *, open_browser: bool = True) -> AuthStatus:
    """Run the installed-app OAuth flow and store the token. Prints the auth URL to stdout."""
    if not settings.client_secrets_file.exists():
        raise NotAuthorized(
            f"OAuth client secrets not found at {settings.client_secrets_file}. "
            "In Google Cloud Console, enable YouTube Data API v3, create an OAuth client ID "
            "of type 'Desktop app', and save its JSON to that path "
            "(or point YOUTUBE_CLIENT_SECRETS at it)."
        )
    # Google lets users untick scopes; without this, oauthlib raises instead of returning what was granted.
    os.environ.setdefault("OAUTHLIB_RELAX_TOKEN_SCOPE", "1")
    flow = InstalledAppFlow.from_client_secrets_file(str(settings.client_secrets_file), SCOPES)
    # prompt=consent: without it Google may omit the refresh token when re-authorizing.
    creds = flow.run_local_server(port=0, open_browser=open_browser, prompt="consent")
    info = json.loads(creds.to_json())
    info["scopes"] = creds.granted_scopes or SCOPES
    _save_token(settings.token_file, info)
    return status(settings)


def logout(settings: Settings) -> AuthStatus:
    """Delete the stored token. Does not revoke it with Google."""
    settings.token_file.unlink(missing_ok=True)
    return status(settings)


def status(settings: Settings) -> AuthStatus:
    """What credentials are configured. Local check only; makes no network calls."""
    token_present = settings.token_file.exists()
    return AuthStatus(
        api_key_set=settings.api_key is not None,
        token_file=str(settings.token_file),
        token_present=token_present,
        granted_scopes=json.loads(settings.token_file.read_text()).get("scopes") if token_present else None,
        client_secrets_file=str(settings.client_secrets_file),
        client_secrets_present=settings.client_secrets_file.exists(),
    )


def _save_token(path: Path, info: dict) -> None:
    # Atomic replace: the CLI and a running MCP server may refresh concurrently.
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".token-", suffix=".json")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(info, f)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
