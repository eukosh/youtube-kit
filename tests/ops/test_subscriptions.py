from youtube_kit.core.ops import subscriptions

from ..fakes import CHANNEL_ID


def subscription_item(subscription_id: str = "sub1") -> dict:
    return {
        "id": subscription_id,
        "snippet": {
            "title": "Channel",
            "publishedAt": "2026-01-01T00:00:00Z",
            "resourceId": {"kind": "youtube#channel", "channelId": CHANNEL_ID},
        },
    }


def test_list_subscriptions(api):
    api.oauth.subscriptions().list().execute.return_value = {"items": [subscription_item()]}
    [found] = subscriptions.list_subscriptions().items
    assert (found.channel_id, found.title) == (CHANNEL_ID, "Channel")


def test_subscribe_is_idempotent(api):
    api.oauth.subscriptions().list().execute.return_value = {"items": [subscription_item()]}
    assert subscriptions.subscribe(CHANNEL_ID).id == "sub1"
    api.oauth.subscriptions().insert.assert_not_called()


def test_subscribe(api):
    api.oauth.subscriptions().list().execute.return_value = {"items": []}
    api.oauth.subscriptions().insert().execute.return_value = subscription_item("new")

    assert subscriptions.subscribe(CHANNEL_ID).id == "new"

    body = api.oauth.subscriptions().insert.call_args.kwargs["body"]
    assert body["snippet"]["resourceId"] == {"kind": "youtube#channel", "channelId": CHANNEL_ID}
    assert api.oauth.subscriptions().list.call_args.kwargs["forChannelId"] == CHANNEL_ID


def test_unsubscribe_deletes_by_subscription_id(api):
    api.oauth.subscriptions().list().execute.return_value = {"items": [subscription_item()]}
    assert subscriptions.unsubscribe(CHANNEL_ID).was_subscribed
    assert api.oauth.subscriptions().delete.call_args.kwargs == {"id": "sub1"}


def test_unsubscribe_is_idempotent(api):
    api.oauth.subscriptions().list().execute.return_value = {"items": []}
    assert not subscriptions.unsubscribe(CHANNEL_ID).was_subscribed
    api.oauth.subscriptions().delete.assert_not_called()
