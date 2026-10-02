"""Settings that lived on boxes, turned into the pieces slotted under them."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import inspect, text

from ..engine import get_engine

log = logging.getLogger(__name__)


def feed_windows_become_pieces() -> None:
    """Turn a trigger wired to a feed into the pieces that say the same thing.

    A feed used to take a trigger on a second input to say when it could be
    read. That is a Reset and a Timer slotted under it now — when it opens,
    and how long for — so the wire is unpicked into the two pieces it was
    carrying rather than dropped along with what somebody set up.

    A pulse said "this long, this often" with no clock time to anchor it, and
    there is no cron that means the same. It becomes a Timer alone, which
    keeps the duration and leaves the feed open — the honest half of it,
    rather than a made-up hour nobody chose.
    """
    engine = get_engine()
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    if not {"graph_node", "graph_edge"} <= tables:
        return
    if "attached_to" not in {c["name"] for c in inspector.get_columns("graph_node")}:
        return

    with engine.begin() as connection:
        windows = connection.execute(text("""
            SELECT e.id, t.id, t.owner_pk, s.trigger_kind, s.duration_minutes, s.cron
            FROM graph_edge e
            JOIN graph_node s ON s.id = e.source_pk AND s.kind = 'trigger'
            JOIN graph_node t ON t.id = e.target_pk AND t.kind = 'feed'
        """)).fetchall()
        for edge_pk, feed_pk, owner_pk, kind, minutes, cron in windows:
            made = connection.execute(
                text(
                    # `label` is NOT NULL with no SQL default: the ORM fills
                    # it in and raw SQL has to say it.
                    "INSERT INTO graph_node (owner_pk, kind, enabled, label, x, y, "
                    "attached_to, duration_minutes) "
                    "VALUES (:owner, 'timer', 1, '', 0, 0, :host, :minutes)"
                ),
                {"owner": owner_pk, "host": feed_pk, "minutes": minutes or 30},
            )
            if kind == "schedule" and cron:
                connection.execute(
                    text(
                        "INSERT INTO graph_node (owner_pk, kind, enabled, label, x, y, "
                        "attached_to, cron) "
                        "VALUES (:owner, 'reset', 1, '', 0, 0, :host, :cron)"
                    ),
                    {"owner": owner_pk, "host": made.lastrowid, "cron": cron},
                )
            connection.execute(
                text("DELETE FROM graph_edge WHERE id = :pk"), {"pk": edge_pk}
            )
    if windows:
        log.info("turned %d feed window(s) into augmentations", len(windows))


#: Which condition piece each filter column becomes. The kind the rule turns
#: into, and the column it keeps living in — a condition carries its value
#: where that rule always was, so this converts the shape and not the data.
_RULES_AS_PIECES: tuple[tuple[str, str], ...] = (
    ("title_include", "has-words"),
    ("title_exclude", "lacks-words"),
    ("min_duration_sec", "longer-than"),
    ("max_duration_sec", "shorter-than"),
    ("tagged", "carrying"),
    ("max_per_run", "at-most"),
)


#: The four switches that used to sit on a Filter box, and the YouTube
#: condition each becomes. These were never general: a Short, a premiere and
#: a community post are YouTube's own distinctions, and they belong to the
#: plugin that knows what those words mean.
_SWITCHES_AS_PLUGIN_RULES: tuple[tuple[str, str], ...] = (
    ("skip_videos", "youtube:no-videos"),
    ("skip_shorts", "youtube:no-shorts"),
    ("skip_live", "youtube:no-live"),
    ("skip_posts", "youtube:no-posts"),
)


def rules_become_pieces() -> None:
    """Turn what a Filter or a Sort box carried into the pieces that say it.

    A box used to hold every rule at once, which meant a canvas of boxes all
    saying "Filter" and no way to tell them apart without opening each one.
    A rule is a piece now, one per condition, so a box says what it does.

    Each piece keeps the value in the column that rule always lived in, so
    this moves the rule onto a piece and changes nothing about what it means.

    The four content switches are the exception only in whose words they end
    up in: they were YouTube's distinctions sitting in the host, so each
    becomes one of YouTube's conditions — slotted under the same box, among
    the rest. The box stays where it is and keeps its wires.
    """
    engine = get_engine()
    inspector = inspect(engine)
    if "graph_node" not in set(inspector.get_table_names()):
        return
    columns = {c["name"] for c in inspector.get_columns("graph_node")}
    if "attached_to" not in columns or "plugin_ref" not in columns:
        return
    # Nothing to convert once no box carries a rule of its own. Asked of the
    # data rather than remembered in a marker table, so a database restored
    # from a backup taken before this is converted on the next start.
    wanted = [name for name, _ in _RULES_AS_PIECES if name in columns]
    switches = [name for name, _ in _SWITCHES_AS_PLUGIN_RULES if name in columns]
    if not wanted and not switches and "sort_by" not in columns:
        return

    made = 0
    with engine.begin() as connection:
        # A box that already has pieces under it has been converted, or was
        # drawn after this: either way its rules are not to be read twice.
        carried = wanted + switches
        still = " OR ".join(
            [f"n.{name} IS NOT NULL" for name in carried] + ["n.sort_by IS NOT NULL"]
        )
        boxes = connection.execute(text(f"""
            SELECT n.id, n.owner_pk, n.kind, n.x, n.y, n.sort_by, n.sort_dir,
                   {", ".join("n." + name for name in carried) or "NULL"}
            FROM graph_node n
            WHERE n.kind IN ('filter', 'sort') AND ({still})
        """)).fetchall()

        for row in boxes:
            node_pk, owner_pk, kind, x, y = row[0], row[1], row[2], row[3], row[4]
            sort_by, sort_dir = row[5], row[6]
            values = dict(zip(carried, row[7:]))

            if kind == "sort":
                connection.execute(
                    text(
                        "INSERT INTO graph_node (owner_pk, kind, enabled, label, x, y, "
                        "attached_to, sort_by, sort_dir) "
                        "VALUES (:owner, 'order', 1, '', :x, :y, :host, :by, :dir)"
                    ),
                    {
                        "owner": owner_pk, "x": x, "y": y + 60, "host": node_pk,
                        "by": sort_by or "published", "dir": sort_dir or "desc",
                    },
                )
                made += 1
                # Cleared, so a second run finds nothing left to convert.
                connection.execute(
                    text(
                        "UPDATE graph_node SET sort_by = NULL, sort_dir = NULL "
                        "WHERE id = :pk"
                    ),
                    {"pk": node_pk},
                )
                continue

            under = node_pk
            for column, piece_kind in _RULES_AS_PIECES:
                said = values.get(column)
                if said is None or said == "":
                    continue
                under = connection.execute(
                    text(
                        f"INSERT INTO graph_node (owner_pk, kind, enabled, label, x, y, "
                        f"attached_to, {column}) "
                        f"VALUES (:owner, :kind, 1, '', :x, :y, :host, :value)"
                    ),
                    {
                        "owner": owner_pk, "kind": piece_kind, "x": x, "y": y + 60,
                        "host": under, "value": said,
                    },
                ).lastrowid
                made += 1

            # The switches, as a YouTube box on the same spot, wired where the
            # filter was wired. Only made when one of them was actually on:
            # a filter that said nothing about Shorts gets no box.
            # The switches, as YouTube's own conditions, under the same box.
            # They were that box's rules; they stay that box's rules, said by
            # the plugin that knows what a Short is. Nothing is rewired.
            for column, ref in _SWITCHES_AS_PLUGIN_RULES:
                if not values.get(column):
                    continue
                under = connection.execute(
                    text(
                        "INSERT INTO graph_node (owner_pk, kind, enabled, label, x, y, "
                        "attached_to, plugin_ref) "
                        "VALUES (:owner, 'rule', 1, '', :x, :y, :host, :ref)"
                    ),
                    {
                        "owner": owner_pk, "x": x, "y": (y or 0) + 60,
                        "host": under, "ref": ref,
                    },
                ).lastrowid
                made += 1

            connection.execute(
                text(
                    "UPDATE graph_node SET "
                    + ", ".join(f"{name} = NULL" for name in carried)
                    + " WHERE id = :pk"
                ),
                {"pk": node_pk},
            )

    if made:
        log.info("turned %d box rule(s) into augmentations", made)


def plugin_boxes_become_pieces() -> None:
    """Turn a plugin box into a Filter box carrying that plugin's condition.

    There have been two shapes of plugin box and neither survives. The first
    *was* the question — "No Shorts" was a box. The second stood for the
    plugin, with its questions slotted under it. Both become the same thing: a
    Filter box, with the plugin's conditions among the conditions under it.

    A plugin has no box of its own now. It widens what the app's Filter box
    can be told, rather than standing a second kind of Filter beside it — so
    one Filter can ask "longer than ten minutes, and not a Short" instead of
    needing two boxes wired in a row to say it.

    The box keeps its place, its name and its wires, so the canvas looks the
    same afterwards and nothing has to be drawn again.
    """
    engine = get_engine()
    inspector = inspect(engine)
    if "graph_node" not in set(inspector.get_table_names()):
        return
    columns = {c["name"] for c in inspector.get_columns("graph_node")}
    if "attached_to" not in columns or "plugin_ref" not in columns:
        return

    with engine.begin() as connection:
        old = connection.execute(text("""
            SELECT id, owner_pk, x, y, plugin_ref, plugin_settings
            FROM graph_node
            WHERE kind = 'plugin' AND plugin_ref LIKE '%:%'
        """)).fetchall()
        for node_pk, owner_pk, x, y, ref, settings in old:
            connection.execute(
                text(
                    "INSERT INTO graph_node (owner_pk, kind, enabled, label, x, y, "
                    "attached_to, plugin_ref, plugin_settings) "
                    "VALUES (:owner, 'rule', 1, '', :x, :y, :host, :ref, :said)"
                ),
                {
                    "owner": owner_pk, "x": x, "y": (y or 0) + 60, "host": node_pk,
                    "ref": ref, "said": settings,
                },
            )
        # And every plugin box, of either shape, is a Filter box now: what it
        # asks is whatever is slotted under it, which is what a Filter means.
        turned = connection.execute(
            text("SELECT id FROM graph_node WHERE kind = 'plugin'")
        ).scalars().all()
        connection.execute(
            text(
                "UPDATE graph_node SET kind = 'filter', plugin_ref = NULL, "
                "plugin_settings = NULL WHERE kind = 'plugin'"
            )
        )
        for node_pk in turned:
            _fold_into_the_filter_before_it(connection, int(node_pk))
    if turned:
        log.info("turned %d plugin box(es) into filter boxes", len(turned))


def _fold_into_the_filter_before_it(connection: Any, node_pk: int) -> None:
    """Put a converted box's conditions on the Filter feeding it, if it can.

    One release put a plugin's condition in a box of its own, wired in after
    the Filter whose switches it came from. Converting that box to a Filter
    leaves two boxes saying "Filter" in a row where one would do, so the pair
    is folded back together.

    Only where it provably changes nothing: the box must be fed by exactly one
    Filter, that Filter must feed only this box and carry no conditions of its
    own, and nothing else may reach either of them. Anything less and the box
    stays as it is — two boxes in a row is untidy, a rewired path is wrong.
    """
    before = connection.execute(
        text("SELECT source_pk FROM graph_edge WHERE target_pk = :pk"), {"pk": node_pk}
    ).scalars().all()
    if len(before) != 1:
        return
    earlier = int(before[0])
    kind = connection.execute(
        text("SELECT kind FROM graph_node WHERE id = :pk"), {"pk": earlier}
    ).scalar()
    if kind != "filter":
        return
    onward = connection.execute(
        text("SELECT id FROM graph_edge WHERE source_pk = :pk"), {"pk": earlier}
    ).scalars().all()
    if len(onward) != 1:
        return
    held = connection.execute(
        text("SELECT count(*) FROM graph_node WHERE attached_to = :pk"), {"pk": earlier}
    ).scalar()
    if held:
        return

    connection.execute(
        text("UPDATE graph_node SET attached_to = :earlier WHERE attached_to = :pk"),
        {"earlier": earlier, "pk": node_pk},
    )
    # What this box reached, the earlier one reaches now.
    connection.execute(
        text("UPDATE graph_edge SET source_pk = :earlier WHERE source_pk = :pk"),
        {"earlier": earlier, "pk": node_pk},
    )
    connection.execute(text("DELETE FROM graph_edge WHERE id = :pk"), {"pk": onward[0]})
    connection.execute(text("DELETE FROM graph_node WHERE id = :pk"), {"pk": node_pk})
