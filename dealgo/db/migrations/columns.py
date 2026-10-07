"""Columns added and removed since the first release."""

from __future__ import annotations

import logging

from sqlalchemy import inspect, text

from ..engine import get_engine

log = logging.getLogger(__name__)


# Columns added after the first release. ``create_all`` only makes missing
# tables, so an existing database needs them added by hand; each is nullable or
# defaulted, which is what makes a plain ADD COLUMN safe.
_ADDED_COLUMNS: tuple[tuple[str, str, str], ...] = (
    # What a source's plugin said about an item when it was read.
    ("video", "hint", "VARCHAR(16)"),
    ("video", "watched_at", "DATETIME"),
    ("sync_run", "removed", "INTEGER NOT NULL DEFAULT 0"),
    ("oauth_token", "refresh_error", "TEXT"),
    # Which plugin's service a grant is for. Every earlier one was YouTube's,
    # which youtube_becomes_a_plugin fills in.
    ("oauth_token", "provider", "VARCHAR(64) NOT NULL DEFAULT ''"),
    ("channel", "priority", "INTEGER NOT NULL DEFAULT 0"),
    ("channel", "min_pull_minutes", "INTEGER NOT NULL DEFAULT 0"),
    ("channel", "backfill_days", "INTEGER"),
    # Which of its plugin's kinds of content a source leaves out.
    ("channel", "left_out", "TEXT"),
    ("channel", "description", "TEXT"),
    ("video", "kind", "VARCHAR(8) NOT NULL DEFAULT 'video'"),
    ("video", "body", "TEXT"),
    ("video", "images", "TEXT"),
    ("settings", "post_seconds", "INTEGER NOT NULL DEFAULT 30"),
    ("playlist", "priority", "INTEGER NOT NULL DEFAULT 0"),
    ("playlist", "max_per_run", "INTEGER NOT NULL DEFAULT 0"),
    ("playlist", "tags", "TEXT"),
    ("playlist", "view_order", "VARCHAR(8) NOT NULL DEFAULT 'oldest'"),
    ("playlist", "view_show", "VARCHAR(10) NOT NULL DEFAULT 'unwatched'"),
    # How the account arranges its feeds on the Feed page.
    ("playlist", "favorite", "BOOLEAN NOT NULL DEFAULT 0"),
    ("playlist", "shelf_position", "INTEGER NOT NULL DEFAULT 0"),
    ("sync_run", "forced", "BOOLEAN NOT NULL DEFAULT 0"),
    ("sync_run", "quota_spent", "INTEGER NOT NULL DEFAULT 0"),
    ("sync_run", "stopped_on_quota", "BOOLEAN NOT NULL DEFAULT 0"),
    # Trigger boxes on the canvas. All nullable: every node that came before
    # them is a source, feed or filter, and none of these mean anything there.
    ("graph_node", "trigger_kind", "VARCHAR(10)"),
    ("graph_node", "every_minutes", "INTEGER"),
    ("graph_node", "cron", "VARCHAR(120)"),
    ("graph_node", "enabled", "BOOLEAN NOT NULL DEFAULT 1"),
    ("channel", "tags", "TEXT"),
    ("graph_node", "tag", "VARCHAR(40)"),
    ("graph_node", "duration_minutes", "INTEGER"),
    ("graph_node", "width", "INTEGER"),
    ("graph_node", "height", "INTEGER"),
    ("graph_node", "locked", "BOOLEAN NOT NULL DEFAULT 0"),
    # Group files: which part of one a box is, and where a group came from.
    ("graph_node", "group_key", "VARCHAR(40)"),
    # How long after it is watched a placement leaves its feed.
    ("placement", "expires_after_watch_minutes", "INTEGER"),
    # A REST API source's mapping and header.
    ("channel", "source_options", "TEXT"),
    ("graph_node", "imported_from", "VARCHAR(255)"),
    ("graph_node", "imported_at", "DATETIME"),
    ("graph_node", "sort_by", "VARCHAR(16)"),
    ("graph_node", "sort_dir", "VARCHAR(4)"),
    # Counts, so a sort box can order by them. Backfilled as the details are
    # next fetched; NULL until then, which the ordering treats as unknown.
    ("video", "view_count", "INTEGER"),
    ("video", "like_count", "INTEGER"),
    ("graph_node", "last_fired_at", "DATETIME"),
    # Ownership. Nullable, so every existing row becomes the implicit
    # owner's — which is exactly what it was before accounts existed.
    ("settings", "owner_pk", "INTEGER REFERENCES user(id) ON DELETE CASCADE"),
    ("oauth_token", "owner_pk", "INTEGER REFERENCES user(id) ON DELETE CASCADE"),
    ("channel", "owner_pk", "INTEGER REFERENCES user(id) ON DELETE CASCADE"),
    ("playlist", "owner_pk", "INTEGER REFERENCES user(id) ON DELETE CASCADE"),
    ("video", "owner_pk", "INTEGER REFERENCES user(id) ON DELETE CASCADE"),
    ("sync_run", "owner_pk", "INTEGER REFERENCES user(id) ON DELETE CASCADE"),
    # Sources that are not YouTube. Every row that existed before these is
    # YouTube, which is what the default says: an upgrade must not quietly
    # turn a channel into something else. `link` is where an item from
    # elsewhere lives, since only YouTube's are addressed by an id.
    ("channel", "source_kind", "VARCHAR(12) NOT NULL DEFAULT 'youtube'"),
    ("channel", "source_url", "TEXT"),
    ("video", "link", "TEXT"),
    # Where else the same feed can be read, when the first place refuses us.
    ("channel", "mirror_url", "TEXT"),
    # Boxes a plugin put in the palette: which one, and what its fields say.
    ("graph_node", "plugin_ref", "VARCHAR(80)"),
    ("graph_node", "plugin_settings", "TEXT"),
    # Which kind of somewhere a source box is for. Nullable: every source box
    # that came before this was the one generic kind, and an empty one of
    # those can still be pointed at something already watched.
    ("graph_node", "source_kind", "VARCHAR(24)"),
    # Deposit and Withdraw boxes: which repository, and how much a withdrawal
    # takes. Nullable, because every box drawn before them is neither.
    ("graph_node", "repository", "VARCHAR(60)"),
    ("graph_node", "takes", "INTEGER"),
    # Which box an augmentation is slotted under. Added without the foreign
    # key an ALTER cannot carry: the constraint is on the table SQLAlchemy
    # creates from scratch, and a column added to an existing one goes in
    # plain. Nothing reads it but the walk up a chain, which checks anyway.
    ("graph_node", "attached_to", "INTEGER"),
    # The two ends of an Alive piece's stretch of the day.
    ("graph_node", "alive_from", "VARCHAR(5)"),
    ("graph_node", "alive_to", "VARCHAR(5)"),
    # What the boxes on an item's way marked it with, and when a placement
    # made under an Expire box stops counting.
    ("video", "tags", "TEXT"),
    ("video", "view_seconds", "INTEGER"),
    ("video", "view_locked", "BOOLEAN NOT NULL DEFAULT 0"),
    ("placement", "expires_at", "DATETIME"),
    # A Filter box can narrow on a tag a Tag box put on.
    ("graph_node", "tagged", "VARCHAR(40)"),
    ("graph_node", "untagged", "VARCHAR(400)"),
    # Leaflets: which edge they hang from, and what each shows.
    ("graph_node", "attached_side", "VARCHAR(8)"),
    ("graph_node", "leaflet", "TEXT"),
    ("settings", "default_pamphlet_pk", "INTEGER"),
    # What a Tag box marks whatever comes through it with.
    ("graph_node", "marks", "VARCHAR(40)"),
    # What a person granted each plugin. plugin_state may already exist from
    # before permissions did, so this is a column rather than part of the
    # table's creation.
    ("plugin_state", "granted", "TEXT"),
    # Where a plugin was fetched from, so it can be fetched again. Here
    # rather than in its folder because it is a record of what this install
    # did, not part of the plugin — one that could write its own origin
    # could point an update at somewhere else entirely.
    ("plugin_state", "origin", "TEXT"),
    ("plugin_state", "origin_ref", "VARCHAR(120)"),
    ("plugin_state", "fetched_at", "DATETIME"),
)

