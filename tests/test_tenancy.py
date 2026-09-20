"""Per-account data: the schema half.

The migration is the risky part — it rebuilds a table on a live database — so
these exercise it against a database built the old way rather than a fresh one.
"""

from __future__ import annotations

import sqlite3

from sqlalchemy import select

import pytest

from dealgo.models import Base

# The shape De-Algo had before ownership: `video` carrying a table-level
# UNIQUE(video_id), and uniqueness on channels, feeds and quota days that was
# global rather than per account.
OLD_SCHEMA = """
CREATE TABLE channel (id INTEGER NOT NULL PRIMARY KEY, channel_id VARCHAR(64) NOT NULL,
    title TEXT NOT NULL DEFAULT '', enabled BOOLEAN NOT NULL DEFAULT 1,
    priority INTEGER NOT NULL DEFAULT 0, added_at DATETIME);
CREATE UNIQUE INDEX ix_channel_channel_id ON channel (channel_id);
CREATE TABLE playlist (id INTEGER NOT NULL PRIMARY KEY, playlist_id VARCHAR(64) NOT NULL,
    title VARCHAR(255) NOT NULL DEFAULT '', enabled BOOLEAN NOT NULL DEFAULT 1,
    priority INTEGER NOT NULL DEFAULT 0, added_at DATETIME);
CREATE UNIQUE INDEX ix_playlist_playlist_id ON playlist (playlist_id);
CREATE TABLE video (id INTEGER NOT NULL PRIMARY KEY, video_id VARCHAR(32) NOT NULL,
    channel_pk INTEGER NOT NULL, title TEXT NOT NULL DEFAULT '', status VARCHAR(16) NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0, discovered_at DATETIME NOT NULL,
    playlist_item_id VARCHAR(128),
    CONSTRAINT uq_video_video_id UNIQUE (video_id),
    FOREIGN KEY(channel_pk) REFERENCES channel (id) ON DELETE CASCADE);
CREATE INDEX ix_video_video_id ON video (video_id);
CREATE TABLE placement (id INTEGER NOT NULL PRIMARY KEY, video_pk INTEGER NOT NULL,
    playlist_pk INTEGER NOT NULL, playlist_item_id VARCHAR(128), attempts INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY(video_pk) REFERENCES video (id) ON DELETE CASCADE,
    FOREIGN KEY(playlist_pk) REFERENCES playlist (id) ON DELETE CASCADE);
CREATE TABLE quota_usage (id INTEGER NOT NULL PRIMARY KEY, day VARCHAR(10) NOT NULL,
    units INTEGER NOT NULL DEFAULT 0, updated_at DATETIME);
CREATE UNIQUE INDEX ix_quota_usage_day ON quota_usage (day);
INSERT INTO channel (id, channel_id, title) VALUES (1, 'UCaaa', 'A channel');
INSERT INTO playlist (id, playlist_id, title) VALUES (1, 'PLaaa', 'A feed');
INSERT INTO video (id, video_id, channel_pk, title, status, discovered_at)
    VALUES (1, 'vid1', 1, 'A video', 'added', '2026-01-01 00:00:00');
INSERT INTO placement (id, video_pk, playlist_pk, playlist_item_id) VALUES (1, 1, 1, 'item-1');
"""


@pytest.fixture
def old_database(tmp_path, monkeypatch):
    """A database on the pre-ownership schema, migrated by init_db."""
    from dealgo import config, db as db_module

    path = tmp_path / "old.sqlite3"
    raw = sqlite3.connect(path)
    raw.executescript(OLD_SCHEMA)
    raw.commit()
    raw.close()

    older = config.Config(**{**config.CONFIG.__dict__, "database_url": f"sqlite:///{path}"})
    monkeypatch.setattr(config, "CONFIG", older)
    monkeypatch.setattr(db_module, "CONFIG", older)
    monkeypatch.setattr(db_module, "_engine", None)
    monkeypatch.setattr(db_module, "_SessionFactory", None)

    db_module.init_db()
    return path


