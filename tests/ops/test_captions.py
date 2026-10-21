import pytest

from youtube_kit.core.errors import ConfirmationRequired, Forbidden, InvalidRequest, NotFound
from youtube_kit.core.ops import captions

from ..fakes import http_error, video_item

SRT = """1
00:00:00,080 --> 00:00:04,560
I'm a <font color="#fff">software</font> engineer

2
00:00:04,560 --> 00:00:09,920
and I build things

3
00:00:31,000 --> 00:00:33,000
Next part

4
01:02:03,000 --> 01:02:05,000
Much later
"""


def caption_resource(caption_id: str = "C1", language: str = "en", kind: str = "standard", **snippet) -> dict:
    return {
        "id": caption_id,
        "snippet": {
            "videoId": "dQw4w9WgXcQ",
            "language": language,
            "name": "",
            "trackKind": kind,
            "isDraft": False,
            "status": "serving",
            "lastUpdated": "2026-01-01T00:00:00Z",
            **snippet,
        },
    }


@pytest.fixture
def own_video(api, my_channel):
    api.oauth.videos().list().execute.return_value = {"items": [video_item()]}


def given_tracks(api, *tracks: dict) -> None:
    api.oauth.captions().list().execute.return_value = {"items": list(tracks)}


def test_list_captions_reads_any_video_through_the_login(api):
    api.oauth.captions().list().execute.return_value = {"items": [caption_resource(kind="ASR", name="")]}

    [track] = captions.list_captions("https://youtu.be/dQw4w9WgXcQ")

    assert (track.id, track.language, track.kind, track.name) == ("C1", "en", "asr", None)
    assert api.oauth.captions().list.call_args.kwargs == {"part": "snippet", "videoId": "dQw4w9WgXcQ"}


def test_transcript_text_is_timestamped_paragraphs(api, own_video):
    given_tracks(api, caption_resource())
    api.oauth.captions().download().execute.return_value = SRT.encode()

    transcript = captions.get_transcript("dQw4w9WgXcQ")

    assert transcript.text == (
        "[0:00] I'm a software engineer and I build things\n[0:31] Next part\n[1:02:03] Much later"
    )
    assert api.oauth.captions().download.call_args.kwargs == {"id": "C1", "tfmt": "srt"}


def test_transcript_file_formats_and_translation_pass_through(api, own_video):
    given_tracks(api, caption_resource())
    api.oauth.captions().download().execute.return_value = b"WEBVTT\n"

    transcript = captions.get_transcript("dQw4w9WgXcQ", format="vtt", translate_to="de")

    assert (transcript.text, transcript.translated_to) == ("WEBVTT\n", "de")
    assert api.oauth.captions().download.call_args.kwargs == {"id": "C1", "tfmt": "vtt", "tlang": "de"}


def test_transcript_prefers_the_spoken_language_and_the_authors_own_track(api, own_video):
    given_tracks(
        api,
        caption_resource("generated", "en", "asr"),
        caption_resource("translation", "de"),
        caption_resource("draft", "en-US", isDraft=True),
        caption_resource("written", "en-US"),
    )
    api.oauth.captions().download().execute.return_value = SRT.encode()

    assert captions.get_transcript("dQw4w9WgXcQ").caption_id == "written"
    assert captions.get_transcript("dQw4w9WgXcQ", language="de").caption_id == "translation"


def test_transcript_matches_language_variants_but_prefers_the_exact_one(api, own_video):
    given_tracks(api, caption_resource("us", "en-US"), caption_resource("gb", "en-GB"))
    api.oauth.captions().download().execute.return_value = SRT.encode()

    assert captions.get_transcript("dQw4w9WgXcQ", language="en-gb").caption_id == "gb"
    given_tracks(api, caption_resource("us", "en-US"))
    assert captions.get_transcript("dQw4w9WgXcQ", language="en").caption_id == "us"


