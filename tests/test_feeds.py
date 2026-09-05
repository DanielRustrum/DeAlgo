from __future__ import annotations

import datetime as dt

from dealgo.youtube.feeds import parse_feed

SAMPLE = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns:yt="http://www.youtube.com/xml/schemas/2015"
      xmlns:media="http://search.yahoo.com/mrss/"
      xmlns="http://www.w3.org/2005/Atom">
  <yt:channelId>aaaaaaaaaaaaaaaaaaaaaa</yt:channelId>
  <title>Some Channel</title>
  <entry>
    <yt:videoId>vid_old</yt:videoId>
    <title>An older video</title>
    <published>2026-01-01T10:00:00+00:00</published>
    <media:group><media:thumbnail url="https://i.ytimg.com/vi/vid_old/hq.jpg"/></media:group>
  </entry>
  <entry>
    <yt:videoId>vid_new</yt:videoId>
    <title>The newest video</title>
    <link rel="alternate" href="https://www.youtube.com/watch?v=vid_new"/>
    <published>2026-02-01T10:00:00+00:00</published>
    <media:group><media:thumbnail url="https://i.ytimg.com/vi/vid_new/hq.jpg"/></media:group>
  </entry>
  <entry>
    <yt:videoId>vid_short</yt:videoId>
    <title>A short</title>
    <link rel="alternate" href="https://www.youtube.com/shorts/vid_short"/>
    <published>2026-01-15T10:00:00+00:00</published>
  </entry>
</feed>
"""


def test_parse_feed_reads_channel_metadata():
    result = parse_feed(SAMPLE)
    # YouTube publishes the feed-level id without its UC prefix; the URL it is
    # fetched from, and every entry, keep it. Normalizing here is what makes the
    # id round-trip back into a feed request.
    assert result.channel_id == "UCaaaaaaaaaaaaaaaaaaaaaa"
    assert result.channel_title == "Some Channel"
    assert len(result.entries) == 3


def test_parse_feed_orders_newest_first():
    entries = parse_feed(SAMPLE).entries
    assert [e.video_id for e in entries] == ["vid_new", "vid_short", "vid_old"]
    assert entries[0].published_at == dt.datetime(2026, 2, 1, 10, tzinfo=dt.timezone.utc)
    assert entries[0].thumbnail_url.endswith("vid_new/hq.jpg")


def test_parse_feed_tolerates_an_empty_channel():
    empty = """<?xml version="1.0"?>
    <feed xmlns="http://www.w3.org/2005/Atom"
          xmlns:yt="http://www.youtube.com/xml/schemas/2015">
      <yt:channelId>bbbbbbbbbbbbbbbbbbbbbb</yt:channelId>
      <title>Quiet Channel</title>
    </feed>"""
    result = parse_feed(empty)
    assert result.entries == []
    assert result.channel_id == "UCbbbbbbbbbbbbbbbbbbbbbb"


def test_shorts_are_recognised_from_their_link():
    by_id = {e.video_id: e for e in parse_feed(SAMPLE).entries}
    assert by_id["vid_short"].is_short is True
    assert by_id["vid_new"].is_short is False
    assert by_id["vid_old"].is_short is False