def inspect_sql(path, name):
    raw = sqlite3.connect(path)
    try:
        row = raw.execute("select sql from sqlite_master where name = ?", (name,)).fetchone()
        return row[0] if row else ""
    finally:
        raw.close()


def rows(path, table):
    raw = sqlite3.connect(path)
    try:
        return raw.execute(f"select count(*) from {table}").fetchone()[0]
    finally:
        raw.close()


def test_the_migration_keeps_every_row(old_database):
    for table in ("channel", "playlist", "video", "placement"):
        assert rows(old_database, table) == 1, table


def test_uniqueness_follows_the_owner(old_database):
    """Two accounts may track the same channel, so it can no longer be global."""
    for table, column in [("channel", "channel_id"), ("playlist", "playlist_id"),
                          ("video", "video_id"), ("quota_usage", "day")]:
        sql = inspect_sql(old_database, f"uq_{table}_owner_{column}")
        assert "UNIQUE" in sql and "owner_pk" in sql, table
        # COALESCE, because SQL counts NULLs as distinct and the implicit owner
        # would otherwise be allowed duplicates.
        assert "COALESCE" in sql, table


def test_the_old_global_constraint_is_gone(old_database):
    assert "uq_video_video_id" not in inspect_sql(old_database, "video")


def test_the_rebuild_leaves_the_foreign_keys_pointing_at_the_right_table(old_database):
    """The bug this caught on real data: since SQLite 3.25 a RENAME rewrites
    other tables' references to follow it, so `placement` ended up pointing at
    `video_old` and every row was left dangling when that was dropped."""
    assert "REFERENCES video_old" not in inspect_sql(old_database, "placement")

    raw = sqlite3.connect(old_database)
    try:
        assert raw.execute("pragma foreign_key_check").fetchall() == []
        raw.execute("pragma foreign_keys=ON")
        # And a new placement can still be written.
        raw.execute("insert into placement (video_pk, playlist_pk, attempts) values (1, 1, 0)")
    finally:
        raw.close()


def test_migrating_twice_changes_nothing(old_database):
    from dealgo import db as db_module

    db_module.init_db()

    assert rows(old_database, "video") == 1
    assert "uq_video_video_id" not in inspect_sql(old_database, "video")


def test_every_owned_table_carries_an_owner(old_database):
    raw = sqlite3.connect(old_database)
    try:
        for table in ("settings", "oauth_token", "channel", "playlist", "video",
                      "quota_usage", "sync_run"):
            columns = {row[1] for row in raw.execute(f"pragma table_info({table})")}
            assert "owner_pk" in columns, table
    finally:
        raw.close()


def test_a_fresh_database_has_the_same_shape_as_a_migrated_one(tmp_path):
    """create_all and the migration have to agree, or new installs and old
    ones drift apart."""
    fresh = tmp_path / "fresh.sqlite3"
    import sqlalchemy

    engine = sqlalchemy.create_engine(f"sqlite:///{fresh}")
    Base.metadata.create_all(engine)
    engine.dispose()

    assert "uq_video_video_id" not in inspect_sql(fresh, "video")
    assert "COALESCE" in inspect_sql(fresh, "uq_video_owner_video_id")


# -- what each account can see ---------------------------------------------
#
# The point of the exercise: a new account starts with nothing, and never sees
# what another has set up. A missed filter anywhere is one account reading
# another's feeds, so this goes looking rather than sampling.

import pytest
from fastapi.testclient import TestClient

from dealgo.db import get_settings
from dealgo.models import Channel, Placement, Playlist, Video, utcnow
from dealgo.services import accounts

ADMIN = ("admin", "admin")


