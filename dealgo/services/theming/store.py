"""Each account's theme, kept and fetched.

Every page asks for its account's theme, so what was read is held until the
next save rather than read again per request.
"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...db import session_scope
from ...models import UserTheme
from ..scope import OwnerId, belongs_to
from .css import PageTheme, page_theme
from .theme import Theme, ThemeError, loads

log = logging.getLogger(__name__)

SLOT = "current"

_held: dict[OwnerId, Theme] = {}
_pages: dict[OwnerId, PageTheme] = {}

#: The stock look, for a page with nobody signed in to it.
STOCK = page_theme(Theme())


def load(owner: OwnerId) -> Theme:
    """An account's theme; the stock one if it never changed anything."""
    if owner in _held:
        return _held[owner]
    with session_scope() as session:
        data = session.scalar(
            select(UserTheme.data)
            .where(belongs_to(UserTheme, owner))
            .where(UserTheme.slot == SLOT)
        )
    try:
        theme = loads(data) if data else Theme()
    except ThemeError as exc:
        # Saved by an earlier release that allowed something this one does
        # not. The page still has to render, so it renders stock.
        log.warning("Ignoring a stored theme that no longer reads: %s", exc)
        theme = Theme()
    _held[owner] = theme
    return theme


def page(owner: OwnerId) -> PageTheme:
    """What base.html puts on every page for this account."""
    if owner not in _pages:
        _pages[owner] = page_theme(load(owner))
    return _pages[owner]


def save(owner: OwnerId, theme: Theme) -> None:
    """Keep an account's theme."""
    with session_scope() as session:
        write(session, owner, theme)
    drop_held()


def write(session: Session, owner: OwnerId, theme: Theme) -> None:
    """Keep a theme within a session already open — a restore's, say. An empty
    theme removes the row: the stock look needs none. The caller drops what
    is held once its session is done."""
    row = session.scalar(
        select(UserTheme).where(belongs_to(UserTheme, owner)).where(UserTheme.slot == SLOT)
    )
    if theme.is_empty():
        if row is not None:
            session.delete(row)
    elif row is None:
        session.add(UserTheme(owner_pk=owner, slot=SLOT, data=theme.dumps()))
    else:
        row.data = theme.dumps()


def drop_held() -> None:
    """Forget what was read: after a save, a restore, or an account removed."""
    _held.clear()
    _pages.clear()
