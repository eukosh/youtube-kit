"""OAuth logins, one per channel: login, choose which to work on, load (with refresh), logout, status.

Google binds a token to the single channel picked on the consent screen, so each channel
(brand accounts included) gets its own login, stored as <token_dir>/<channel ID>.json.
"""

import json
import os
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from . import parse
from .config import Settings
from .errors import LOGIN_HINT, NETWORK_ERRORS, InvalidRequest, NetworkError, NotAuthorized, from_http_error
from .models import AuthStatus, MyChannel

# Full read/write access to the user's YouTube account: uploads, edits, playlists, comments.
YOUTUBE = "https://www.googleapis.com/auth/youtube.force-ssl"
# YouTube Analytics reports, revenue included.
ANALYTICS = "https://www.googleapis.com/auth/yt-analytics-monetary.readonly"
SCOPES = [YOUTUBE, ANALYTICS]

_DEFAULT_FILE = "default"  # in token_dir; holds the default channel's ID

# A ContextVar rather than a parameter, so core code below the operation needn't pass it along.
_my_channel: ContextVar[str | None] = ContextVar("youtube_kit_my_channel", default=None)


@contextmanager
def working_on(channel: str | None) -> Iterator[None]:
    """Work on this logged-in channel (UC… ID, @handle, or URL) inside the block. None changes nothing."""
    if channel is None:
        yield
        return
    token = _my_channel.set(channel)
    try:
        yield
    finally:
        _my_channel.reset(token)


def token_file(settings: Settings, *, any_login: bool = False) -> Path:
    """Token of the channel to work on: the one chosen with `working_on`, else the default channel.

    With `any_login`, falls back to some login when there's no default, for reads where any will do.
    """
    logins = _logins(settings)
    if not logins:
        raise NotAuthorized(f"Not logged in. {LOGIN_HINT}")
    ref = _my_channel.get()
    channel_id = _match(ref, logins) if ref is not None else _default_id(settings, logins)
    if channel_id is None and any_login:
        channel_id = next(iter(logins))
    if channel_id is None:
        raise NotAuthorized(
            f"Logged in to several channels and none is the default: {_describe(logins)}. "
            "Name the channel to work on, or set a default with `ytk auth switch CHANNEL`."
        )
    return settings.token_dir / f"{channel_id}.json"


def has_login(settings: Settings) -> bool:
    return bool(_logins(settings))


def load_credentials(path: Path, scope: str = YOUTUBE) -> Credentials:
    """Credentials stored at `path`, refreshed and re-saved if expired. They must include `scope`."""
    try:
        info = json.loads(path.read_text())
    except FileNotFoundError:
        raise NotAuthorized(f"No OAuth token at {path}. {LOGIN_HINT}") from None
    except ValueError as e:
        raise NotAuthorized(f"OAuth token at {path} is unreadable ({e}). {LOGIN_HINT}") from e
    # The token lists the scopes Google granted; the user may have unticked some, or logged in before
    # a scope was added. A refresh can't add scopes; the only fix is logging in again. Tokens from
    # elsewhere may not list scopes at all; Google then answers for itself.
    if "scopes" in info and scope not in info["scopes"]:
        access = "analytics" if scope == ANALYTICS else "YouTube"
        raise NotAuthorized(f"Your login doesn't grant {access} access. {LOGIN_HINT} Allow every requested permission.")
    try:
        creds = Credentials.from_authorized_user_info(info)
    except ValueError as e:
        raise NotAuthorized(f"OAuth token at {path} is incomplete ({e}). {LOGIN_HINT}") from e
    if creds.valid:
        return creds
    if not creds.refresh_token:
        raise NotAuthorized(f"OAuth token at {path} expired and cannot be refreshed. {LOGIN_HINT}")
    creds.refresh(Request())
    _write_atomic(path, json.dumps({**info, **json.loads(creds.to_json())}))
    return creds


def login(settings: Settings, *, open_browser: bool = True) -> AuthStatus:
    """Run the installed-app OAuth flow and store the token under the channel picked. Prints the auth URL to stdout.

    The first channel logged in becomes the default.
    """
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
    info["scopes"] = creds.granted_scopes or SCOPES  # Google omits the list when all were granted
    info["channel"] = _identify(creds)
    channel_id = info["channel"]["id"]
    _write_atomic(settings.token_dir / f"{channel_id}.json", json.dumps(info))
    if _stored_default(settings) not in _logins(settings):
        _save_default(settings, channel_id)
    return status(settings)


def switch(settings: Settings, channel: str) -> AuthStatus:
    """Make a logged-in channel the default. Refused while YOUTUBE_CHANNEL overrides the default."""
    if settings.channel is not None:
        raise InvalidRequest(f"YOUTUBE_CHANNEL={settings.channel} overrides the default. Unset it to switch.")
    _save_default(settings, _match(channel, _logins(settings)))
    return status(settings)


