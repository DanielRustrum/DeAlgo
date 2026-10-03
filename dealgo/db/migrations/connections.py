"""YouTube's sign-in, credentials and quota, from the app into its plugin.

They were the app's: a Google client id, secret and API key on each
account's settings (or in DEALGO_CLIENT_ID and friends), a Google grant per
account, and a quota ledger per account. They belong to the YouTube plugin
now — its settings for everyone, its sign-in, its allowance — so whatever an
existing install had is carried across once, and the old places go.
"""

from __future__ import annotations

import logging
import os

from sqlalchemy import inspect, text

from ..engine import get_engine

log = logging.getLogger(__name__)

#: The plugin they move to. The one place outside that plugin that names it,
#: because this is about data an earlier version stored on its behalf.
YOUTUBE = "youtube"

#: Old settings columns, and the YouTube setting each becomes.
_SETTINGS = (
    ("client_id", "client_id"),
    ("client_secret", "client_secret"),
    ("api_key", "api_key"),
    ("daily_quota", "daily_quota"),
    ("quota_reserve", "quota_reserve"),
)

#: The defaults an old row held without anybody choosing them; not worth
#: carrying, since the plugin's own defaults say the same.
_DEFAULTS = {"daily_quota": "10000", "quota_reserve": "0"}

#: The environment variables that used to hold the credentials.
_ENVIRONMENT = (
    ("DEALGO_CLIENT_ID", "client_id"),
    ("DEALGO_CLIENT_SECRET", "client_secret"),
    ("DEALGO_API_KEY", "api_key"),
)


def youtube_becomes_a_plugin() -> None:
    """Carry an existing install's Google state into the YouTube plugin."""
    engine = get_engine()
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    with engine.begin() as connection:
        saved = {
            row[0]
            for row in connection.execute(
                text("SELECT key FROM plugin_app_setting WHERE key LIKE :prefix"),
                {"prefix": f"{YOUTUBE}:%"},
            )
        }

        def keep(name: str, value: str, came_from: str) -> None:
            key = f"{YOUTUBE}:{name}"
            if not value or key in saved:
                return
            connection.execute(
                text("INSERT INTO plugin_app_setting (key, value, updated_at)"
                     " VALUES (:key, :value, CURRENT_TIMESTAMP)"),
                {"key": key, "value": value},
            )
            saved.add(key)
            log.info("moved %s from %s to the YouTube plugin's settings", name, came_from)

        # The credentials were per account; they are one for the install now.
        # The implicit owner's first, then the oldest account's that has any.
        if "settings" in tables:
            columns = {c["name"] for c in inspector.get_columns("settings")}
            for old, name in _SETTINGS:
                if old not in columns:
                    continue
                row = connection.execute(
                    text(f"SELECT {old} FROM settings WHERE {old} IS NOT NULL AND {old} != ''"
                         " ORDER BY owner_pk IS NOT NULL, id LIMIT 1")
                ).first()
                value = "" if row is None else str(row[0]).strip()
                if _DEFAULTS.get(name) == value:
                    continue
                keep(name, value, "Settings")

        # The environment can no longer name them the old way. Carried once,
        # so an install configured only by environment keeps working; said in
        # the log, so it can be moved to the new names.
        for variable, name in _ENVIRONMENT:
            value = os.environ.get(variable, "").strip()
            if value:
                keep(name, value, variable)
                log.warning(
                    "%s is no longer read. Its value was saved to the YouTube plugin's "
                    "settings; set DEALGO_PLUGIN_YOUTUBE_%s instead, or change it on the "
                    "plugin's card under Admin → Plugins.", variable, name.upper(),
                )

        # Every grant so far was a Google one.
        if "oauth_token" in tables:
            columns = {c["name"] for c in inspector.get_columns("oauth_token")}
            if "provider" in columns:
                connection.execute(
                    text("UPDATE oauth_token SET provider = :youtube WHERE provider = ''"),
                    {"youtube": YOUTUBE},
                )

        # The per-account ledgers become the install's: one Google project,
        # one allowance. The busiest account's count is the closest to true.
        if "quota_usage" in tables:
            # The oldest ledgers predate marking a day exhausted.
            had = {c["name"] for c in inspector.get_columns("quota_usage")}
            exhausted = "MAX(exhausted_at)" if "exhausted_at" in had else "NULL"
            connection.execute(
                text("INSERT INTO allowance_usage (provider, day, units, exhausted_at, updated_at)"
                     f" SELECT :youtube, day, MAX(units), {exhausted}, CURRENT_TIMESTAMP"
                     " FROM quota_usage WHERE day NOT IN"
                     " (SELECT day FROM allowance_usage WHERE provider = :youtube)"
                     " GROUP BY day"),
                {"youtube": YOUTUBE},
            )
            connection.execute(text("DROP TABLE quota_usage"))
            log.info("moved the quota ledger to the YouTube plugin's allowance")


