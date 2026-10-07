"""What runs on every start: bring the schema up to date, then the rows it needs."""

from __future__ import annotations

from ..models import Base
from .engine import get_engine, session_scope
from .migrations import (
    after_watching_is_its_own_condition,
    leaflets_are_wired_to_their_feeds,
    add_missing_columns,
    drop_removed_columns,
    feed_windows_become_pieces,
    migrate_single_playlist,
    plugin_boxes_become_pieces,
    rebuild_video_uniqueness,
    rename_local_feed_prefix,
    retire_tag_nodes,
    rules_become_pieces,
    scope_uniqueness_to_owners,
    wires_belong_to_boxes,
    youtube_becomes_a_plugin,
    youtube_takes_become_declared,
)


def init_db() -> None:
    """Bring the database up to date, then make sure of the admin account.

    Safe on every start: each migration step does nothing once it has been done. Order matters —
    the column drops come last because earlier steps read those columns.
    """
    Base.metadata.create_all(get_engine())
    add_missing_columns()
    rebuild_video_uniqueness()
    scope_uniqueness_to_owners()
    rename_local_feed_prefix()
    migrate_single_playlist()
    retire_tag_nodes()
    wires_belong_to_boxes()
    feed_windows_become_pieces()
    plugin_boxes_become_pieces()
    rules_become_pieces()
    youtube_becomes_a_plugin()
    youtube_takes_become_declared()
    after_watching_is_its_own_condition()
    leaflets_are_wired_to_their_feeds()
    # After the migrations above, not before: they read columns this drops,
    # and they are the last things that need them.
    drop_removed_columns()

    # The admin account is the environment's, so it is reconciled on every
    # start rather than only when the database is first made. Imported here
    # rather than at the top: accounts reads the models this module defines.
    # Items filed before anything looked at a feed's markup for pictures kept
    # the address in their words instead. Reading it back out needs no
    # network, and reaches items the feed has long since stopped listing.
    from ..services import accounts, sync

    with session_scope() as session:
        accounts.ensure_admin(session)
        accounts.clear_expired(session)
        sync.repair_stored_pictures(session)
