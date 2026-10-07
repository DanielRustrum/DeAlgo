"""The algorithm of one's own, and the Aggregation piece that puts it to work.

Taught on made-up history — one source's items always clicked open, the
other's always skipped — it should learn the difference, and act on it under
a Filter, a Sort and an Expire box; and do nothing at all while it has too
little to go on, or is switched off.
"""

from __future__ import annotations

import datetime as dt

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from dealgo.db import get_settings
from dealgo.models import Channel, Consumption, Placement, Video, utcnow
from dealgo.services import algorithm, graph
from dealgo.services import playlists as playlist_service


def two_sources(session):
    liked = Channel(channel_id="UCliked", title="Liked Science")
    passed = Channel(channel_id="UCpassed", title="Shouty Clips")
    session.add_all([liked, passed])
    session.flush()
    return liked, passed


def item(session, channel, n, *, title=None, duration=600):
    video = Video(video_id=f"{channel.channel_id}-{n}", channel_pk=channel.id,
                  title=title or f"{channel.title} episode {n}", status="added",
                  duration_sec=duration, published_at=utcnow() - dt.timedelta(hours=n))
    session.add(video)
    session.flush()
    return video


def history(session, liked, passed, count=15):
    """Every liked item clicked open and watched through; every other skipped at once."""
    account = get_settings(session)
    for n in range(count):
        algorithm.record(session, None, item(session, liked, n), account, seconds=500, reached=590,
                         duration=600, pauses=0, clicked=True, skipped=False, finished=True)
        algorithm.record(session, None, item(session, passed, n), account, seconds=2, reached=1,
                         duration=600, pauses=0, clicked=False, skipped=True, finished=False)


def learned(session, signal="interest"):
    account = get_settings(session)
    account.algorithm_min = 10
    return algorithm.train(session, None, account, signal)


# -- what it learns from ---------------------------------------------------------


def test_an_item_is_its_source_kind_tags_words_length_and_hour(db):
    with db.session_scope() as session:
        liked, _ = two_sources(session)
        video = item(session, liked, 1, title="The Ocean Floor, mapped", duration=900)
        video.tags = "science,maps"
        said = algorithm.features(video)
    assert f"source:{liked.id}" in said and "kind:video" in said
    assert {"tag:science", "tag:maps", "word:ocean", "word:floor", "word:mapped"} <= set(said)
    assert "word:the" not in said and "length:10–30 min" in said


def test_each_signal_is_labelled_from_what_focus_mode_saw(db):
    with db.session_scope() as session:
        account = get_settings(session)
        liked, passed = two_sources(session)
        opened = item(session, liked, 1)
        algorithm.record(session, None, opened, account, seconds=300, reached=300, duration=600,
                         pauses=3, clicked=True, skipped=False, finished=False)
        skipped = item(session, passed, 1)
        algorithm.record(session, None, skipped, account, seconds=3, reached=2, duration=600,
                         pauses=0, clicked=False, skipped=True, finished=False)
        # Sat in a feed four days, never opened: not interested, either.
        ignored = item(session, passed, 2)
        feed = playlist_service.create_generic(session, "F")
        session.add(Placement(video_pk=ignored.id, playlist_pk=feed.id, playlist_item_id="g-1",
                              added_at=utcnow() - dt.timedelta(days=4)))
        session.flush()

        interest = {video.id: value for video, value in algorithm.labels(session, None, account, "interest")}
        retention = {video.id: value for video, value in algorithm.labels(session, None, account, "retention")}
        engagement = {video.id: value for video, value in algorithm.labels(session, None, account, "engagement")}

    assert interest == {opened.id: 1.0, skipped.id: 0.0, ignored.id: 0.0}
    assert retention == {opened.id: 0.5}                      # half way through the video
    assert engagement == {opened.id: pytest.approx(0.5 / 2.5)}  # three pauses


def test_with_too_few_items_it_says_nothing(db):
    with db.session_scope() as session:
        liked, passed = two_sources(session)
        history(session, liked, passed, count=3)
        account = get_settings(session)
        assert account.algorithm_min == 20
        assert algorithm.train(session, None, account, "interest") is None


