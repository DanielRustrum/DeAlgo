"""YouTube, now that YouTube is a plugin.

Everything the app used to know about this service — which endpoint answers
what, how a reference is classified, what a call costs, how a Posts tab is
laid out — lives in one Lua file. These are the properties the old client was
held to, asked of the thing that holds them now.

Nothing here reaches YouTube. The host's own client is stubbed, which is the
same seam the plugin's requests go through: it never makes one itself.
"""

from __future__ import annotations

import datetime as dt
import json

import httpx
import pytest

from dealgo import outgoing
from dealgo.models import OAuthToken, User, utcnow
from dealgo.plugins import registry
from dealgo.plugins.capabilities import acting_for
from dealgo.plugins.publisher import Publisher


@pytest.fixture
def signed_in(db):
    """An account with a live token, since that is what `account` sends as."""
    with db.session_scope() as session:
        session.add(User(id=1, username="me", password_hash="x"))
    with db.session_scope() as session:
        session.add(OAuthToken(
            provider="youtube",
            owner_pk=1,
            access_token="secret-token",
            expires_at=utcnow() + dt.timedelta(hours=1),
        ))
    registry.reload()


@pytest.fixture
def google(monkeypatch):
    """Stand in for Google, and record every request that reaches it."""
    made: list[httpx.Request] = []
    answers: list[httpx.Response] = []

    class Client:
        def request(self, method, url, params=None, json=None, headers=None):
            request = httpx.Request(method, url, params=params or None, json=json)
            made.append(request)
            if answers:
                answer = answers.pop(0)
                answer.request = request
                return answer
            return httpx.Response(200, request=request, json={"items": []})

        def get(self, url, headers=None):
            request = httpx.Request("GET", url, headers=headers)
            made.append(request)
            answer = answers.pop(0) if answers else httpx.Response(200, text="")
            answer.request = request
            return answer

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False


    monkeypatch.setattr(outgoing, "client", lambda: Client())
    # Read again with the stub in place: a plugin's `net` is handed the
    # client to use when it loads, so a registry built before this is a
    # registry holding the real one.
    registry.reload()
    return made, answers


def says(*payloads) -> list[httpx.Response]:
    return [httpx.Response(200, json=payload) for payload in payloads]


def publisher() -> Publisher:
    return Publisher(1, writable=True, readable=True)


def asked(made: list[httpx.Request]) -> list[tuple[str, str, dict]]:
    """Each request as (method, endpoint, query), which is what these are about."""
    return [
        (r.method, r.url.path.rsplit("/", 1)[-1], dict(r.url.params))
        for r in made
    ]


# -- classifying whatever was pasted in ------------------------------------
#
# The same shapes the old parser was given, judged by which endpoint the
# plugin then asks — because that, not an intermediate tuple, is what being
# classified correctly actually means.

CHANNEL_ID = "UC_x5XG1OV2P6uZZ5FSM9Ttw"


@pytest.mark.parametrize(
    ("reference", "expected"),
    [
        (CHANNEL_ID, {"id": CHANNEL_ID}),
        (f"https://www.youtube.com/channel/{CHANNEL_ID}", {"id": CHANNEL_ID}),
        (f"youtube.com/channel/{CHANNEL_ID}/videos", {"id": CHANNEL_ID}),
        ("@GoogleDevelopers", {"forHandle": "@GoogleDevelopers"}),
        ("https://www.youtube.com/@GoogleDevelopers", {"forHandle": "@GoogleDevelopers"}),
        ("https://www.youtube.com/user/GoogleDevelopers", {"forUsername": "GoogleDevelopers"}),
    ],
)
def test_a_reference_decides_which_endpoint_is_asked(signed_in, google, reference, expected):
    made, answers = google
    answers.extend(says({"items": [{"id": CHANNEL_ID, "snippet": {"title": "Devs"}}]}))

    with acting_for(1):
        found = publisher().resolve_channel(reference)

    assert found is not None and found.title == "Devs"
    method, endpoint, query = asked(made)[0]
    assert (method, endpoint) == ("GET", "channels")
    for name, value in expected.items():
        assert query[name] == value


def test_a_name_falls_through_to_search(signed_in, google):
    """Which costs a hundred units, so it is never the first thing tried."""
    made, answers = google
    answers.extend(says(
        {"items": [{"snippet": {"channelId": CHANNEL_ID}}]},
        {"items": [{"id": CHANNEL_ID, "snippet": {"title": "Google Developers"}}]},
    ))

    with acting_for(1):
        found = publisher().resolve_channel("Google Developers")

    assert found.channel_id == CHANNEL_ID
    assert [(m, e) for m, e, _ in asked(made)] == [
        ("GET", "search"), ("GET", "channels"),
    ]
    assert asked(made)[0][2]["q"] == "Google Developers"


