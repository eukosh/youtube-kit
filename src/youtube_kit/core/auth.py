"""OAuth token lifecycle: login, load (with refresh), logout, status."""

import os
import tempfile
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

from .config import Settings
from .errors import LOGIN_HINT, NotAuthorized
from .models import AuthStatus

# Full read/write access to the authenticated user's YouTube account,
# including uploads, metadata edits, playlists, and comments.
SCOPES = ["https://www.googleapis.com/auth/youtube.force-ssl"]


def load_credentials(settings: Settings) -> Credentials:
    """Stored OAuth credentials, refreshed and re-saved if expired."""
    if not settings.token_file.exists():
        raise NotAuthorized(f"No OAuth token at {settings.token_file}. {LOGIN_HINT}")
    creds = Credentials.from_authorized_user_file(str(settings.token_file), SCOPES)
    if creds.valid:
        return creds
    if not creds.refresh_token:
        raise NotAuthorized(f"OAuth token at {settings.token_file} expired and cannot be refreshed. {LOGIN_HINT}")
    creds.refresh(Request())
    _save_token(settings.token_file, creds)
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
    flow = InstalledAppFlow.from_client_secrets_file(str(settings.client_secrets_file), SCOPES)
    # prompt=consent: without it Google may omit the refresh token when re-authorizing.
    creds = flow.run_local_server(port=0, open_browser=open_browser, prompt="consent")
    _save_token(settings.token_file, creds)
    return status(settings)


def logout(settings: Settings) -> AuthStatus:
    """Delete the stored token. Does not revoke it with Google."""
    settings.token_file.unlink(missing_ok=True)
    return status(settings)


def status(settings: Settings) -> AuthStatus:
    """What credentials are configured. Local check only; makes no network calls."""
    return AuthStatus(
        api_key_set=settings.api_key is not None,
        token_file=str(settings.token_file),
        token_present=settings.token_file.exists(),
        client_secrets_file=str(settings.client_secrets_file),
        client_secrets_present=settings.client_secrets_file.exists(),
    )


def _save_token(path: Path, creds: Credentials) -> None:
    # Atomic replace: the CLI and a running MCP server may refresh concurrently.
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".token-", suffix=".json")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(creds.to_json())
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
