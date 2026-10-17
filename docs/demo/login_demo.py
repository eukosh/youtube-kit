"""The real `ytk auth login` wizard with the browser and Google's sign-in stubbed, for recording login.gif.

Run by shell.sh as `ytk` inside the recorded terminal. Everything lands in a throwaway $DEMO_HOME.
"""

import json
import os
import sys
import time
from pathlib import Path

home = Path(os.environ["DEMO_HOME"])
config = home / "Library/Application Support/youtube-kit"
os.environ["YOUTUBE_CLIENT_SECRETS"] = str(config / "client_secrets.json")
os.environ["YOUTUBE_TOKEN_DIR"] = str(config / "tokens")
os.environ["YOUTUBE_CONFIG_FILE"] = str(config / "config.toml")
Path.home = lambda: home

# Imported only now: the settings above must be in place first.
from youtube_kit import guide
from youtube_kit.cli import main
from youtube_kit.core import auth
from youtube_kit.core.models import MyChannel

CLIENT = {"installed": {"client_id": "418204-k2v9.apps.googleusercontent.com", "client_secret": "demo"}}
find_download = auth.downloaded_client_secrets


def downloaded(downloads=None):
    # The JSON "arrives" in Downloads during the last step, as it does for a real user.
    (home / "Downloads").mkdir(parents=True, exist_ok=True)
    (home / "Downloads/client_secret_418204-k2v9.apps.googleusercontent.com.json").write_text(json.dumps(CLIENT))
    return find_download(downloads)


def authorize(settings, *, open_browser=True):
    time.sleep(1.5)  # the user picks the account and channel at Google


guide.webbrowser.open = lambda url: None
auth.downloaded_client_secrets = downloaded
auth.authorize = authorize
auth.connect = lambda settings, creds: MyChannel(
    id="UCW702rk-td8oLbge4xImmRA",
    title="Just a Dev",
    handle="@justadevshow",
    url="https://www.youtube.com/@justadevshow",
    default=True,
    analytics=True,
)
auth.status = lambda settings: None  # end on the wizard rather than the status JSON

sys.exit(main(sys.argv[1:]))