def test_it_learns_which_source_is_wanted(db):
    with db.session_scope() as session:
        liked, passed = two_sources(session)
        history(session, liked, passed)
        model = learned(session)
        assert model is not None and model.examples == 30 and model.quality == 1.0
        fresh_liked, fresh_passed = item(session, liked, 99), item(session, passed, 99)
        assert model.predict(fresh_liked) > 0.8 and model.predict(fresh_passed) < 0.2
        toward, away = algorithm.leanings(model, {liked.id: "Liked Science", passed.id: "Shouty Clips"})
        # Its source, or the word every one of its titles has: equally telling.
        assert "Liked Science" in [one.named for one in toward]
        assert "Shouty Clips" in [one.named for one in away]


# -- the piece, under each box ---------------------------------------------------------


def aggregation_under(session, host, threshold=50, signal="interest"):
    piece = graph.add_piece(session, kind="aggregation", host=host)
    algorithm.save(piece, {"aggregation_signal": signal, "aggregation_threshold": str(threshold)})
    return piece


def test_under_a_filter_it_holds_back_what_it_predicts_below_the_threshold(db):
    from dealgo.services.sync.deciding import decide

    with db.session_scope() as session:
        liked, passed = two_sources(session)
        history(session, liked, passed)
        learned(session)
        middle = graph.add_filter(session)
        aggregation_under(session, middle, threshold=60)
        feed = graph.add_feed(session, playlist_service.create_generic(session, "Feed"))
        for channel in (liked, passed):
            source = graph.add_source(session, channel=channel)
            graph.connect(session, source, middle)
        graph.connect(session, middle, feed)
        routes = {route.channel.id: route for route in graph.routes(session)}
        account = get_settings(session)

        kept = decide(item(session, liked, 50), routes[liked.id], None, account)
        held = decide(item(session, passed, 50), routes[passed.id], None, account)
        assert kept.accept and not held.accept
        assert "the algorithm predicts" in held.reason and "under 60%" in held.reason

        # Switched off — by the account, or by the admin — it holds nothing back.
        account.algorithm_on = False
        assert decide(item(session, passed, 51), routes[passed.id], None, account).accept
        account.algorithm_on = True
        algorithm.set_site_allows(session, False)
        assert decide(item(session, passed, 52), routes[passed.id], None, account).accept


def test_under_a_sort_it_puts_the_most_predicted_first(db):
    from dealgo.services.sync.ordering import reorder

    with db.session_scope() as session:
        liked, passed = two_sources(session)
        history(session, liked, passed)
        learned(session)
        sort = graph.add_sort(session)
        aggregation_under(session, sort)
        feed = graph.add_feed(session, playlist_service.create_generic(session, "Feed"))
        for channel in (liked, passed):
            graph.connect(session, graph.add_source(session, channel=channel), sort)
        graph.connect(session, sort, feed)
        routes: dict[int, list] = {}
        for route in graph.routes(session):
            routes.setdefault(route.channel.id, []).append(route)

        batch = [item(session, passed, 60), item(session, liked, 60), item(session, passed, 61)]
        reorder(batch, routes)
        assert batch[0].channel_pk == liked.id


def test_under_an_expire_box_what_it_predicts_below_leaves_sooner(db):
    from dealgo.services.sync.expiry import life_share

    with db.session_scope() as session:
        liked, passed = two_sources(session)
        history(session, liked, passed)
        learned(session)
        expire = graph.add_stamp(session, kind="expire")
        graph.add_piece(session, kind="timer", host=expire, duration_minutes=1440)
        aggregation_under(session, expire, threshold=50)
        known = graph.pieces_of(session)
        assert life_share(session, item(session, liked, 70), [expire], known) == 1.0
        assert life_share(session, item(session, passed, 70), [expire], known) < 0.5
        assert algorithm.expiry_share(0.001, 50) == algorithm.SHORTEST_LIFE

        piece = next(p for p in known(expire) if p.kind == "aggregation")
        assert algorithm.words(piece, expire) == "under 50% predicted interest leaves sooner"


def test_only_a_filter_sort_or_expire_box_takes_one(db):
    with db.session_scope() as session:
        feed = graph.add_feed(session, playlist_service.create_generic(session, "Feed"))
        with pytest.raises(graph.GraphError):
            graph.add_piece(session, kind="aggregation", host=feed)
        with pytest.raises(ValueError):
            algorithm.save(graph.add_piece(session, kind="aggregation"), {"aggregation_signal": "vibes"})


# -- learning on a run, Focus mode, and the pages ---------------------------------------


