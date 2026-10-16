from youtube_kit.core.ops import comments


def test_list_comments(api):
    api.public.commentThreads().list().execute.return_value = {
        "items": [
            {
                "snippet": {
                    "totalReplyCount": 2,
                    "topLevelComment": {
                        "id": "c1",
                        "snippet": {
                            "authorDisplayName": "A",
                            "textDisplay": "Nice",
                            "likeCount": 5,
                            "publishedAt": "2026-01-01T00:00:00Z",
                        },
                    },
                }
            }
        ]
    }

    page = comments.list_comments("dQw4w9WgXcQ", order="time")

    assert (page.items[0].id, page.items[0].reply_count) == ("c1", 2)
    assert api.public.commentThreads().list.call_args.kwargs["order"] == "time"