# run_event is a new table rather than new columns, so it needs no entry here:
# create_all makes it, and an install that predates it simply has no history
# from before it existed.


# Columns removed after the first release. An existing table still has them,
# and they are NOT NULL with no SQL default, so leaving them would break every
# insert once the model stops supplying a value.
_DROPPED_COLUMNS: tuple[tuple[str, str], ...] = (
    ("playlist", "default_target"),
    # From before feeds could be fanned out. They are NOT NULL with no SQL
    # default, so they were harmless only while `settings` held exactly one
    # row that already had them — the moment a second account needed a row of
    # its own, the insert failed and the app would not start.
    ("settings", "max_playlist_items"),
    ("settings", "playlist_id"),
    ("settings", "playlist_title"),
    # The tag node, and the Sources page that set what it matched on. A
    # source box names one source now, and the way to follow a kind of thing
    # is the plugin that understands it. Feed tags are a different feature
    # and are untouched.
    ("channel", "tags"),
    ("graph_node", "tag"),
    # The four content switches, which were never general: a Short, a
    # premiere and a community post are YouTube's own distinctions. They are
    # YouTube conditions now, slotted under a YouTube box. A channel still
    # has its own four — that is what it takes from the source at all, which
    # is a different question from what one path narrows to.
    ("graph_node", "skip_videos"),
    ("graph_node", "skip_shorts"),
    ("graph_node", "skip_live"),
    ("graph_node", "skip_posts"),
    # Google's credentials and quota, which are the YouTube plugin's settings
    # for everyone now. youtube_becomes_a_plugin carries them across first.
    ("settings", "client_id"),
    ("settings", "client_secret"),
    ("settings", "api_key"),
    ("settings", "daily_quota"),
    ("settings", "quota_reserve"),
    # YouTube's four kinds of content, its Short marker and what counts as
    # a Short: the YouTube plugin's `takes`, `hint` and a user setting now.
    # youtube_takes_become_declared carries them across first.
    ("channel", "skip_videos"),
    ("channel", "skip_shorts"),
    ("channel", "skip_live"),
    ("channel", "skip_posts"),
    ("video", "is_short"),
    ("settings", "shorts_max_seconds"),
    # The Tour, and the switches that hid the standing notices.
    ("settings", "hide_tour"),
    ("settings", "hide_open_notice"),
    ("settings", "hide_connect_notice"),
)


def drop_removed_columns() -> None:
    """Drop each column in `_DROPPED_COLUMNS` that a table still has."""
    engine = get_engine()
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    with engine.begin() as connection:
        for table, column in _DROPPED_COLUMNS:
            if table not in tables:
                continue
            if column not in {c["name"] for c in inspector.get_columns(table)}:
                continue
            connection.execute(text(f"ALTER TABLE {table} DROP COLUMN {column}"))
            log.info("dropped unused column %s.%s", table, column)


def add_missing_columns() -> None:
    """Add each column in `_ADDED_COLUMNS` that a table does not have yet."""
    engine = get_engine()
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    with engine.begin() as connection:
        for table, column, definition in _ADDED_COLUMNS:
            if table not in tables:
                continue
            existing = {c["name"] for c in inspector.get_columns(table)}
            if column in existing:
                continue
            connection.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {definition}"))
            log.info("added column %s.%s to an existing database", table, column)