def logout(settings: Settings, channel: str | None = None) -> AuthStatus:
    """Delete a channel's stored token, the default channel's when None. Does not revoke it with Google."""
    logins = _logins(settings)
    if not logins and channel is None:
        return status(settings)
    channel_id = _match(channel, logins) if channel is not None else _default_id(settings, logins)
    if channel_id is None:
        raise InvalidRequest(f"Several channels are logged in and none is the default; name one: {_describe(logins)}.")
    (settings.token_dir / f"{channel_id}.json").unlink(missing_ok=True)
    if _stored_default(settings) == channel_id:
        (settings.token_dir / _DEFAULT_FILE).unlink(missing_ok=True)
    return status(settings)


def my_channels(settings: Settings) -> list[MyChannel]:
    """Channels with a stored login, read locally. Makes no network calls."""
    logins = _logins(settings)
    try:
        default = _default_id(settings, logins)
    except NotAuthorized:  # YOUTUBE_CHANNEL names a channel that isn't logged in
        default = None
    channels = []
    for channel_id, info in logins.items():
        channel = info.get("channel") or {}
        handle = channel.get("handle")
        channels.append(
            MyChannel(
                id=channel_id,
                title=channel.get("title", channel_id),
                handle=handle,
                url=f"https://www.youtube.com/{handle}" if handle else f"https://www.youtube.com/channel/{channel_id}",
                default=channel_id == default,
                analytics=ANALYTICS in info.get("scopes", SCOPES if info else []),
            )
        )
    return channels


def status(settings: Settings) -> AuthStatus:
    """What credentials are configured. Local check only; makes no network calls."""
    return AuthStatus(
        api_key_set=settings.api_key is not None,
        channels=my_channels(settings),
        token_dir=str(settings.token_dir),
        client_secrets_file=str(settings.client_secrets_file),
        client_secrets_present=settings.client_secrets_file.exists(),
        config_file=str(settings.config_file),
    )


def _logins(settings: Settings) -> dict[str, dict]:
    """Stored tokens by channel ID. An unreadable one maps to {} so it still shows up, and fails when used."""
    logins = {}
    for path in sorted(settings.token_dir.glob("UC*.json")):
        try:
            info = json.loads(path.read_text())
        except (OSError, ValueError):
            info = {}
        logins[path.stem] = info if isinstance(info, dict) else {}
    return logins


def _match(ref: str, logins: dict[str, dict]) -> str:
    """ID of the logged-in channel that `ref` names."""
    key = parse.channel_ref(ref)
    for channel_id, info in logins.items():
        handle = (info.get("channel") or {}).get("handle") or ""
        if (key.by == "id" and key.value == channel_id) or (key.by == "handle" and key.value.lower() == handle.lower()):
            return channel_id
    logged_in = _describe(logins) if logins else "none"
    raise NotAuthorized(f"Not logged in to {ref} (logged in: {logged_in}). {LOGIN_HINT} Pick that channel at Google.")


def _default_id(settings: Settings, logins: dict[str, dict]) -> str | None:
    """The channel to work on when none is named: YOUTUBE_CHANNEL, else the stored default, else the only login."""
    if settings.channel is not None:
        try:
            return _match(settings.channel, logins)
        except (NotAuthorized, InvalidRequest):
            logged_in = _describe(logins) if logins else "none"
            raise NotAuthorized(
                f"YOUTUBE_CHANNEL={settings.channel} isn't one of your logged-in channels (logged in: {logged_in}). "
                "Unset it, or log in to that channel."
            ) from None
    if (stored := _stored_default(settings)) in logins:
        return stored
    return next(iter(logins)) if len(logins) == 1 else None


def _stored_default(settings: Settings) -> str | None:
    try:
        return (settings.token_dir / _DEFAULT_FILE).read_text().strip()
    except OSError:
        return None


def _save_default(settings: Settings, channel_id: str) -> None:
    _write_atomic(settings.token_dir / _DEFAULT_FILE, channel_id + "\n")


def _describe(logins: dict[str, dict]) -> str:
    def name(channel_id: str, info: dict) -> str:
        channel = info.get("channel") or {}
        return f"{channel['title']} ({channel.get('handle') or channel_id})" if "title" in channel else channel_id

    return ", ".join(name(channel_id, info) for channel_id, info in logins.items())


def _identify(creds: Credentials) -> dict:
    """ID, title, and handle of the channel a fresh token works on."""
    youtube = build("youtube", "v3", credentials=creds, cache_discovery=False, static_discovery=True)
    try:
        response = youtube.channels().list(part="snippet", mine=True).execute()
    except HttpError as e:
        raise from_http_error(e) from e
    except NETWORK_ERRORS as e:
        raise NetworkError(f"Could not reach YouTube ({type(e).__name__}: {e}). Retry later.") from e
    if not response.get("items"):
        raise NotAuthorized(f"The account you picked has no YouTube channel. {LOGIN_HINT} Pick a channel at Google.")
    item = response["items"][0]
    return {"id": item["id"], "title": item["snippet"]["title"], "handle": item["snippet"].get("customUrl")}


def _write_atomic(path: Path, text: str) -> None:
    # Atomic replace: a running MCP server may read or refresh while the CLI writes.
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".token-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