def test_a_sibling_variant_is_another_language(api, own_video, tmp_path):
    # pt-PT captions must not overwrite the pt-BR track, nor a zh-Hans one stand in for zh-Hant.
    file = tmp_path / "pt.srt"
    file.write_text(SRT)
    given_tracks(api, caption_resource("brazil", "pt-BR"))
    with pytest.raises(NotFound, match="it has pt-BR"):
        captions.update_caption("dQw4w9WgXcQ", language="pt-PT", file=file)
    api.oauth.captions().update.assert_not_called()

    given_tracks(
        api, caption_resource("simplified", "zh-Hans"), caption_resource("traditional", "zh-Hant", isDraft=True)
    )
    api.oauth.captions().download().execute.return_value = SRT.encode()
    assert captions.get_transcript("dQw4w9WgXcQ", language="zh-Hant").caption_id == "traditional"


def test_transcript_prefers_youtubes_full_track_over_forced_subtitles(api, own_video):
    given_tracks(api, caption_resource("forced", kind="forced"), caption_resource("generated", kind="asr"))
    api.oauth.captions().download().execute.return_value = SRT.encode()
    assert captions.get_transcript("dQw4w9WgXcQ").caption_id == "generated"


def test_the_authors_variant_track_beats_youtubes_track_in_the_exact_language(api, own_video):
    given_tracks(api, caption_resource("generated", "en", "asr"), caption_resource("written", "en-US"))
    api.oauth.captions().download().execute.return_value = SRT.encode()
    api.oauth.captions().update().execute.return_value = caption_resource("written", "en-US")

    assert captions.get_transcript("dQw4w9WgXcQ", language="en").caption_id == "written"
    captions.update_caption("dQw4w9WgXcQ", language="en", draft=True)
    assert api.oauth.captions().update.call_args.kwargs["body"]["id"] == "written"


def test_several_written_tracks_resolve_to_the_exact_language(api, own_video):
    given_tracks(api, caption_resource("us", "en-US"), caption_resource("gb", "en-GB"))
    api.oauth.captions().update().execute.return_value = caption_resource("gb", "en-GB")
    captions.update_caption("dQw4w9WgXcQ", language="en-GB", draft=True)
    assert api.oauth.captions().update.call_args.kwargs["body"]["id"] == "gb"
    with pytest.raises(InvalidRequest, match="pass name or the exact language"):
        captions.update_caption("dQw4w9WgXcQ", language="en", draft=True)


def test_ambiguity_left_after_a_name_asks_only_for_the_exact_language(api, own_video):
    given_tracks(api, caption_resource("us", "en-US", name="A"), caption_resource("gb", "en-GB", name="A"))
    with pytest.raises(InvalidRequest, match=r"; pass the exact language\."):
        captions.delete_caption("dQw4w9WgXcQ", language="en", name="A")


def test_transcript_prefers_youtubes_published_track_over_a_draft(api, own_video):
    given_tracks(api, caption_resource("draft", isDraft=True), caption_resource("generated", kind="asr"))
    api.oauth.captions().download().execute.return_value = SRT.encode()
    assert captions.get_transcript("dQw4w9WgXcQ").caption_id == "generated"


def test_transcript_prefers_a_serving_track_over_one_youtube_failed_to_process(api, own_video):
    given_tracks(
        api,
        caption_resource("failed", status="failed"),
        caption_resource("syncing", status="syncing"),
        caption_resource("generated", kind="asr"),
    )
    api.oauth.captions().download().execute.return_value = SRT.encode()
    assert captions.get_transcript("dQw4w9WgXcQ").caption_id == "generated"

    given_tracks(api, caption_resource("failed", status="failed"), caption_resource("unknown", status=None))
    assert captions.get_transcript("dQw4w9WgXcQ").caption_id == "unknown"
    given_tracks(api, caption_resource("failed", status="failed"), caption_resource("syncing", status="syncing"))
    assert captions.get_transcript("dQw4w9WgXcQ").caption_id == "syncing"
    given_tracks(api, caption_resource("failed", status="failed"))
    assert captions.get_transcript("dQw4w9WgXcQ").caption_id == "failed"


