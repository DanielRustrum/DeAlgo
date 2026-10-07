"""What the admin decided about each plugin: paused, granted, and where it came from.

Kept in the database rather than beside the plugin, because a plugin that
could write its own grants could grant itself anything.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from .. import permissions

# Re-exported, so that a caller handling what a plugin did wrong does not have
# to know which module the sentence came from. Said with `as` rather than with
# an `__all__`, which would also hide every function here from the reference.

log = logging.getLogger(__name__)


def decided() -> tuple[frozenset[str], dict[str, frozenset[str]]]:
    """Which plugins are off, and what each has been granted.

    One read for both, because they live in one row. A database that cannot
    be reached is read as "everything on, nothing granted": the safe way
    round, since a plugin quietly keeping a capability through a failed query
    is the one outcome nobody would want.
    """

    from ...db import session_scope
    from ...models import PluginState

    try:
        with session_scope() as session:
            off: set[str] = set()
            granted: dict[str, frozenset[str]] = {}
            for row in session.query(PluginState):
                if not row.enabled:
                    off.add(row.plugin_id)
                granted[row.plugin_id] = _names(row.granted)
            return frozenset(off), granted
    except Exception:  # pragma: no cover - a database that is not there yet
        log.warning("could not read plugin state; nothing is granted")
        return frozenset(), {}


def _names(stored: str | None) -> frozenset[str]:
    """The permission names in a stored JSON list; empty when it is unreadable."""
    import json

    if not stored:
        return frozenset()
    try:
        loaded = json.loads(stored)
    except (TypeError, ValueError):
        return frozenset()
    if not isinstance(loaded, list):
        return frozenset()
    return frozenset(str(name) for name in loaded)


def paused_ids() -> frozenset[str]:
    """Which plugins have been switched off."""
    return decided()[0]


def set_granted(plugin_id: str, names: frozenset[str]) -> None:
    """Record what a person granted a plugin, and hand it over.

    Only names this version understands are kept: a grant for a permission
    that has since been removed from the vocabulary would be a row nobody can
    read, and quietly dropping it is better than storing a promise that
    cannot be honoured.
    """
    import json

    from ...db import session_scope
    from ...models import PluginState, utcnow

    kept = sorted(name for name in names if name in permissions.BY_NAME)
    with session_scope() as session:
        row = (
            session.query(PluginState)
            .filter(PluginState.plugin_id == plugin_id)
            .one_or_none()
        )
        if row is None:
            row = PluginState(plugin_id=plugin_id)
            session.add(row)
        row.granted = json.dumps(kept)
        row.changed_at = utcnow()
    from .current import reload

    reload()


@dataclass(frozen=True)
class Origin:
    """Where a plugin was fetched from, and when."""

    url: str
    ref: str
    when: Any = None


def set_origin(plugin_id: str, url: str, ref: str) -> None:
    """Remember where a plugin was fetched from, so it can be fetched again."""
    from ...db import session_scope
    from ...models import PluginState, utcnow

    with session_scope() as session:
        row = (
            session.query(PluginState)
            .filter(PluginState.plugin_id == plugin_id)
            .one_or_none()
        )
        if row is None:
            row = PluginState(plugin_id=plugin_id)
            session.add(row)
        row.origin = url or None
        row.origin_ref = ref or None
        row.fetched_at = utcnow()
        row.changed_at = utcnow()


def origins() -> dict[str, Origin]:
    """Where each fetched plugin came from, by id.

    Read as a whole rather than per plugin: the Admin page draws every row at
    once, and one query beats one per plugin.
    """
    from ...db import session_scope
    from ...models import PluginState

    try:
        with session_scope() as session:
            return {
                row.plugin_id: Origin(row.origin, row.origin_ref or "", row.fetched_at)
                for row in session.query(PluginState)
                if row.origin
            }
    except Exception:  # pragma: no cover - a database that is not there yet
        return {}


def set_paused(plugin_id: str, *, paused: bool) -> None:
    """Switch a plugin off, or back on, and rebuild what is offered."""
    from ...db import session_scope
    from ...models import PluginState, utcnow

    with session_scope() as session:
        row = (
            session.query(PluginState)
            .filter(PluginState.plugin_id == plugin_id)
            .one_or_none()
        )
        if row is None:
            row = PluginState(plugin_id=plugin_id)
            session.add(row)
        row.enabled = not paused
        row.changed_at = utcnow()
    from .current import reload

    reload()
