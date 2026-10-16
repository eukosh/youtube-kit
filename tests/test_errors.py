import httplib2
import pytest
from google.auth.exceptions import RefreshError

from youtube_kit.core import errors
from youtube_kit.core.ops import channels, videos

from .fakes import http_error


@pytest.mark.parametrize(
    ("status", "reason", "expected"),
    [
        (403, "quotaExceeded", errors.QuotaExceeded),
        (403, "dailyLimitExceeded", errors.QuotaExceeded),
        (401, "", errors.NotAuthorized),
        (403, "insufficientPermissions", errors.NotAuthorized),
        (403, "commentsDisabled", errors.Forbidden),
        (404, "videoNotFound", errors.NotFound),
        (400, "invalidParameter", errors.InvalidRequest),
        (500, "backendError", errors.YouTubeError),
    ],
)
def test_http_errors_map_to_domain_errors(status, reason, expected):
    error = errors.from_http_error(http_error(status, reason, "Nope."))
    assert type(error) is expected
    assert "Nope." in str(error)


def test_auth_errors_tell_the_user_how_to_fix_them():
    assert "ytk auth login" in str(errors.from_http_error(http_error(401)))


def test_exit_codes_are_distinct():
    classes = [errors.YouTubeError, *errors.YouTubeError.__subclasses__()]
    assert len({cls.exit_code for cls in classes}) == len(classes)
    assert len({cls.kind for cls in classes}) == len(classes)


def test_operations_translate_http_errors(api):
    api.public.videoCategories().list().execute.side_effect = http_error(403, "quotaExceeded")
    with pytest.raises(errors.QuotaExceeded):
        videos.list_video_categories()


def test_operations_translate_refresh_errors(api):
    api.oauth.channels().list().execute.side_effect = RefreshError("invalid_grant")
    with pytest.raises(errors.NotAuthorized, match="ytk auth login"):
        channels.get_channel()


def test_invalid_api_key_points_at_the_env_var():
    error = errors.from_http_error(
        http_error(400, "badRequest", "API key not valid. Please pass a valid API key.", details="API_KEY_INVALID")
    )
    assert isinstance(error, errors.NotAuthorized)
    assert "YOUTUBE_API_KEY" in str(error)


def test_missing_channel_is_not_an_auth_problem():
    error = errors.from_http_error(http_error(401, "youtubeSignupRequired"))
    assert isinstance(error, errors.Forbidden)
    assert "YouTube channel" in str(error)


@pytest.mark.parametrize("raised", [httplib2.ServerNotFoundError("dns"), TimeoutError("slow"), ConnectionResetError()])
def test_operations_translate_network_errors(api, raised):
    api.public.videoCategories().list().execute.side_effect = raised
    with pytest.raises(errors.NetworkError):
        videos.list_video_categories()


def test_missing_scope_points_at_login():
    error = errors.from_http_error(
        http_error(
            403, "", "Request had insufficient authentication scopes.", details="ACCESS_TOKEN_SCOPE_INSUFFICIENT"
        )
    )
    assert isinstance(error, errors.NotAuthorized)
    assert "ytk auth login" in str(error)
