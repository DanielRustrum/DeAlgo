"""Tag boxes that choose which of several tags fit each item, by what it is."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from pamphlets.db import get_settings
from pamphlets.models import Channel, GraphNode, Video, utcnow
from pamphlets.services import graph, tagging, writing
from pamphlets.services import playlists as playlist_service

TAGS = "reviews — a verdict on one product\nnews: what happened this week\ntutorial"


def a_source(session):
    channel = Channel(channel_id="UCmixed", title="Mixed Tech")
    session.add(channel)
    session.flush()
    return channel


def item(session, channel, n, title, *, tags=None, status="pending"):
    video = Video(video_id=f"m{n}", channel_pk=channel.id, title=title, status=status,
                  published_at=utcnow(), tags=tags)
    session.add(video)
    session.flush()
    return video


def choosing_box(session, **said):
    box = graph.add_stamp(session, kind="tag")
    tagging.save(box, {"tagging_mode": "choose", "tagging_tags": TAGS, **said})
    return box


def test_tags_are_read_one_per_line_with_what_they_mean(db):
    with db.session_scope() as session:
        box = choosing_box(session)
        assert [(one.name, one.about) for one in tagging.choices(box)] == [
            ("reviews", "a verdict on one product"),
            ("news", "what happened this week"),
            ("tutorial", ""),
        ]
        assert box.title == "Tag: by what it is"
        assert tagging.words(box) == "chooses from reviews, news, tutorial"
        with pytest.raises(ValueError, match="at least one tag"):
            tagging.save(box, {"tagging_tags": ""})


def test_on_this_machine_it_chooses_by_the_tags_words(db):
    with db.session_scope() as session:
        channel = a_source(session)
        box = choosing_box(session, tagging_engine="local")
        review = item(session, channel, 1, "Phone X review: the verdict after a month")
        guide = item(session, channel, 2, "Tutorial: setting up a home server")
        neither = item(session, channel, 3, "Unboxing live stream")
        assert tagging.chosen(session, review, box) == ["reviews"]
        assert tagging.chosen(session, guide, box) == ["tutorial"]
        assert tagging.chosen(session, neither, box) == []
        # Kept by box, so asked once.
        assert json.loads(review.classified) == {str(box.id): ["reviews"]}


def test_it_learns_from_items_already_carrying_a_tag(db):
    with db.session_scope() as session:
        channel = a_source(session)
        box = choosing_box(session, tagging_engine="local")
        for n in range(6):
            item(session, channel, 10 + n, f"Weekly roundup {n}: chips and phones", tags="news",
                 status="added")
            item(session, channel, 20 + n, f"Benchmarks deep dive {n}", tags="reviews",
                 status="added")
        # No word of “news” in it — but it is like the items that carry it.
        roundup = item(session, channel, 40, "Weekly roundup 9: chips and phones")
        assert tagging.chosen(session, roundup, box) == ["news"]


def test_with_a_model_chosen_it_asks_a_batch_at_a_time(db, monkeypatch):
    asked = []

    def pretend(model, instructions, material, *, counted, system):
        items = json.loads(material)
        asked.append((len(items), system))
        return "Here: " + json.dumps({str(one["id"]): ["news", "made-up"] for one in items})

    monkeypatch.setattr(writing, "write", pretend)
    with db.session_scope() as session:
        account = get_settings(session)
        account.ai_provider, account.ai_key = "anthropic", "sk-test"
        channel = a_source(session)
        box = choosing_box(session, tagging_most="1")
        feed = graph.add_feed(session, playlist_service.create_generic(session, "Feed"))
        source = graph.add_source(session, channel=channel)
        graph.connect(session, source, box)
        graph.connect(session, box, feed)
        videos = [item(session, channel, n, f"Story {n}") for n in range(3)]

        done = tagging.choose_before_filling(session, None, account, graph.routes(session))
        assert done == 3 and asked == [(3, tagging.SYSTEM)]
        # Only tags it was given, and no more than allowed.
        assert all(tagging.chosen(session, video, box) == ["news"] for video in videos)
        # Already chosen: not asked again.
        assert tagging.choose_before_filling(session, None, account, graph.routes(session)) == 0


def test_a_choosing_box_puts_nothing_on_everything_and_filters_see_its_choice(db):
    from pamphlets.services.sync.deciding import decide

    with db.session_scope() as session:
        channel = a_source(session)
        box = choosing_box(session, tagging_engine="local")
        box.marks = "everything"   # left from before it chose: not put on any more
        middle = graph.add_filter(session)
        graph.add_piece(session, kind="carrying", host=middle).tagged = "tutorial"
        feed = graph.add_feed(session, playlist_service.create_generic(session, "Feed"))
        source = graph.add_source(session, channel=channel)
        graph.connect(session, source, box)
        graph.connect(session, box, middle)
        graph.connect(session, middle, feed)
        route = graph.routes(session)[0]
        assert graph.stamped_tags(route.stamps) == []

        account = get_settings(session)
        assert decide(item(session, channel, 1, "Tutorial: a first app"), route, None, account).accept
        held = decide(item(session, channel, 2, "Phone review"), route, None, account)
        assert not held.accept and "not tagged" in held.reason


def test_a_run_tags_what_it_files(world, db):
    from pamphlets.services import sync as sync_service

    with db.session_scope() as session:
        db.get_settings(session).initial_backfill = 10
        source = session.scalar(select(GraphNode).where(GraphNode.kind == "source"))
        feed = session.scalar(select(GraphNode).where(GraphNode.kind == "feed"))
        from fakes import unwire

        unwire(session, source.channel)
        box = choosing_box(session, tagging_engine="local")
        graph.connect(session, source, box)
        graph.connect(session, box, feed)
    from fakes import entry
    from pamphlets.plugins.publisher import VideoDetails

    world["entries"] = [entry("v0", minutes_ago=1), entry("v1", minutes_ago=2)]
    world["client"].details = {f"v{n}": VideoDetails(f"v{n}", f"Video v{n}", 600, "none", "public")
                               for n in range(2)}
    sync_service.run_sync("manual", force=True)
    with db.session_scope() as session:
        for video in session.scalars(select(Video)):
            assert video.classified is not None   # chosen for, once, before it was judged


@pytest.fixture
def client(db, monkeypatch):
    from pamphlets import scheduler
    from pamphlets.web import app as web_app

    monkeypatch.setattr(scheduler, "start", lambda: None)
    monkeypatch.setattr(scheduler, "shutdown", lambda: None)
    monkeypatch.setattr(scheduler, "next_run_time", lambda: None)
    monkeypatch.setattr(web_app, "init_db", lambda: None)
    with TestClient(web_app.app) as test_client:
        yield test_client


def test_the_canvas_sets_a_tag_box_to_choose(client, db):
    made = client.post("/graph/nodes", data={"kind": "tag"}).json()
    box = next(node for node in made["nodes"] if node["kind"] == "tag")
    assert box["stamp"]["choosing"]["mode"] == "fixed"
    saved = client.post(f"/graph/nodes/{box['id']}", data={
        "label": "", "marks": "", "tagging_mode": "choose", "tagging_tags": TAGS,
        "tagging_most": "2", "tagging_engine": "auto",
    }).json()
    drawn = next(node for node in saved["nodes"] if node["id"] == box["id"])
    assert drawn["note"] == "chooses from reviews, news, tutorial"
    assert drawn["stamp"]["choosing"]["tags"].startswith("reviews — a verdict")
    assert "on this machine" in drawn["stamp"]["choosing"]["how"]



def test_at_least_gives_every_item_that_many_the_likeliest_first(db):
    with db.session_scope() as session:
        channel = a_source(session)
        box = choosing_box(session, tagging_engine="local", tagging_least="1", tagging_most="2")
        assert tagging.words(box) == "chooses 1–2 from reviews, news, tutorial"
        # Nothing in it fits well, but it must carry one.
        assert len(tagging.chosen(session, item(session, channel, 1, "Unboxing live stream"), box)) == 1
        # A clear fit is still the first.
        assert tagging.chosen(session, item(session, channel, 2, "Tutorial: a first app"), box)[0] == "tutorial"
        with pytest.raises(ValueError, match="more than at most"):
            tagging.save(box, {"tagging_least": "3"})
