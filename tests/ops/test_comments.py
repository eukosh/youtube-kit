import pytest

from youtube_kit.core.errors import Forbidden, InvalidRequest
from youtube_kit.core.ops import comments

from ..fakes import CHANNEL_ID, comment_resource, thread_resource


def test_list_comments_on_a_video_uses_public_data(api):
    api.public.commentThreads().list().execute.return_value = {"items": [thread_resource()]}

    [comment] = comments.list_comments("dQw4w9WgXcQ", order="relevance").items

    assert (comment.id, comment.reply_count, comment.video_id, comment.author_channel_id) == (
        "Ugc1",
        2,
        "dQw4w9WgXcQ",
        CHANNEL_ID,
    )
    request = api.public.commentThreads().list.call_args.kwargs
    assert (request["videoId"], request["order"]) == ("dQw4w9WgXcQ", "relevance")
    assert "moderationStatus" not in request


def test_list_comments_defaults_to_my_whole_channel(api, my_channel):
    api.oauth.commentThreads().list().execute.return_value = {"items": []}

    comments.list_comments(status="held", search="buy now")

    request = api.oauth.commentThreads().list.call_args.kwargs
    assert request["allThreadsRelatedToChannelId"] == CHANNEL_ID
    assert (request["moderationStatus"], request["searchTerms"]) == ("heldForReview", "buy now")


def test_moderation_queues_of_a_video_need_oauth(api):
    api.oauth.commentThreads().list().execute.return_value = {"items": []}
    comments.list_comments("dQw4w9WgXcQ", status="spam")
    assert api.oauth.commentThreads().list.call_args.kwargs["moderationStatus"] == "likelySpam"
    api.public.commentThreads.assert_not_called()


def test_moderation_status_is_reported_in_our_words(api):
    item = thread_resource(comment_resource(moderationStatus="heldForReview"))
    api.public.commentThreads().list().execute.return_value = {"items": [item]}
    assert comments.list_comments("dQw4w9WgXcQ").items[0].status == "held"


def test_list_replies(api):
    reply = comment_resource("Ugc1.r1", parentId="Ugc1")
    api.public.comments().list().execute.return_value = {"items": [reply]}

    [found] = comments.list_replies("https://www.youtube.com/watch?v=dQw4w9WgXcQ&lc=Ugc1").items

    assert found.parent_id == "Ugc1"
    assert api.public.comments().list.call_args.kwargs["parentId"] == "Ugc1"


def test_post_comment(api):
    api.oauth.commentThreads().insert().execute.return_value = thread_resource(replies=0)

    assert comments.post_comment("dQw4w9WgXcQ", "Hello").reply_count == 0

    body = api.oauth.commentThreads().insert.call_args.kwargs["body"]
    assert body == {"snippet": {"videoId": "dQw4w9WgXcQ", "topLevelComment": {"snippet": {"textOriginal": "Hello"}}}}


def test_replying_to_a_reply_joins_its_thread(api):
    api.oauth.comments().insert().execute.return_value = comment_resource("Ugc1.r2", parentId="Ugc1")

    comments.reply_to_comment("Ugc1.r1", "Thanks")

    body = api.oauth.comments().insert.call_args.kwargs["body"]
    assert body == {"snippet": {"parentId": "Ugc1", "textOriginal": "Thanks"}}


def test_edit_comment(api):
    api.oauth.comments().update().execute.return_value = comment_resource(
        textOriginal="it's <3", textDisplay="it&#39;s &lt;3"
    )

    assert comments.edit_comment("Ugc1", "it's <3").text == "it's <3"
    assert api.oauth.comments().update.call_args.kwargs["body"] == {
        "id": "Ugc1",
        "snippet": {"textOriginal": "it's <3"},
    }


def test_deleting_someone_elses_comment_points_at_rejecting(api, my_channel):
    api.oauth.comments().list().execute.return_value = {"items": [comment_resource(author_channel_id="UCother")]}
    with pytest.raises(Forbidden, match="Reject"):
        comments.delete_comment("Ugc1", confirm="Ugc1")
    api.oauth.comments().delete.assert_not_called()


def test_moderation_batches_by_50_and_bans_only_when_asked(api):
    ids = [f"Ugc{i}" for i in range(60)]

    result = comments.reject_comments([*ids, "Ugc0"], ban_author=True)

    assert (len(result.comment_ids), result.status, result.authors_banned) == (60, "rejected", True)
    requests = [c.kwargs for c in api.oauth.comments().setModerationStatus.call_args_list if c.kwargs]
    assert [len(r["id"].split(",")) for r in requests] == [50, 10]
    assert all(r["moderationStatus"] == "rejected" and r["banAuthor"] for r in requests)

    comments.approve_comments(["Ugc1"])
    assert api.oauth.comments().setModerationStatus.call_args.kwargs == {"id": "Ugc1", "moderationStatus": "published"}


def test_moderation_needs_comments(api):
    with pytest.raises(InvalidRequest):
        comments.hold_comments([])