def test_a_stale_handle_falls_back_to_searching_for_it(signed_in, google):
    """`forHandle` finding nothing is not the end of it: somebody pasting a
    handle that has since changed meant the channel, not the string."""
    made, answers = google
    answers.extend(says(
        {"items": []},
        {"items": [{"snippet": {"channelId": CHANNEL_ID}}]},
        {"items": [{"id": CHANNEL_ID, "snippet": {"title": "Devs"}}]},
    ))

    with acting_for(1):
        found = publisher().resolve_channel("@GoogleDevelopers")

    assert found.channel_id == CHANNEL_ID
    # The @ is dropped for the search: it is not part of the name.
    assert asked(made)[1][2]["q"] == "GoogleDevelopers"


@pytest.mark.parametrize("reference", ["", "   ", "https://www.youtube.com/watch?v=dQw4w9WgXcQ"])
def test_something_that_is_not_a_channel_asks_nothing(signed_in, google, reference):
    """A video link is not a channel link, and finding that out must not cost
    a hundred units of somebody's day."""
    made, _ = google

    with acting_for(1):
        assert publisher().resolve_channel(reference) is None
    assert made == []


# -- what a video is -------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "seconds"),
    [("PT4M13S", 253), ("PT1H2M3S", 3723), ("PT45S", 45),
     ("P1DT2H", 93600), ("PT0S", 0), (None, None), ("junk", 0)],
)
def test_a_duration_is_read_as_seconds(signed_in, google, raw, seconds):
    _, answers = google
    answers.extend(says({"items": [{
        "id": "v1",
        "snippet": {"title": "A video", "liveBroadcastContent": "none"},
        "contentDetails": {"duration": raw} if raw else {},
        "status": {"privacyStatus": "public"},
        "statistics": {"viewCount": "1200", "likeCount": "34"},
    }]}))

    with acting_for(1):
        found = publisher().video_details(["v1"])

    assert found["v1"].duration_sec == (seconds if raw else None)
    assert (found["v1"].view_count, found["v1"].like_count) == (1200, 34)


def test_a_hidden_count_stays_nothing_rather_than_zero(signed_in, google):
    """"No likes recorded" is not "nobody liked it", and a sort box that
    treated them the same would bury every video on a channel that hides them."""
    _, answers = google
    answers.extend(says({"items": [{
        "id": "v1",
        "snippet": {"title": "A video"},
        "contentDetails": {"duration": "PT1M"},
        "statistics": {"viewCount": "5"},
    }]}))

    with acting_for(1):
        found = publisher().video_details(["v1"])

    assert found["v1"].like_count is None
    assert found["v1"].view_count == 5


def test_ids_go_up_in_batches_of_fifty(signed_in, google):
    """Fifty ids cost one unit and one id costs one unit, so asking one at a
    time would cost fifty times as much for the same answer."""
    made, answers = google
    answers.extend(says({"items": []}, {"items": []}))

    with acting_for(1):
        publisher().video_details([f"v{n}" for n in range(60)])

    queries = [query["id"].split(",") for _, _, query in asked(made)]
    assert [len(batch) for batch in queries] == [50, 10]


# -- playlists -------------------------------------------------------------


def test_a_playlist_is_read_page_by_page(signed_in, google):
    made, answers = google
    answers.extend(says(
        {"items": [{"id": "i1", "snippet": {
            "position": 0, "title": "One",
            "resourceId": {"kind": "youtube#video", "videoId": "v1"}}}],
         "nextPageToken": "second"},
        {"items": [{"id": "i2", "snippet": {
            "position": 1, "title": "Two",
            "resourceId": {"kind": "youtube#video", "videoId": "v2"}}}]},
    ))

    with acting_for(1):
        found = publisher().playlist_items("PL1")

    assert [item.video_id for item in found] == ["v1", "v2"]
    assert asked(made)[1][2]["pageToken"] == "second"


def test_something_in_a_playlist_that_is_not_a_video_is_left_alone(signed_in, google):
    """A playlist can hold one. It is not ours to reason about, so it is not
    reported as if it were a video with a missing id."""
    _, answers = google
    answers.extend(says({"items": [
        {"id": "i1", "snippet": {"resourceId": {"kind": "youtube#channel"}}},
        {"id": "i2", "snippet": {"resourceId": {"kind": "youtube#video", "videoId": "v2"}}},
    ]}))

    with acting_for(1):
        found = publisher().playlist_items("PL1")

    assert [item.video_id for item in found] == ["v2"]