def test_transcript_takes_the_newest_of_equal_tracks(api, own_video):
    given_tracks(
        api,
        caption_resource("old", lastUpdated="2026-01-01T00:00:00Z"),
        caption_resource("new", lastUpdated="2026-03-01T00:00:00Z"),
    )
    api.oauth.captions().download().execute.return_value = SRT.encode()
    assert captions.get_transcript("dQw4w9WgXcQ").caption_id == "new"


def test_transcript_asks_which_language_when_unclear(api, own_video):
    given_tracks(api, caption_resource("a", "de"), caption_resource("b", "fr"))
    with pytest.raises(InvalidRequest, match="de, fr"):
        captions.get_transcript("dQw4w9WgXcQ")


@pytest.mark.parametrize(("tracks", "match"), [([], "no captions"), ([caption_resource()], "it has en")])
def test_transcript_missing_language(api, own_video, tracks, match):
    given_tracks(api, *tracks)
    with pytest.raises(NotFound, match=match):
        captions.get_transcript("dQw4w9WgXcQ", language="fr" if tracks else None)


def test_transcript_of_someone_elses_video_is_refused_before_spending_quota(api, my_channel):
    api.oauth.videos().list().execute.return_value = {"items": [video_item(snippet={"channelId": "UCother"})]}
    with pytest.raises(Forbidden, match="listing them works"):
        captions.get_transcript("dQw4w9WgXcQ")
    api.oauth.captions().list.assert_not_called()


def test_upload_caption(api, tmp_path):
    file = tmp_path / "en.srt"
    file.write_text(SRT)
    api.oauth.captions().insert().execute.return_value = caption_resource(isDraft=True, name="Director")

    track = captions.upload_caption("dQw4w9WgXcQ", file, language="en", name="Director", draft=True)

    assert (track.name, track.draft) == ("Director", True)
    body = api.oauth.captions().insert.call_args.kwargs["body"]
    assert body == {"snippet": {"videoId": "dQw4w9WgXcQ", "language": "en", "name": "Director", "isDraft": True}}


def test_upload_caption_over_an_existing_track_says_what_to_do(api, tmp_path):
    file = tmp_path / "en.srt"
    file.write_text(SRT)
    api.oauth.captions().insert().execute.side_effect = http_error(409, "captionExists")
    with pytest.raises(InvalidRequest, match="Replace that track's file"):
        captions.upload_caption("dQw4w9WgXcQ", file, language="en")


def test_update_caption_keeps_the_draft_state_unless_asked(api, own_video, tmp_path):
    file = tmp_path / "en.srt"
    file.write_text(SRT)
    given_tracks(api, caption_resource("generated", "en", "asr"), caption_resource("written", isDraft=True))
    api.oauth.captions().update().execute.return_value = caption_resource("written", isDraft=True)

    captions.update_caption("dQw4w9WgXcQ", language="en", file=file)

    request = api.oauth.captions().update.call_args.kwargs
    assert request["body"] == {"id": "written", "snippet": {"isDraft": True}}
    assert "media_body" in request

    captions.update_caption("dQw4w9WgXcQ", language="en", draft=False)
    assert api.oauth.captions().update.call_args.kwargs["body"]["snippet"] == {"isDraft": False}


def test_update_caption_still_targets_a_track_youtube_failed_to_process(api, own_video):
    # A failed track is the one to replace, so changing a track ignores the status reading prefers.
    given_tracks(api, caption_resource("generated", "en", "asr"), caption_resource("broken", status="failed"))
    api.oauth.captions().update().execute.return_value = caption_resource("broken", status="failed")
    captions.update_caption("dQw4w9WgXcQ", language="en", draft=True)
    assert api.oauth.captions().update.call_args.kwargs["body"]["id"] == "broken"


def test_update_caption_checks_the_file_before_spending_quota(api, tmp_path):
    with pytest.raises(InvalidRequest, match="File not found"):
        captions.update_caption("dQw4w9WgXcQ", language="en", file=tmp_path / "missing.srt")
    api.oauth.videos().list.assert_not_called()