@pytest.fixture
def two_accounts(db, monkeypatch):
    """An admin with a channel and a feed, and a second account with nothing."""
    from dealgo import config, scheduler
    from dealgo.services import accounts as accounts_module
    from dealgo.web import app as web_app

    secured = config.Config(
        **{**config.CONFIG.__dict__, "admin_user": ADMIN[0], "admin_password": ADMIN[1]}
    )
    for module in (config, web_app, accounts_module):
        monkeypatch.setattr(module, "CONFIG", secured)
    monkeypatch.setattr(scheduler, "start", lambda: None)
    monkeypatch.setattr(scheduler, "shutdown", lambda: None)
    monkeypatch.setattr(scheduler, "next_run_time", lambda: None)
    monkeypatch.setattr(web_app, "init_db", lambda: None)

    with db.session_scope() as session:
        admin = accounts.ensure_admin(session)
        newcomer = accounts.create_user(session, "sam", "member-password")
        admin_pk, sam_pk = admin.id, newcomer.id

        feed = Playlist(playlist_id="PL_admin", title="AdminFeed", owner_pk=admin_pk)
        channel = Channel(channel_id="UCadmin", title="AdminChannel", owner_pk=admin_pk)
        channel.playlists.append(feed)
        session.add_all([feed, channel])
        session.flush()
        video = Video(
            video_id="vid-admin", channel_pk=channel.id, owner_pk=admin_pk,
            title="AdminVideo", status="added", published_at=utcnow(),
        )
        session.add(video)
        session.flush()
        session.add(Placement(video_pk=video.id, playlist_pk=feed.id, playlist_item_id="item-1"))

    with TestClient(web_app.app) as client:
        yield client, admin_pk, sam_pk


def as_account(client, username, password):
    client.post("/logout")
    return client.post("/login", data={"username": username, "password": password},
                       follow_redirects=False)


def test_a_new_account_starts_with_an_empty_configuration(two_accounts):
    """Asked of the canvas's own data rather than the page: the page is a
    blank canvas for everybody, so a leak would not show in its HTML."""
    client, _, _ = two_accounts
    as_account(client, "sam", "member-password")

    assert client.get("/channels").status_code == 200
    drawn = [node["title"] for node in client.get("/api/graph").json()["nodes"]]
    assert drawn == []


def test_a_new_account_starts_with_no_feeds(two_accounts):
    client, _, _ = two_accounts
    as_account(client, "sam", "member-password")

    feed = client.get("/feed").text
    assert "AdminFeed" not in feed
    assert "AdminVideo" not in feed


def test_nor_does_anything_else_leak(two_accounts):
    """Every page that lists something, checked against the same setup."""
    client, _, _ = two_accounts
    as_account(client, "sam", "member-password")

    for path in ["/", "/feed", "/channels", "/videos", "/focus", "/settings", "/tour"]:
        body = client.get(path).text
        assert "AdminChannel" not in body, path
        assert "AdminFeed" not in body, path
        assert "AdminVideo" not in body, path
        assert "UCadmin" not in body, path


def test_the_counts_are_this_accounts_own(two_accounts, db):
    """The one that got through: names were scoped but the numbers beside them
    were not, so a new account opened on somebody else's tally of watched
    videos."""
    from dealgo.models import Video, utcnow
    from dealgo.services import watched as watched_service

    client, admin_pk, sam_pk = two_accounts
    with db.session_scope() as session:
        session.scalar(select(Video).where(Video.owner_pk == admin_pk)).watched_at = utcnow()

    with db.session_scope() as session:
        assert watched_service.count_watched(session, admin_pk) == 1
        assert watched_service.count_watched(session, sam_pk) == 0
        assert watched_service.count_removable(session, sam_pk) == 0

    as_account(client, "sam", "member-password")
    dashboard = client.get("/").text
    marked = dashboard.split("WATCHED", 1)[-1] if "WATCHED" in dashboard else dashboard
    assert ">1</strong> marked" not in marked
    assert ">0</strong>" in marked or "0 marked" in marked or "nothing" in marked.lower()


def test_a_backup_holds_only_your_own(two_accounts):
    """It exports the configuration, so an unscoped one would hand every
    account's feeds to whoever pressed the button."""
    import json

    client, _, _ = two_accounts
    as_account(client, "sam", "member-password")

    export = json.loads(client.get("/settings/backup").text)

    assert export["feeds"] == []
    assert export["channels"] == []