def test_renaming_carries_the_description_so_it_is_not_wiped(signed_in, google):
    """YouTube clears any mutable property an update leaves out, so a rename
    that sent only the title would quietly empty the description."""
    made, answers = google
    answers.extend(says(
        {"items": [{"id": "PL1", "snippet": {"description": "What this is for"}}]},
        {"id": "PL1"},
    ))

    with acting_for(1):
        publisher().rename_playlist("PL1", "A better name")

    sent = made[1]
    assert sent.method == "PUT"
    body = json.loads(sent.content)
    assert body["snippet"] == {
        "title": "A better name", "description": "What this is for",
    }


# -- what it all costs -----------------------------------------------------


def spent(db, owner=1) -> int:
    from dealgo.services import quota

    with db.session_scope() as session:
        return quota.state(session).used


def test_each_call_is_charged_at_the_published_price(signed_in, google, db):
    """Reads are a unit whatever they bring back; a write is fifty."""
    _, answers = google
    answers.extend(says({"items": []}, {"items": []}, {"id": "item-1"}))
    before = spent(db)

    with acting_for(1):
        made = publisher()
        made.video_details(["a", "b"])
        made.playlist_items("PL")
        made.insert_playlist_item("PL", "a")

    assert spent(db) - before == 1 + 1 + 50


def test_a_request_google_refuses_is_still_charged(signed_in, google, db):
    """Google bills failed calls too — except the one refused for no quota,
    which instead says the day is spent: believed over the count, so nothing
    more is tried until it resets."""
    _, answers = google
    answers.append(httpx.Response(
        404, json={"error": {"errors": [{"reason": "videoNotFound"}]}}
    ))
    before = spent(db)

    with acting_for(1):
        with pytest.raises(Exception):
            publisher().insert_playlist_item("PL", "a")
    after_refusal = spent(db)

    answers.append(httpx.Response(
        403, json={"error": {"errors": [{"reason": "quotaExceeded"}]}}
    ))
    with acting_for(1):
        with pytest.raises(Exception):
            publisher().insert_playlist_item("PL", "a")

    assert after_refusal - before == 50
    from dealgo.services import quota

    with db.session_scope() as session:
        day = quota.state(session)
        assert day.exhausted and day.spendable == 0


# -- community posts -------------------------------------------------------


def page(posts: list[dict]) -> str:
    """A Posts tab, shaped the way YouTube ships one."""
    threads = [
        {
            "backstagePostThreadRenderer": {
                "post": {
                    "backstagePostRenderer": {
                        "postId": post["id"],
                        "contentText": {"runs": [{"text": post.get("text", "")}]},
                        "publishedTimeText": {"runs": [{"text": post.get("age", "2 days ago")}]},
                        **(
                            {
                                "backstageAttachment": {
                                    "postMultiImageRenderer": {
                                        "images": [
                                            {
                                                "backstageImageRenderer": {
                                                    "image": {
                                                        "thumbnails": [
                                                            {"url": url + "?s=100", "width": 100},
                                                            {"url": url, "width": 800},
                                                        ]
                                                    }
                                                }
                                            }
                                            for url in post["images"]
                                        ]
                                    }
                                }
                            }
                            if post.get("images")
                            else {}
                        ),
                    }
                }
            }
        }
        for post in posts
    ]
    data = {"contents": {"twoColumnBrowseResultsRenderer": {"tabs": threads}}}
    return "<html><script>var ytInitialData = " + json.dumps(data) + ";</script></html>"


def serves(google, html: str):
    _, answers = google
    answers.append(httpx.Response(200, text=html))


def read_posts(key: str = "UCzzzzzzzzzzzzzzzzzzzzzz") -> list[dict]:
    with acting_for(1):
        return registry.current().posts("youtube", key)


@pytest.mark.reads_pages
def test_it_reads_the_text_images_and_age_of_a_post(signed_in, google):
    serves(google, page([{
        "id": "Ugk1", "text": "Back on Friday", "age": "3 days ago",
        "images": ["https://img.test/a.jpg", "https://img.test/b.jpg"],
    }]))
    now = dt.datetime.now(dt.timezone.utc).timestamp()

    found = read_posts()

    assert len(found) == 1
    post = found[0]
    assert post["id"] == "Ugk1"
    assert post["text"] == "Back on Friday"
    # The largest thumbnail wins: a tile is displayed big.
    assert post["images"] == ["https://img.test/a.jpg", "https://img.test/b.jpg"]
    assert abs(post["published_at"] - (now - 3 * 86400)) < 60


