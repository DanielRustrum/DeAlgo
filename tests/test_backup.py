"""The JSON backup: everything needed to rebuild a setup elsewhere."""

from __future__ import annotations

import datetime as dt
import json
from urllib.parse import unquote_plus

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from pamphlets.models import Channel, OAuthToken, Placement, Playlist, Video, utcnow
from pamphlets.services import backup


@pytest.fixture
def populated(db):
    with db.session_scope() as session:
        science = Playlist(playlist_id="PL_sci", title="Science", max_items=40, max_per_run=2)
        music = Playlist(playlist_id="PL_mus", title="Music", enabled=False, priority=1)
        channel = Channel(
            channel_id="UCaaaaaaaaaaaaaaaaaaaaaa",
            title="A Channel",
            min_pull_minutes=360,
            left_out="[]",
            title_exclude="podcast",
            last_checked_at=utcnow(),
        )
        channel.playlists.append(science)
        session.add_all([science, music, channel])
        session.flush()

        video = Video(
            video_id="v1",
            channel_pk=channel.id,
            title="A video",
            published_at=utcnow(),
            status="added",
            watched_at=utcnow(),
        )
        session.add(video)
        session.flush()
        session.add(
            Placement(video_pk=video.id, playlist_pk=science.id, playlist_item_id="item-1")
        )

        settings = db.get_settings(session)
        settings.poll_interval_minutes = 45
        settings.client_id = "client-id"
        settings.client_secret = "secret"
        session.add(OAuthToken(provider="youtube", id=1, access_token="live-token", refresh_token="refresh-token"))
    return db


def export(db) -> dict:
    with db.session_scope() as session:
        return backup.build_export(session)


def legacy_export(db) -> dict:
    """A file as an earlier version wrote it: history, and a client id."""
    from pamphlets.models import Placement, Video

    data = export(db)
    with db.session_scope() as session:
        settings = db.get_settings(session)
        data["credentials"] = {
            # What an old file carried, as it would have said it.
            "client_id": "id-from-an-old-file",
            "client_secret": "secret",
            "api_key": "key-from-an-old-file",
        }
        feeds = {p.id: p.playlist_id for p in session.scalars(select(Playlist))}
        channels = {c.id: c.channel_id for c in session.scalars(select(Channel))}
        data["videos"] = [
            {
                "video_id": v.video_id,
                "channel_id": channels.get(v.channel_pk),
                "title": v.title,
                "published_at": backup._stamp(v.published_at),
                "status": v.status,
                "watched_at": backup._stamp(v.watched_at),
                "placements": [
                    {
                        "playlist_id": feeds.get(p.playlist_pk),
                        "playlist_item_id": p.playlist_item_id,
                        "added_at": None,
                        "removed_at": None,
                    }
                    for p in session.scalars(select(Placement).where(Placement.video_pk == v.id))
                ],
            }
            for v in session.scalars(select(Video))
        ]
    return data


def test_the_setup_comes_out_whole(populated):
    data = export(populated)

    assert data["pamphlets_backup"] == backup.FORMAT_VERSION
    assert data["settings"]["poll_interval_minutes"] == 45
    assert data["counts"] == {"feeds": 2, "channels": 1}

    feed = next(f for f in data["feeds"] if f["playlist_id"] == "PL_sci")
    assert feed["max_items"] == 40 and feed["max_per_run"] == 2
    assert feed["channels"] == ["UCaaaaaaaaaaaaaaaaaaaaaa"]

    channel = data["channels"][0]
    assert channel["min_pull_minutes"] == 360
    assert channel["left_out"] == []
    assert channel["title_exclude"] == "podcast"
    assert channel["feeds"] == ["PL_sci"]


def test_nothing_secret_leaves_the_machine(populated):
    """Neither the sign-in nor the client credentials belong in a file that
    lives in a Downloads folder."""
    blob = json.dumps(export(populated))

    assert "live-token" not in blob
    assert "refresh-token" not in blob
    assert "secret" not in blob
    assert "client-id" not in blob
    assert "credentials" not in blob


def test_the_video_history_is_not_exported(populated):
    """The file is the shape of the setup, not a record of everything seen."""
    data = export(populated)

    assert "videos" not in data
    assert "counts" in data and "videos" not in data["counts"]
    assert data["feeds"] and data["channels"]  # the setup is still complete


