"""Whose rows a query is about.

Every top-level table carries `owner_pk`. NULL means the one implicit owner,
which is what everything is while sign-in is switched off — so the same code
serves both shapes and there is no separate path to get wrong.

The point of the helper is that narrowing is one call rather than a `.where`
written out at each of a hundred sites: a missed filter is one account reading
another's feeds, and the way to avoid that is for the filter to be the easy
thing to write.
"""

from __future__ import annotations

from typing import Any, TypeVar

from sqlalchemy import Select
from sqlalchemy.sql.elements import ColumnElement

from ..models import (
    Channel,
    OAuthToken,
    GraphEdge,
    GraphNode,
    Playlist,
    PluginUserSetting,
    RepositoryItem,
    RunEvent,
    Settings,
    SyncRun,
    Video,
)

# Anything with an owner. Listed rather than inferred, so adding a table is a
# deliberate decision about who it belongs to.
Owned = (
    Channel | Playlist | Video | Settings | SyncRun | GraphNode | GraphEdge
    | RunEvent | RepositoryItem | PluginUserSetting | OAuthToken
)

# A select of anything: one column, several, or a count. The rows it yields
# are not this helper's business — only the table they come from is.
Rows = TypeVar("Rows", bound=tuple[Any, ...])

# Who a request is about. None is the implicit owner, not "everyone".
OwnerId = int | None


def belongs_to(model: type[Owned], owner: OwnerId) -> ColumnElement[bool]:
    """The condition that picks out one owner's rows.

    `owner_pk == None` is not the same as `IS NULL` in SQL, which is why this
    exists rather than a bare comparison.
    """
    if owner is None:
        return model.owner_pk.is_(None)
    return model.owner_pk == owner


def owned(statement: Select[Rows], model: type[Owned], owner: OwnerId) -> Select[Rows]:
    """Narrow a select to one owner's rows."""
    return statement.where(belongs_to(model, owner))


def stamp(row: Any, owner: OwnerId) -> Any:
    """Mark a new row as belonging to this owner. Returns it, to read well at
    the point of creation."""
    row.owner_pk = owner
    return row