def test_watched_marks_cannot_reach_across(two_accounts, db):
    """An id from another account is not this one's to mark, however it got
    into the request."""
    from dealgo.models import Video

    client, admin_pk, _ = two_accounts
    with db.session_scope() as session:
        theirs = session.scalar(select(Video).where(Video.owner_pk == admin_pk)).id

    as_account(client, "sam", "member-password")
    client.post(f"/videos/{theirs}/watched", data={"view": "feed"})

    with db.session_scope() as session:
        assert session.get(Video, theirs).watched_at is None


def test_the_owner_still_sees_their_own(two_accounts):
    """Isolation is not the same as hiding everything."""
    client, _, _ = two_accounts
    as_account(client, *ADMIN)

    drawn = [node["title"] for node in client.get("/api/graph").json()["nodes"]]
    assert "AdminChannel" in drawn and "AdminFeed" in drawn
    assert "AdminFeed" in client.get("/feed").text


def test_what_one_account_adds_belongs_to_it(two_accounts, db):
    client, admin_pk, sam_pk = two_accounts
    as_account(client, "sam", "member-password")

    client.post("/settings/feeds/new", data={"source": "generic", "generic_title": "SamFeed"})

    with db.session_scope() as session:
        made = session.scalar(select(Playlist).where(Playlist.title == "SamFeed"))
        assert made is not None
        assert made.owner_pk == sam_pk

    # And the admin cannot see it.
    as_account(client, *ADMIN)
    assert "SamFeed" not in client.get("/feed").text


def test_two_accounts_may_track_the_same_channel(db):
    """Which is why uniqueness had to stop being global."""
    with db.session_scope() as session:
        first = accounts.create_user(session, "one", "password-one")
        second = accounts.create_user(session, "two", "password-two")
        session.add_all([
            Channel(channel_id="UCshared", title="Shared", owner_pk=first.id),
            Channel(channel_id="UCshared", title="Shared", owner_pk=second.id),
        ])
        session.flush()

        assert len(list(session.scalars(select(Channel).where(Channel.channel_id == "UCshared")))) == 2


def test_settings_are_each_accounts_own(two_accounts, db):
    client, admin_pk, sam_pk = two_accounts

    with db.session_scope() as session:
        get_settings(session, admin_pk).poll_interval_minutes = 5
        get_settings(session, sam_pk).poll_interval_minutes = 90

    as_account(client, "sam", "member-password")
    assert 'value="90"' in client.get("/settings").text

    as_account(client, *ADMIN)
    assert 'value="5"' in client.get("/settings").text


def test_turning_sign_in_on_hands_the_existing_setup_to_the_admin(db, monkeypatch):
    """Upgrading an instance that already had channels and feeds: they belong
    to the implicit owner, which is nobody once there are accounts. Without
    this the admin signs in to an empty De-Algo and the data sits invisible."""
    from dealgo import config
    from dealgo.services import accounts as accounts_module

    with db.session_scope() as session:
        session.add_all([
            Playlist(playlist_id="PLold", title="OldFeed"),        # owner_pk NULL
            Channel(channel_id="UCold", title="OldChannel"),
        ])

    secured = config.Config(
        **{**config.CONFIG.__dict__, "admin_user": "admin", "admin_password": "admin"}
    )
    monkeypatch.setattr(accounts_module, "CONFIG", secured)

    with db.session_scope() as session:
        admin = accounts.ensure_admin(session)
        admin_pk = admin.id

    with db.session_scope() as session:
        feed = session.scalar(select(Playlist).where(Playlist.title == "OldFeed"))
        channel = session.scalar(select(Channel).where(Channel.title == "OldChannel"))
        assert feed.owner_pk == admin_pk
        assert channel.owner_pk == admin_pk


def test_adoption_leaves_other_accounts_alone(db, monkeypatch):
    from dealgo import config
    from dealgo.services import accounts as accounts_module

    with db.session_scope() as session:
        sam = accounts.create_user(session, "sam", "member-password")
        session.add(Playlist(playlist_id="PLsam", title="SamOwn", owner_pk=sam.id))
        sam_pk = sam.id

    secured = config.Config(
        **{**config.CONFIG.__dict__, "admin_user": "admin", "admin_password": "admin"}
    )
    monkeypatch.setattr(accounts_module, "CONFIG", secured)

    with db.session_scope() as session:
        accounts.ensure_admin(session)

    with db.session_scope() as session:
        kept = session.scalar(select(Playlist).where(Playlist.title == "SamOwn"))
        assert kept.owner_pk == sam_pk


