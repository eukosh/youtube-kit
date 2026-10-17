from youtube_kit.core.config import Settings
from youtube_kit.core.ops import auth

from ..fakes import write_login


def test_a_new_user_gets_the_whole_setup():
    guide = auth.setup_guide()
    assert not guide.ready
    assert guide.steps == [*auth.CLIENT_STEPS, auth.CONNECT]


def test_with_a_client_only_the_sign_in_is_left():
    Settings.from_env().client_secrets_file.write_text("{}")
    assert auth.setup_guide().steps == [auth.CONNECT]


def test_once_a_channel_is_logged_in_nothing_is_left():
    write_login(Settings.from_env().token_dir)
    guide = auth.setup_guide()
    assert guide.ready
    assert guide.steps == []
    assert [channel.handle for channel in guide.channels] == ["@channel"]


def test_a_known_project_is_selected_in_links_and_commands():
    steps = auth.setup_guide(project="youtube-123").steps
    urls = [task.url for step in steps for task in step.tasks if task.url]
    assert urls[0] == "https://console.cloud.google.com/projectcreate"
    assert all(url.endswith("?project=youtube-123") for url in urls[1:])
    assert steps[1].gcloud.endswith("--project=youtube-123")