def test_rows_reference_youtube_ids_not_row_numbers(populated):
    """Row ids differ between machines; YouTube's ids do not."""
    data = export(populated)

    assert all(f["playlist_id"].startswith("PL") for f in data["feeds"])
    for feed in data["feeds"]:
        for channel_id in feed["channels"]:
            assert channel_id.startswith("UC")


def test_timestamps_say_which_zone_they_are_in(populated):
    data = export(populated)
    assert data["exported_at"].endswith("+00:00")
    assert data["channels"][0]["added_at"].endswith("+00:00")


def test_an_empty_install_still_exports(db):
    data = export(db)
    assert data["counts"] == {"feeds": 0, "channels": 0}
    assert data["settings"]


def test_the_filename_is_dated():
    stamped = backup.filename(dt.datetime(2026, 3, 9, tzinfo=dt.timezone.utc))
    assert stamped == "pamphlets-backup-2026-03-09.json"


@pytest.fixture
def client(populated, monkeypatch):
    from pamphlets import scheduler
    from pamphlets.web import app as web_app

    monkeypatch.setattr(scheduler, "start", lambda: None)
    monkeypatch.setattr(scheduler, "shutdown", lambda: None)
    monkeypatch.setattr(scheduler, "next_run_time", lambda: None)
    monkeypatch.setattr(web_app, "init_db", lambda: None)
    with TestClient(web_app.app) as test_client:
        yield test_client


def test_the_download_is_offered_on_the_settings_page(client):
    body = client.get("/settings").text
    assert 'action="/settings/backup"' in body
    # A boosted request would swap the JSON into the page instead of saving it.
    assert 'hx-boost="false"' in body


def test_the_browser_is_told_to_save_it(client):
    response = client.get("/settings/backup")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    assert "attachment" in response.headers["content-disposition"]
    assert "pamphlets-backup-" in response.headers["content-disposition"]

    data = response.json()
    assert data["counts"]["channels"] == 1
    assert "credentials" not in data


def test_the_panel_offers_no_secret_bearing_options(client):
    """The only choice worth having here is whether to press the button."""
    body = client.get("/settings").text

    assert "Include Google client id" not in body
    assert 'name="credentials"' not in body
    assert 'name="no_history"' not in body
    assert "No credentials are in the file" in body


def test_a_backup_restores_onto_an_empty_install(populated, db):
    """The round trip: export one install, load it into a fresh one."""
    exported = export(populated)

    # A brand new database, sharing nothing but the file.
    from pamphlets.models import Base

    with db.session_scope() as session:
        for table in reversed(Base.metadata.sorted_tables):
            session.execute(table.delete())
    db.init_db()

    with db.session_scope() as session:
        summary = backup.restore(session, exported)

    assert summary.feeds == 2 and summary.channels == 1

    with db.session_scope() as session:
        feed = session.scalar(select(Playlist).where(Playlist.playlist_id == "PL_sci"))
        assert feed.max_items == 40 and feed.max_per_run == 2
        channel = session.scalar(select(Channel))
        assert channel.min_pull_minutes == 360 and channel.title_exclude == "podcast"
        assert [p.playlist_id for p in channel.playlists] == ["PL_sci"]

        assert db.get_settings(session).poll_interval_minutes == 45
        # A setup-only file carries no last-checked time, so the channel counts
        # as never polled and the backfill limit applies on the first sync.
        assert channel.last_checked_at is None


def test_restoring_twice_does_not_duplicate(populated, db):
    exported = export(populated)
    with db.session_scope() as session:
        backup.restore(session, exported)
        backup.restore(session, exported)

    with db.session_scope() as session:
        assert len(list(session.scalars(select(Playlist)))) == 2
        assert len(list(session.scalars(select(Channel)))) == 1
        assert len(list(session.scalars(select(Placement)))) == 1


def test_a_restore_never_brings_back_a_sign_in(populated, db):
    exported = legacy_export(populated)  # even an old file that carried more
    with db.session_scope() as session:
        session.query(OAuthToken).delete()
        backup.restore(session, exported)

    with db.session_scope() as session:
        assert session.get(OAuthToken, 1) is None  # still has to be reconnected


