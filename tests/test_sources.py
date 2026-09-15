"""Sources other than YouTube.

De-Algo's polling was always an RSS reader — YouTube publishes a per-channel
Atom feed — so following a subreddit or a newsletter is the same act with a
different address. These cover the two halves of that: working out where a
feed is from what somebody typed, and reading whichever shape it is written
in.
"""

from __future__ import annotations

import datetime as dt

import pytest

from dealgo import sources
from dealgo.sources import syndication


# -- what somebody typed ---------------------------------------------------


@pytest.mark.parametrize(
    "typed, kind, key",
    [
        ("r/python", "reddit", "r/python"),
        ("/r/python/", "reddit", "r/python"),
        ("https://www.reddit.com/r/python/", "reddit", "r/python"),
        ("https://old.reddit.com/r/python/top/", "reddit", "r/python"),
        ("@jay.bsky.social", "bluesky", "@jay.bsky.social"),
        ("https://bsky.app/profile/jay.bsky.social", "bluesky", "@jay.bsky.social"),
        ("astralcodexten.substack.com", "substack", "astralcodexten.substack.com"),
        ("https://astralcodexten.substack.com/", "substack", "astralcodexten.substack.com"),
        ("https://example.com/blog/feed.xml", "rss", "https://example.com/blog/feed.xml"),
    ],
)
def test_a_reference_says_what_it_is_by_its_shape(typed, kind, key):
    """Nothing here makes a request: a subreddit, a handle and an address all
    say where their feed is by how they are written."""
    found = sources.resolve(typed)
    assert (found.kind, found.key) == (kind, key)
    assert found.feed_url.startswith("http")


def test_a_reddit_feed_is_the_subreddits_own():
    assert sources.resolve("r/python").feed_url == "https://www.reddit.com/r/python/.rss"


def test_a_substack_feed_is_the_sites_own():
    found = sources.resolve("astralcodexten.substack.com")
    assert found.feed_url == "https://astralcodexten.substack.com/feed"
    assert found.title == "Astralcodexten"


@pytest.mark.parametrize(
    "typed",
    ["UCzzzzzzzzzzzzzzzzzzzzzz", "@mkbhd", "https://www.youtube.com/@mkbhd",
     "https://youtube.com/channel/UCzzzzzzzzzzzzzzzzzzzzzz"],
)
def test_youtube_is_left_to_youtube(typed):
    """Turning a handle into a channel id may need an API key, which is that
    service's business rather than this one's."""
    assert sources.looks_like_youtube(typed) is True


def test_a_dotted_handle_is_bluesky_and_a_bare_one_is_youtube():
    """Both are written with an @, and the dots are the only thing telling
    them apart without asking somebody."""
    assert sources.looks_like_youtube("@mkbhd") is True
    assert sources.looks_like_youtube("@jay.bsky.social") is False
    assert sources.resolve("@jay.bsky.social").kind == "bluesky"


def test_nonsense_is_refused_in_words():
    with pytest.raises(sources.UnknownSource) as refused:
        sources.resolve("what even is this")
    assert "not something this knows how to follow" in str(refused.value)

    with pytest.raises(sources.UnknownSource):
        sources.resolve("   ")


# -- reading a feed --------------------------------------------------------

RSS = """<?xml version="1.0"?>
<rss version="2.0">
  <channel>
    <title>A Newsletter</title>
    <item>
      <title>The older one</title>
      <link>https://example.com/one</link>
      <guid>https://example.com/one</guid>
      <pubDate>Mon, 04 May 2026 09:00:00 +0000</pubDate>
      <description>&lt;p&gt;Some &lt;b&gt;words&lt;/b&gt;.&lt;/p&gt;</description>
    </item>
    <item>
      <title>The newer one</title>
      <link>https://example.com/two</link>
      <guid>tag:example.com,2026:2</guid>
      <pubDate>Tue, 05 May 2026 09:00:00 +0000</pubDate>
      <enclosure url="https://example.com/two.png" type="image/png"/>
    </item>
  </channel>
</rss>
"""

ATOM = """<?xml version="1.0"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>A Profile</title>
  <entry>
    <id>at://did:plc:abc/post/1</id>
    <title>A skeet</title>
    <link rel="alternate" href="https://bsky.app/profile/jay/post/1"/>
    <published>2026-05-05T09:00:00Z</published>
    <summary>Hello there</summary>
  </entry>
</feed>
"""


def test_an_rss_feed_is_read_newest_first():
    feed = syndication.parse(RSS)
    assert feed.title == "A Newsletter"
    assert [item.title for item in feed.items] == ["The newer one", "The older one"]


def test_an_entry_keeps_its_own_id_and_link():
    """The guid where there is one, the link where there is not — so an item
    stays the same item when its title is edited."""
    feed = syndication.parse(RSS)
    newer, older = feed.items
    assert newer.guid == "tag:example.com,2026:2"
    assert newer.link == "https://example.com/two"
    assert older.guid == "https://example.com/one"


def test_the_markup_is_taken_out_of_a_summary():
    """It is shown in a card, and a feed is not a place to accept markup from."""
    older = syndication.parse(RSS).items[1]
    assert older.summary == "Some words ."


def test_a_picture_is_found_wherever_the_feed_put_it():
    assert syndication.parse(RSS).items[0].thumbnail_url == "https://example.com/two.png"


def test_an_atom_feed_is_read_the_same_way():
    feed = syndication.parse(ATOM)
    assert feed.title == "A Profile"
    assert [item.title for item in feed.items] == ["A skeet"]
    assert feed.items[0].link == "https://bsky.app/profile/jay/post/1"
    assert feed.items[0].summary == "Hello there"


def test_both_kinds_of_timestamp_are_understood():
    """RSS writes them one way and Atom the other, and a feed with an
    unreadable one is still a feed."""
    assert syndication.parse(RSS).items[0].published_at == dt.datetime(
        2026, 5, 5, 9, 0, tzinfo=dt.timezone.utc
    )
    assert syndication.parse(ATOM).items[0].published_at == dt.datetime(
        2026, 5, 5, 9, 0, tzinfo=dt.timezone.utc
    )


def test_an_entry_with_nothing_to_name_it_is_skipped():
    """No id and no link is an entry nothing could be said about twice."""
    feed = syndication.parse(
        '<rss version="2.0"><channel><title>T</title><item>'
        "<title>Nameless</title></item></channel></rss>"
    )
    assert feed.items == []
