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
from dealgo.sources import kinds, syndication


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
    assert found.kind == "substack"
    assert found.feed_url == "https://astralcodexten.substack.com/feed"
    # A working title until the first poll, when the feed says what it is
    # actually called.
    assert found.title == "astralcodexten"


@pytest.mark.parametrize(
    "typed",
    ["UCzzzzzzzzzzzzzzzzzzzzzz", "@mkbhd", "https://www.youtube.com/@mkbhd",
     "https://youtube.com/channel/UCzzzzzzzzzzzzzzzzzzzzzz"],
)
def test_youtube_is_left_to_youtube(typed):
    """The plugin recognises all four, and finishes the two that need no
    credentials. A handle needs this account's Google connection to become a
    channel id, so the plugin says so and the host takes over."""
    found = sources.resolve(typed)

    assert found.kind == "youtube"
    if typed.startswith("UC") or "/channel/" in typed:
        assert found.needs_host is False
        assert found.feed_url.endswith("channel_id=UCzzzzzzzzzzzzzzzzzzzzzz")
    else:
        assert found.needs_host is True


def test_a_dotted_handle_is_bluesky_and_a_bare_one_is_youtube():
    """Both are written with an @, and the dots are the only thing telling
    them apart without asking somebody."""
    assert sources.resolve("@mkbhd").kind == "youtube"
    assert sources.resolve("@jay.bsky.social").kind == "bluesky"


def test_a_certain_answer_beats_a_guess():
    """A Bluesky handle may be any domain, so a plugin that is sure about an
    address has to be able to answer over one that is only offering. Without
    it the winner would be whichever plugin's file sorts first."""
    assert sources.resolve("name.substack.com").kind == "substack"
    # And with nobody certain, the guess still stands rather than nothing.
    assert sources.resolve("someone.example").kind == "bluesky"


def test_an_address_nobody_claims_is_read_as_a_feed():
    """RSS is the floor: it is not a plugin, because every plugin's parsing
    is built on it and because something has to catch what nobody claims."""
    found = sources.resolve("https://example.com/atom.xml")

    assert found.kind == "rss"
    assert found.feed_url == "https://example.com/atom.xml"


def test_every_kind_says_which_plugin_offers_it():
    """Four plugins and one floor, so the Sources page can say where each
    came from and the Admin page can say what a plugin is for."""
    by_name = {kind.name: kind for kind in sources.all_kinds()}

    assert by_name["youtube"].plugin == "YouTube"
    assert by_name["reddit"].plugin == "Reddit"
    assert by_name["rss"].plugin == "", "RSS is not a plugin"
    # And only one of them may fill a real YouTube playlist.
    assert [name for name, k in by_name.items() if k.playlistable] == ["youtube"]


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


# -- somewhere else to read the same feed ----------------------------------


def test_a_reddit_source_suggests_a_mirror():
    """Reddit is the kind that rations a reader, so it is the kind worth
    offering a second address for."""
    assert sources.suggest_mirror("reddit", "r/python") == (
        "https://openrss.org/reddit.com/r/python"
    )


def test_the_kinds_that_do_not_ration_us_suggest_nothing():
    """A suggestion nobody needs is a field somebody has to think about for
    no reason."""
    assert sources.suggest_mirror("youtube", "UCzzzzzzzzzzzzzzzzzzzzzz") is None
    assert sources.suggest_mirror("rss", "https://example.com/feed") is None
    assert sources.suggest_mirror("substack", "name.substack.com") is None


def test_a_reddit_key_that_is_not_a_subreddit_suggests_nothing():
    assert sources.suggest_mirror("reddit", "") is None
    assert sources.suggest_mirror("reddit", "python") is None


# -- pictures --------------------------------------------------------------

# Reddit's shape, cut down: the post's HTML sits escaped inside <content>, and
# the same picture is named again as a media:thumbnail at a much smaller size.
REDDIT_WITH_A_PICTURE = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:media="http://search.yahoo.com/mrss/">
  <title>r/ElectricalEngineering</title>
  <entry>
    <title>What value is this resistor?</title>
    <link href="https://www.reddit.com/r/ee/comments/abc/" />
    <id>t3_abc</id>
    <published>2026-09-19T02:19:24+00:00</published>
    <media:thumbnail url="https://preview.redd.it/pic.png?width=140&amp;height=54&amp;s=sig140" />
    <content type="html">&lt;div&gt;&lt;a href="x"&gt;&lt;img src="https://preview.redd.it/pic.png?width=640&amp;amp;crop=smart&amp;amp;s=sig640"&gt;&lt;/a&gt;&lt;p&gt;Any ideas?&lt;/p&gt;&lt;/div&gt;</content>
  </entry>