def test_update_caption_needs_a_change(api):
    with pytest.raises(InvalidRequest, match="file, draft"):
        captions.update_caption("dQw4w9WgXcQ", language="en")


def test_several_tracks_in_a_language_need_a_name(api, own_video):
    given_tracks(api, caption_resource("a", name="Main"), caption_resource("b", name="SDH"))
    with pytest.raises(InvalidRequest, match=r"en 'Main', en 'SDH'\); pass name\."):
        captions.update_caption("dQw4w9WgXcQ", language="en", draft=True)

    api.oauth.captions().update().execute.return_value = caption_resource("b", name="SDH")
    captions.update_caption("dQw4w9WgXcQ", language="en", name="SDH", draft=True)
    assert api.oauth.captions().update.call_args.kwargs["body"]["id"] == "b"


def test_delete_caption_is_guarded(api, own_video):
    given_tracks(api, caption_resource("C1", name="Main"))

    with pytest.raises(ConfirmationRequired) as caught:
        captions.delete_caption("dQw4w9WgXcQ", language="en")
    assert caught.value.details == {
        "kind": "caption",
        "video_id": "dQw4w9WgXcQ",
        "language": "en",
        "name": "Main",
        "track_kind": "standard",
        "confirm": "C1",
    }
    api.oauth.captions().delete.assert_not_called()

    result = captions.delete_caption("dQw4w9WgXcQ", language="en", confirm="C1")
    assert (result.id, result.already_gone) == ("C1", False)
    assert api.oauth.captions().delete.call_args.kwargs == {"id": "C1"}


@pytest.mark.parametrize(
    "remaining",
    [
        caption_resource("generated", kind="asr"),
        caption_resource("british", "en-GB"),
        caption_resource("C2", name="Other"),
    ],
)
def test_rerunning_a_confirmed_delete_succeeds_when_another_track_now_matches(api, own_video, remaining):
    # C1 is gone; whatever else matches the language must not become the target, nor the value to confirm.
    given_tracks(api, remaining)

    result = captions.delete_caption("dQw4w9WgXcQ", language="en", confirm="C1")

    assert (result.id, result.already_gone) == ("C1", True)
    api.oauth.captions().delete.assert_not_called()


def test_confirming_a_different_existing_track_is_refused(api, own_video):
    given_tracks(api, caption_resource("C1"), caption_resource("C2", "de"))
    with pytest.raises(InvalidRequest, match="confirm must be C1"):
        captions.delete_caption("dQw4w9WgXcQ", language="en", confirm="C2")
    api.oauth.captions().delete.assert_not_called()


def test_deleting_captions_of_a_deleted_video_after_confirming_succeeds(api, my_channel):
    api.oauth.videos().list().execute.return_value = {"items": []}
    assert captions.delete_caption("dQw4w9WgXcQ", language="en", confirm="C1").already_gone


def test_a_login_without_a_channel_is_not_mistaken_for_a_deleted_video(api):
    api.oauth.videos().list().execute.return_value = {"items": [video_item()]}
    api.oauth.channels().list().execute.return_value = {"items": []}
    with pytest.raises(NotFound, match="no YouTube channel"):
        captions.delete_caption("dQw4w9WgXcQ", language="en", confirm="C1")


def test_deleting_a_track_the_video_never_had_is_not_found(api, own_video):
    given_tracks(api)
    with pytest.raises(NotFound):
        captions.delete_caption("dQw4w9WgXcQ", language="en")


def test_deleting_captions_of_someone_elses_video_is_refused(api, my_channel):
    api.oauth.videos().list().execute.return_value = {"items": [video_item(snippet={"channelId": "UCother"})]}
    with pytest.raises(Forbidden, match="another channel"):
        captions.delete_caption("dQw4w9WgXcQ", language="en", confirm="C1")
    api.oauth.captions().delete.assert_not_called()