# -- the canvas ------------------------------------------------------------
#
# The graph is a listing like any other, and its routes take node ids straight
# off the wire. An id is a guess away, so each one is asked whose box it is.


def test_the_canvas_only_draws_your_own(two_accounts):
    client, _, _ = two_accounts
    as_account(client, "sam", "member-password")

    payload = client.get("/api/graph").json()
    assert [node["title"] for node in payload["nodes"]] == []
    assert payload["wires"] == []


def test_another_accounts_box_cannot_be_moved(two_accounts):
    client, _, _ = two_accounts
    as_account(client, *ADMIN)
    admin_nodes = client.get("/api/graph").json()["nodes"]
    assert admin_nodes, "the admin's setup should have drawn itself"
    theirs = admin_nodes[0]

    as_account(client, "sam", "member-password")
    assert client.post(f"/graph/nodes/{theirs['id']}/move", data={"x": 5, "y": 5}).json() == {
        "moved": False
    }


def test_another_accounts_boxes_cannot_be_wired_together(two_accounts):
    client, _, _ = two_accounts
    as_account(client, *ADMIN)
    admin_nodes = client.get("/api/graph").json()["nodes"]
    source = next(node for node in admin_nodes if node["kind"] == "source")
    feed = next(node for node in admin_nodes if node["kind"] == "feed")

    as_account(client, "sam", "member-password")
    refused = client.post("/graph/connect", data={"source": source["id"], "target": feed["id"]})
    assert refused.status_code == 404

    assert client.post(f"/graph/nodes/{source['id']}/delete").status_code == 404
    assert client.post(f"/graph/nodes/{source['id']}", data={"label": "mine now"}).status_code == 404


def test_another_accounts_wire_cannot_be_cut(two_accounts):
    client, _, _ = two_accounts
    as_account(client, *ADMIN)
    wires = client.get("/api/graph").json()["wires"]
    assert len(wires) == 1, "the admin's channel feeds the admin's playlist"

    as_account(client, "sam", "member-password")
    client.post("/graph/disconnect", data={"wire": wires[0]["id"]})

    as_account(client, *ADMIN)
    assert len(client.get("/api/graph").json()["wires"]) == 1


def test_another_accounts_trigger_cannot_be_pressed(two_accounts):
    """A pulse polls channels. Pressing somebody else's would be reaching into
    their account to make it fetch."""
    client, _, _ = two_accounts
    as_account(client, *ADMIN)
    added = client.post("/graph/nodes", data={"kind": "pulse"}).json()
    theirs = next(node for node in added["nodes"] if node["kind"] == "trigger")
    source = next(node for node in added["nodes"] if node["kind"] == "source")
    client.post("/graph/connect", data={"source": theirs["id"], "target": source["id"]})

    as_account(client, "sam", "member-password")
    assert client.post(f"/graph/nodes/{theirs['id']}/fire").status_code == 400
    assert client.post(f"/graph/nodes/{theirs['id']}/delete").status_code == 404


def test_a_new_accounts_canvas_has_no_triggers_either(two_accounts):
    client, _, _ = two_accounts
    as_account(client, *ADMIN)
    client.post("/graph/nodes", data={"kind": "schedule"})

    as_account(client, "sam", "member-password")
    assert client.get("/api/graph").json()["nodes"] == []


def test_another_accounts_run_is_not_reported(two_accounts, db):
    """The run state names boxes and counts. Reporting one account's run to
    another would say which channels they watch and how much each brought in."""
    from dealgo.services import sync as sync_service

    client, admin_pk, _ = two_accounts
    as_account(client, *ADMIN)
    client.get("/api/graph")  # the admin's boxes exist

    with db.session_scope() as session:
        channel_pk = session.scalar(select(Channel.id).where(Channel.owner_pk == admin_pk))
    sync_service.claim(admin_pk, "pulse")
    sync_service._note(stage="polling", channel_pk=channel_pk)

    as_account(client, "sam", "member-password")
    answer = client.get("/api/graph/run").json()
    assert answer["nodes"] == {}
    assert answer["stage"] is None