def test_a_run_learns_again_when_it_is_due(world, db):
    from dealgo.services import sync as sync_service

    with db.session_scope() as session:
        liked, passed = two_sources(session)
        history(session, liked, passed)
        get_settings(session).algorithm_min = 10
        world["entries"] = []
    sync_service.run_sync("manual", force=True)
    with db.session_scope() as session:
        assert algorithm.learned(session, None, "interest") is not None
        assert not algorithm.due(session, None, get_settings(session))  # daily: done for today


@pytest.fixture
def client(db, monkeypatch):
    from dealgo import scheduler
    from dealgo.web import app as web_app

    monkeypatch.setattr(scheduler, "start", lambda: None)
    monkeypatch.setattr(scheduler, "shutdown", lambda: None)
    monkeypatch.setattr(scheduler, "next_run_time", lambda: None)
    monkeypatch.setattr(web_app, "init_db", lambda: None)
    with TestClient(web_app.app) as test_client:
        yield test_client


def test_focus_mode_says_how_each_item_went(client, db):
    with db.session_scope() as session:
        liked, _ = two_sources(session)
        first, second = item(session, liked, 1), item(session, liked, 2)
        first_pk, second_pk = first.id, second.id

    # Done pressed half way through: done with it, not watched to the end.
    client.post(f"/focus/{first_pk}/finished", data={
        "watched": "1", "seconds": "300", "reached": "300", "duration": "600",
        "pauses": "2", "clicked": "1",
    })
    # The page left with the second still open.
    assert client.post(f"/focus/{second_pk}/seen", data={"seconds": "40", "pauses": "0"}).status_code == 204

    with db.session_scope() as session:
        rows = {row.video_pk: row for row in session.scalars(select(Consumption))}
        assert rows[first_pk].clicked and rows[first_pk].pauses == 2 and not rows[first_pk].finished
        assert rows[second_pk].seconds == 40 and not rows[second_pk].skipped

        # An account that does not want it remembered is not remembered.
        get_settings(session).algorithm_on = False
    client.post(f"/focus/{second_pk}/seen", data={"seconds": "10"})
    with db.session_scope() as session:
        assert len(session.scalars(select(Consumption)).all()) == 2


def test_the_admin_can_switch_algorithms_off(client, db):
    assert "Switch algorithms off for everyone" in client.get("/admin").text
    client.post("/admin/algorithms", data={"allowed": "0"})
    with db.session_scope() as session:
        assert not algorithm.site_allows(session)
    assert "switched algorithms off for this install" in client.get("/settings/ai").text
    client.post("/admin/algorithms", data={"allowed": "1"})
    with db.session_scope() as session:
        assert algorithm.site_allows(session)


def test_the_settings_page_shows_what_it_learned_and_can_forget(client, db):
    with db.session_scope() as session:
        liked, passed = two_sources(session)
        history(session, liked, passed)
    client.post("/settings/ai/algorithm", data={"on": "1", "days": "60", "least": "10", "every": "run"})
    with db.session_scope() as session:
        account = get_settings(session)
        assert (account.algorithm_days, account.algorithm_min, account.algorithm_every) == (60, 10, "run")

    client.post("/settings/ai/algorithm/learn")
    page = client.get("/settings/ai").text
    assert "Leans towards" in page and "Liked Science" in page and "Shouty Clips" in page

    client.post("/settings/ai/algorithm/forget")
    with db.session_scope() as session:
        assert session.scalars(select(Consumption)).all() == []
        assert algorithm.learned(session, None, "interest") is None


def test_the_canvas_says_where_the_algorithm_is(client, db):
    made = client.post("/graph/nodes", data={"kind": "filter"}).json()
    box = next(node for node in made["nodes"] if node["kind"] == "filter")
    answer = client.post("/graph/nodes", data={"kind": "aggregation", "attach_to": str(box["id"])}).json()
    piece = next(node for node in answer["nodes"] if node["kind"] == "aggregation")
    assert piece["note"] == "only what it predicts at 50% interest or more"
    assert "Still learning" in piece["aggregation"]["state"]
    saved = client.post(f"/graph/nodes/{piece['id']}", data={
        "label": "", "aggregation_signal": "retention", "aggregation_threshold": "70",
    }).json()
    assert next(n for n in saved["nodes"] if n["id"] == piece["id"])["note"] == \
        "only what it predicts at 70% retention or more"