#: YouTube's old switches, and the name of the kind each one leaves out.
_SWITCHES = (
    ("skip_videos", "videos"),
    ("skip_shorts", "shorts"),
    ("skip_live", "live"),
    ("skip_posts", "posts"),
)

#: What a skipped item's reason said, and what the YouTube plugin's `takes`
#: call that kind now — so switching a kind back on still finds what it held.
_REASONS = (
    ("reason GLOB 'Short' OR reason GLOB 'Short (*'", "Shorts"),
    ("reason IN ('live stream', 'scheduled premiere')", "Live"),
    ("reason = 'regular video'", "Videos"),
    ("reason = 'community post'", "Posts"),
    ("reason = 'not a YouTube video, and that feed is a YouTube playlist'",
     "not something that feed's playlist can hold"),
)


def youtube_takes_become_declared() -> None:
    """Carry YouTube's four kinds of content into its plugin's `takes`.

    A channel had four switch columns, an item a Short flag, and every
    account a "what counts as a Short" figure. The YouTube plugin declares
    the kinds now, says which an item is, and keeps the figure as a user
    setting; this moves what an existing install had into that shape.
    """
    import json

    engine = get_engine()
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    with engine.begin() as connection:
        if "channel" in tables:
            had = {c["name"] for c in inspector.get_columns("channel")}
            present = [(column, name) for column, name in _SWITCHES if column in had]
            if present and "left_out" in had:
                picked = ", ".join(column for column, _ in present)
                rows = connection.execute(text(
                    f"SELECT id, {picked} FROM channel"
                    f" WHERE source_kind = :youtube AND left_out IS NULL"
                ), {"youtube": YOUTUBE}).all()
                for row in rows:
                    names = [name for (_, name), on in zip(present, row[1:]) if on]
                    connection.execute(
                        text("UPDATE channel SET left_out = :names WHERE id = :id"),
                        {"names": json.dumps(names), "id": row[0]},
                    )

        if "video" in tables:
            had = {c["name"] for c in inspector.get_columns("video")}
            if "is_short" in had and "hint" in had:
                connection.execute(text(
                    "UPDATE video SET hint = 'shorts' WHERE is_short = 1 AND hint IS NULL"
                ))
            for condition, now in _REASONS:
                connection.execute(
                    text(f"UPDATE video SET reason = :now WHERE {condition}"), {"now": now}
                )

        # What counted as a Short was each account's own: a user setting.
        if "settings" in tables and "plugin_user_setting" in tables:
            had = {c["name"] for c in inspector.get_columns("settings")}
            if "shorts_max_seconds" in had:
                key = f"{YOUTUBE}:shorts_max_seconds"
                rows = connection.execute(text(
                    "SELECT owner_pk, shorts_max_seconds FROM settings"
                    " WHERE shorts_max_seconds IS NOT NULL AND shorts_max_seconds != 60"
                    " ORDER BY id"
                )).all()
                for owner, seconds in rows:
                    exists = connection.execute(text(
                        "SELECT 1 FROM plugin_user_setting WHERE key = :key"
                        " AND COALESCE(owner_pk, 0) = COALESCE(:owner, 0)"
                    ), {"key": key, "owner": owner}).first()
                    if exists is None:
                        connection.execute(text(
                            "INSERT INTO plugin_user_setting (owner_pk, key, value, updated_at)"
                            " VALUES (:owner, :key, :value, CURRENT_TIMESTAMP)"
                        ), {"owner": owner, "key": key, "value": str(seconds)})