def test_another_accounts_filter_cannot_be_read(two_accounts):
    client, _, _ = two_accounts
    as_account(client, *ADMIN)
    added = client.post("/graph/nodes", data={"kind": "filter"}).json()
    theirs = next(node for node in added["nodes"] if node["kind"] == "filter")

    as_account(client, "sam", "member-password")
    assert client.get(f"/graph/nodes/{theirs['id']}/filtered").status_code == 400


def test_another_accounts_group_cannot_be_taken(two_accounts):
    """A group file is a piece of somebody's setup — the channels they watch
    and what they do with them. Exporting one is theirs to do."""
    client, _, _ = two_accounts
    as_account(client, *ADMIN)
    added = client.post("/graph/nodes", data={"kind": "group"}).json()
    theirs = next(node for node in added["nodes"] if node["kind"] == "group")

    as_account(client, "sam", "member-password")
    assert client.get(f"/graph/nodes/{theirs['id']}/export").status_code == 400
    assert client.post(
        f"/graph/nodes/{theirs['id']}/move", data={"x": 5, "y": 5, "carries": "1"}
    ).status_code == 400
    assert client.post(
        f"/graph/nodes/{theirs['id']}/resize", data={"width": 900, "height": 900}
    ).json() == {"resized": False}


def test_a_loaded_group_belongs_to_whoever_loaded_it(two_accounts, db):
    import json as json_module

    from dealgo.models import Channel as ChannelModel

    client, _, sam_pk = two_accounts
    as_account(client, "sam", "member-password")

    packed = {
        "de_algo_group": 1,
        "name": "A gift",
        "nodes": [{"ref": 0, "kind": "source", "x": 0, "y": 0,
                   "channel_id": "UCgifted", "title": "A gift"}],
        "wires": [],
    }
    client.post(
        "/graph/groups",
        files={"file": ("group.json", json_module.dumps(packed), "application/json")},
    )

    with db.session_scope() as session:
        gifted = session.scalar(
            select(ChannelModel).where(ChannelModel.channel_id == "UCgifted")
        )
        assert gifted is not None and gifted.owner_pk == sam_pk


def test_sources_and_their_tags_are_each_accounts_own(two_accounts, db):
    """A tag is a label on somebody's channels, and a tag node pulls from
    whatever carries it — so a leak here would put another account's channels
    into this one's feeds."""
    client, _, _ = two_accounts
    as_account(client, *ADMIN)
    client.post("/sources/1/tags", data={"tags": "news"})

    as_account(client, "sam", "member-password")
    body = client.get("/sources").text
    assert "AdminChannel" not in body

    # And their tag node stands for nothing of the admin's.
    added = client.post("/graph/nodes", data={"kind": "tagged", "title": "news"}).json()
    tagged = [node for node in added["nodes"] if node["tag"] is not None][0]
    assert tagged["tag"]["channels"] == []
    assert tagged["tag"]["known"] == []

    # Nor can they tag one of the admin's.
    assert client.post("/sources/1/tags", data={"tags": "mine"},
                       follow_redirects=False).headers["location"].count("err=") == 1


def test_the_source_picker_only_offers_your_own(two_accounts):
    """It is a list of channels to point a node at, so another account's in it
    would be another account's channel in this one's feeds."""
    client, _, _ = two_accounts
    as_account(client, "sam", "member-password")

    assert client.get("/api/graph").json()["sources"] == []

    added = client.post("/graph/nodes", data={"kind": "source", "source_kind": "reddit"}).json()
    empty = [node for node in added["nodes"] if node["kind"] == "source"][0]
    refused = client.post(f"/graph/nodes/{empty['id']}", data={"source_pk": "1"})
    assert refused.status_code == 400