@pytest.mark.reads_pages
def test_a_post_is_fetched_with_a_browsers_user_agent(signed_in, google):
    """Without one YouTube serves a consent wall, which carries no data."""
    made, _ = google
    serves(google, page([{"id": "Ugk1", "text": "Hi"}]))

    read_posts()

    assert "Mozilla/5.0" in made[0].headers["user-agent"]


@pytest.mark.reads_pages
def test_a_post_with_no_date_it_understands_keeps_none(signed_in, google):
    serves(google, page([{"id": "Ugk1", "text": "Hi", "age": "just now"}]))

    # Absent rather than nothing: a Lua table has no room for a nil, and the
    # host reads a missing date the same way it reads an unreadable one.
    assert read_posts()[0].get("published_at") is None


@pytest.mark.reads_pages
@pytest.mark.parametrize("html", ["", "<html>nothing here</html>",
                                  "<script>var ytInitialData = {oops;</script>"])
def test_a_page_it_cannot_read_yields_nothing_rather_than_raising(signed_in, google, html):
    """YouTube can change this shape whenever it likes. It must not take a
    sync down when it does."""
    serves(google, html)

    assert read_posts() == []


@pytest.mark.reads_pages
def test_the_same_post_is_only_read_once(signed_in, google):
    """The blob repeats a renderer in more than one place."""
    once = page([{"id": "Ugk1", "text": "Hello"}])
    inner = json.loads(once.split("var ytInitialData = ")[1].rsplit(";", 1)[0])
    twice = once.replace('"contents"', '"header": ' + json.dumps(inner["contents"]) + ', "contents"')
    serves(google, twice)

    assert len(read_posts()) == 1


# -- what kind of thing a YouTube item is ----------------------------------
#
# A Short, a premiere and a community post are YouTube's own distinctions.
# They sat on the host's Filter box once, as four switches nobody outside
# YouTube could mean anything by; they are conditions of this plugin's now,
# slotted under its box.


def an_item(**over) -> dict:
    """One item as the host hands it over: plain values only."""
    base = {
        "title": "", "kind": "video", "words": "", "link": "", "duration": 0,
        "views": 0, "likes": 0, "is_short": False, "live": "", "source": "youtube",
    }
    base.update(over)
    return base


def shipped():
    from pathlib import Path

    from dealgo.plugins import registry

    here = Path(__file__).resolve().parent.parent / "dealgo" / "plugins" / "builtin"
    return registry.read(here)


def test_no_videos_holds_an_ordinary_upload_and_nothing_else():
    """A Short and a broadcast are their own things, each with a condition of
    its own. This one is about everything else."""
    found = shipped()

    assert found.keeps("youtube:no-videos", an_item(), {}) is False
    assert found.keeps("youtube:no-videos", an_item(is_short=True), {}) is True
    assert found.keeps("youtube:no-videos", an_item(live="upcoming"), {}) is True
    assert found.keeps("youtube:no-videos", an_item(kind="post"), {}) is True


def test_no_live_holds_a_broadcast_whether_it_has_started_or_not():
    found = shipped()

    assert found.keeps("youtube:no-live", an_item(live="live"), {}) is False
    assert found.keeps("youtube:no-live", an_item(live="upcoming"), {}) is False
    assert found.keeps("youtube:no-live", an_item(live="none"), {}) is True
    # Nothing recorded is not a broadcast: the details are fetched after
    # discovery and may never say.
    assert found.keeps("youtube:no-live", an_item(), {}) is True


def test_no_posts_holds_a_community_post():
    found = shipped()

    assert found.keeps("youtube:no-posts", an_item(kind="post"), {}) is False
    assert found.keeps("youtube:no-posts", an_item(kind="video"), {}) is True


def test_the_content_conditions_let_everything_else_by():
    """The rule that keeps them safe to place anywhere: a subreddit has no
    Shorts and no premieres, and must not be swallowed by a question about
    either."""
    found = shipped()
    elsewhere = an_item(source="reddit", kind="post", is_short=True, live="live")

    for ref in ("youtube:no-videos", "youtube:no-live", "youtube:no-posts"):
        assert found.keeps(ref, elsewhere, {}) is True, ref
