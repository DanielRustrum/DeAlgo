"""Reading a YouTube channel feed.

There is no YouTube parser any more. The feed is Atom, Pamphlets reads Atom,
and the YouTube plugin says the two things only it knows: that an entry's id
carries the video id, and that a Short is told apart by the address it links
to. These are the same properties the old parser was held to, asked of the
two halves that do the work now.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

from dealgo.plugins import registry
from dealgo.sources import syndication

SHIPPED = Path(__file__).resolve().parent.parent / "dealgo" / "plugins" / "builtin"

SAMPLE = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns:yt="http://www.youtube.com/xml/schemas/2015"
      xmlns:media="http://search.yahoo.com/mrss/"
      xmlns="http://www.w3.org/2005/Atom">
  <yt:channelId>aaaaaaaaaaaaaaaaaaaaaa</yt:channelId>
  <title>Some Channel</title>
  <entry>
    <id>yt:video:vid_old</id>
    <title>An older video</title>
    <link rel="alternate" href="https://www.youtube.com/watch?v=vid_old"/>
    <published>2026-01-01T10:00:00+00:00</published>
    <media:group><media:thumbnail url="https://i.ytimg.com/vi/vid_old/hq.jpg"/></media:group>
  </entry>
  <entry>
    <id>yt:video:vid_new</id>
    <title>The newest video</title>
    <link rel="alternate" href="https://www.youtube.com/watch?v=vid_new"/>
    <published>2026-02-01T10:00:00+00:00</published>
    <media:group><media:thumbnail url="https://i.ytimg.com/vi/vid_new/hq.jpg"/></media:group>
  </entry>
  <entry>
    <id>yt:video:vid_short</id>
    <title>A short</title>
    <link rel="alternate" href="https://www.youtube.com/shorts/vid_short"/>
    <published>2026-01-15T10:00:00+00:00</published>
  </entry>
</feed>
"""


def read(xml: str = SAMPLE):
    """The feed, as the host reads it and the plugin then refines it."""
    found = registry.read(SHIPPED)
    feed = syndication.parse(xml)
    refined = []
    for item in feed.items:
        said = found.refine(
            "youtube",
            {"guid": item.guid, "title": item.title, "link": item.link or "", "summary": ""},
        )
        refined.append((item, said))
    return feed, refined


def test_the_host_reads_the_feed_itself():
    """No second parser in Lua. Rewriting a namespace-aware XML reader as
    string matching would be a worse parser, not a plugin."""
    feed, refined = read()

    assert feed.title == "Some Channel"
    assert len(refined) == 3


def test_the_entries_come_back_newest_first():
    feed, refined = read()

    assert [said["id"] for _, said in refined] == ["vid_new", "vid_short", "vid_old"]
    first, _ = refined[0]
    assert first.published_at == dt.datetime(2026, 2, 1, 10, tzinfo=dt.timezone.utc)


def test_a_thumbnail_nested_in_a_media_group_is_found():
    """YouTube wraps it in <media:group>, and a reader that only looked one
    level down found nothing at all there."""
    _, refined = read()
    by_id = {said["id"]: item for item, said in refined}

    assert by_id["vid_new"].thumbnail_url.endswith("vid_new/hq.jpg")


def test_the_plugin_reads_the_video_id_out_of_the_entrys_own_id():
    """A video is filed under its own id, not under the feed's guid."""
    _, refined = read()

    assert all(said["id"] and ":" not in said["id"] for _, said in refined)


def test_shorts_are_recognised_from_their_link():
    """Nothing in the feed says "this is a Short". The address is the only
    thing that does, without spending API quota to ask."""
    _, refined = read()
    by_id = {said["id"]: said for _, said in refined}

    assert by_id["vid_short"].get("hint") == "shorts"
    assert not by_id["vid_new"].get("hint")
    assert not by_id["vid_old"].get("hint")


def test_an_empty_channel_is_read_without_complaint():
    empty = """<?xml version="1.0"?>
    <feed xmlns="http://www.w3.org/2005/Atom"
          xmlns:yt="http://www.youtube.com/xml/schemas/2015">
      <yt:channelId>bbbbbbbbbbbbbbbbbbbbbb</yt:channelId>
      <title>Quiet Channel</title>
    </feed>"""
    feed, refined = read(empty)

    assert refined == []
    assert feed.title == "Quiet Channel"


def test_an_entry_that_is_not_a_video_gets_no_id_from_the_plugin():
    """So the host falls back to the hash every other source gets, rather
    than filing something under nothing."""
    found = registry.read(SHIPPED)

    said = found.refine("youtube", {"guid": "t3_notavideo", "link": "https://x/y"})

    assert not said.get("id")