</feed>
"""


def test_the_biggest_picture_offered_is_the_one_led_with():
    """A feed's declared thumbnail is often a 140px crop while the same
    picture sits in the entry's HTML at 640. The card is sized for a video
    still, and 140px in it looks like a mistake."""
    item = syndication.parse(REDDIT_WITH_A_PICTURE).items[0]

    assert item.thumbnail_url is not None
    assert "width=640" in item.thumbnail_url


def test_entities_in_an_embedded_address_are_undone():
    """A Reddit preview address is signed over its query, so an "&amp;" left
    in it is not cosmetic — it is a URL that will be refused."""
    item = syndication.parse(REDDIT_WITH_A_PICTURE).items[0]

    assert "&amp;" not in (item.thumbnail_url or "")
    assert item.thumbnail_url.endswith("s=sig640")


def test_the_same_picture_twice_is_carried_once():
    item = syndication.parse(REDDIT_WITH_A_PICTURE).items[0]

    assert len(item.images) == 2, item.images   # the 640 and the 140 are different URLs
    # And the one led with comes first, so opening it shows what the card did.
    assert item.images[0] == item.thumbnail_url


NO_PICTURE = """<?xml version="1.0"?>
<rss version="2.0"><channel>
  <title>r/ee</title>
  <item>
    <title>Why is RF so rare?</title>
    <link>https://www.reddit.com/r/ee/comments/def/</link>
    <guid>t3_def</guid>
    <description>&lt;p&gt;Just wondering.&lt;/p&gt;</description>
  </item>
</channel></rss>
"""


def test_a_post_with_no_picture_carries_none():
    """Most of a subreddit is words. A card for one leads with its words."""
    item = syndication.parse(NO_PICTURE).items[0]

    assert item.thumbnail_url is None
    assert item.images == []


def test_the_words_of_a_post_are_unescaped():
    item = syndication.parse(REDDIT_WITH_A_PICTURE).items[0]

    assert item.summary == "Any ideas?"


# -- a box knows which kind it is ------------------------------------------
#
# There is no generic source box any more. You pick the kind by picking the
# box out of the palette, which means the box can ask for what that kind
# actually looks like — and can read what is typed the way somebody typing
# into that box meant it.


@pytest.mark.parametrize(
    ("kind", "typed", "key"),
    [
        ("reddit", "python", "r/python"),
        ("reddit", "r/python", "r/python"),
        ("bluesky", "jay", "@jay.bsky.social"),
        ("bluesky", "me.example.com", "@me.example.com"),
        ("substack", "astralcodexten", "astralcodexten.substack.com"),
    ],
)
def test_a_bare_name_means_what_the_box_it_was_typed_into_means(kind, typed, key):
    """"python" is not a subreddit to anybody in general. It is one to a
    Subreddit box, which is the whole reason the box has a kind."""
    assert kinds.resolve(typed, within=kind).key == key


def test_a_guess_stops_being_a_guess_once_the_kind_is_settled():
    """A Bluesky handle may be any domain, so nothing can be sure "me.example.com"
    is one — until somebody drags out the Bluesky box and types it in."""
    assert kinds.resolve("me.example.com", within="bluesky").kind == "bluesky"
    # Asked of nobody in particular, the same words are only ever a guess,
    # and a plugin certain about them would win.
    from dealgo.plugins import registry

    said = registry.current().recognise("me.example.com")
    assert said is not None and said.guess


def test_what_a_box_refuses_says_what_that_box_wants():
    with pytest.raises(kinds.UnknownSource) as refused:
        kinds.resolve("!!!", within="reddit")

    assert "Reddit" in str(refused.value)
    assert "r/python" in str(refused.value)  # its own example, not a generic one


def test_the_address_box_takes_an_address_and_asks_nobody():
    """Whether it is a feed is settled by reading it, not by its spelling."""
    found = kinds.resolve("example.com/atom.xml", within="rss")

    assert (found.kind, found.feed_url) == ("rss", "https://example.com/atom.xml")


def test_every_kind_says_what_its_box_is_called_and_what_to_type():
    """The palette draws from this, so a kind with nothing to say here would
    be a row nobody can read."""
    for kind in kinds.all_kinds():
        assert kind.noun, kind.name
        assert kind.example, kind.name