def test_an_older_file_with_history_still_restores(populated, db):
    """Writing narrowed; reading stays forgiving, so files already downloaded
    keep working."""
    exported = legacy_export(populated)

    with db.session_scope() as session:
        summary = backup.restore(session, exported)

    assert summary.videos == 1
    with db.session_scope() as session:
        placement = session.scalar(select(Placement))
        assert placement.playlist_item_id == "item-1"
        # With the videos present, a last-checked time can be trusted.
        assert session.scalar(select(Channel)).last_checked_at is not None

    # Credentials in an old file are not taken: they belong to the plugin's
    # settings for everyone now, set by the admin, never by a restore.
    from pamphlets.services import plugin_settings

    assert plugin_settings.stored("youtube", "app") == {}


def test_a_video_whose_channel_is_missing_is_skipped_not_orphaned(populated, db):
    exported = legacy_export(populated)
    exported["channels"] = []  # a hand-trimmed file

    with db.session_scope() as session:
        summary = backup.restore(session, exported)

    assert summary.videos == 0
    assert summary.skipped == ["v1"]


def test_a_file_that_is_not_a_backup_is_refused(db):
    with db.session_scope() as session:
        for payload in ({}, {"hello": "world"}, [], "text"):
            with pytest.raises(backup.RestoreError):
                backup.restore(session, payload)


def test_a_newer_format_is_refused_rather_than_half_read(db):
    with db.session_scope() as session:
        with pytest.raises(backup.RestoreError) as caught:
            backup.restore(session, {"pamphlets_backup": backup.FORMAT_VERSION + 1})
    assert "reads" in str(caught.value)


def test_the_page_offers_a_load_button(client):
    body = client.get("/settings").text
    assert 'action="/settings/restore"' in body
    assert 'enctype="multipart/form-data"' in body
    assert 'type="file"' in body


def test_uploading_a_backup_through_the_page(client, populated):
    exported = json.dumps(export(populated))

    response = client.post(
        "/settings/restore",
        files={"backup_file": ("backup.json", exported, "application/json")},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert "Restored" in unquote_plus(response.headers["location"])


def test_uploading_rubbish_says_so(client):
    response = client.post(
        "/settings/restore",
        files={"backup_file": ("notes.txt", "just some text", "text/plain")},
        follow_redirects=False,
    )
    assert "not readable JSON" in unquote_plus(response.headers["location"])

    response = client.post(
        "/settings/restore",
        files={"backup_file": ("other.json", '{"some": "json"}', "application/json")},
        follow_redirects=False,
    )
    assert "not a Pamphlets backup" in unquote_plus(response.headers["location"])


def test_a_restored_backup_comes_back_wired(db, tmp_path):
    """A backup carries which feeds each source fills, not the canvas. The
    canvas is drawn from that the first time it is opened — and since a
    source's wire is what routes now, a restore that produced no wires would
    restore a setup that collects nothing."""
    import json

    from pamphlets.models import Channel, GraphEdge, GraphNode, Playlist
    from pamphlets.services import backup as backup_service
    from pamphlets.services import graph as graph_service

    with db.session_scope() as session:
        channel = Channel(channel_id="UCaaaaaaaaaaaaaaaaaaaaaa", title="One", source_kind="youtube")
        feed = Playlist(playlist_id="generic:reading", title="Reading")
        session.add_all([channel, feed])
        session.flush()
        channel.playlists.append(feed)
        saved = json.loads(json.dumps(backup_service.build_export(session)))

    # A fresh database, restored from that file and then opened.
    with db.session_scope() as session:
        for row in session.scalars(select(GraphEdge)):
            session.delete(row)
        for row in session.scalars(select(GraphNode)):
            session.delete(row)
        for row in session.scalars(select(Channel)):
            session.delete(row)
        for row in session.scalars(select(Playlist)):
            session.delete(row)

    with db.session_scope() as session:
        backup_service.restore(session, saved)

    with db.session_scope() as session:
        graph_service.load(session)
        drawn = [(w["from"], w["to"]) for w in graph_service.wires(session)]
        source = session.scalar(select(GraphNode).where(GraphNode.kind == "source"))
        target = session.scalar(select(GraphNode).where(GraphNode.kind == "feed"))

        assert (source.id, target.id) in drawn
