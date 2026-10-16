"""Where credentials come from. Environment variables override the defaults."""

import os
from dataclasses import dataclass
from pathlib import Path

from platformdirs import user_config_path

APP_NAME = "youtube-kit"


@dataclass(frozen=True)
class Settings:
    api_key: str | None
    token_file: Path
    client_secrets_file: Path

    @classmethod
    def from_env(cls) -> Settings:
        config_dir = user_config_path(APP_NAME)
        return cls(
            api_key=os.environ.get("YOUTUBE_API_KEY") or None,
            token_file=_path_env("YOUTUBE_TOKEN_FILE", config_dir / "token.json"),
            client_secrets_file=_path_env("YOUTUBE_CLIENT_SECRETS", config_dir / "client_secrets.json"),
        )


def _path_env(name: str, default: Path) -> Path:
    value = os.environ.get(name)
    return Path(value).expanduser() if value else default
