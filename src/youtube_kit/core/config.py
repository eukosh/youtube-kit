"""Where credentials and settings come from. Environment variables override the defaults."""

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Self

from platformdirs import user_config_path

from .errors import InvalidRequest

APP_NAME = "youtube-kit"


@dataclass(frozen=True)
class Settings:
    api_key: str | None
    token_file: Path
    client_secrets_file: Path
    config_file: Path

    @classmethod
    def from_env(cls) -> Self:
        config_dir = user_config_path(APP_NAME)
        return cls(
            api_key=os.environ.get("YOUTUBE_API_KEY") or None,
            token_file=_path_env("YOUTUBE_TOKEN_FILE", config_dir / "token.json"),
            client_secrets_file=_path_env("YOUTUBE_CLIENT_SECRETS", config_dir / "client_secrets.json"),
            config_file=_path_env("YOUTUBE_CONFIG_FILE", config_dir / "config.toml"),
        )


@dataclass(frozen=True)
class DeleteProtection:
    """Videos past either limit can't be deleted through this toolkit."""

    max_views: int = 100
    max_public_age_days: int = 7

    @classmethod
    def load(cls, config_file: Path) -> Self:
        """The [delete_protection] table of the config file; defaults when absent. Bad values are an error."""
        if not config_file.exists():
            return cls()
        try:
            table = tomllib.loads(config_file.read_text()).get("delete_protection", {})
            limits = cls(**table)
        except (tomllib.TOMLDecodeError, TypeError) as e:
            raise InvalidRequest(f"Invalid {config_file}: {e}") from e
        for name, value in vars(limits).items():
            if type(value) is not int or value < 0:
                raise InvalidRequest(f"Invalid {config_file}: delete_protection.{name} must be a whole number >= 0.")
        return limits


def _path_env(name: str, default: Path) -> Path:
    value = os.environ.get(name)
    return Path(value).expanduser() if value else default
