"""Signing in: a random token in a cookie, of which only a hash is kept."""

from __future__ import annotations

import datetime as dt
import hashlib
import secrets
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ...config import CONFIG
from ...models import LoginSession, User, utcnow

SESSION_COOKIE = "pamphlets_session"
#: The cookie's name before the app was called Pamphlets: still honoured, so
#: nobody signed in then is signed out by the rename.
OLD_SESSION_COOKIE = "dealgo_session"


@dataclass(frozen=True)
class Identity:
    """Who is making a request, as the rest of the app needs to know it."""

    username: str
    is_admin: bool
    user_pk: int | None = None

    @property
    def initial(self) -> str:
        """The letter the account icon wears."""
        return self.username[:1].upper() or "?"

    @property
    def hue(self) -> int:
        """A colour of its own, picked from the name so it never moves.

        The same trick the channel avatars use, so two accounts are told apart
        at a glance without anything having to be stored.
        """
        return int(hashlib.sha256(self.username.encode("utf-8")).hexdigest()[:4], 16) % 360


def _fingerprint(token: str) -> str:
    """The SHA-256 of a session token: all the database ever holds of it."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def start_session(session: Session, user: User, *, agent: str = "") -> str:
    """Returns the token to put in the cookie. It is not stored anywhere."""
    token = secrets.token_urlsafe(32)
    session.add(
        LoginSession(
            token_hash=_fingerprint(token),
            user_pk=user.id,
            expires_at=utcnow() + dt.timedelta(days=CONFIG.session_days),
            agent=(agent or "")[:255] or None,
        )
    )
    user.last_seen_at = utcnow()
    session.flush()
    return token


def identify(session: Session, token: str | None) -> User | None:
    """The account a cookie belongs to, or None for anything at all wrong."""
    if not token:
        return None
    found = session.scalar(
        select(LoginSession)
        .options(selectinload(LoginSession.user))
        .where(LoginSession.token_hash == _fingerprint(token))
    )
    if found is None:
        return None
    # An expired session is deleted when it is next shown; a disabled account's are refused.
    if found.expired:
        session.delete(found)
        session.flush()
        return None
    if not found.user.enabled:
        return None
    found.last_used_at = utcnow()
    found.user.last_seen_at = utcnow()
    return found.user


def end_session(session: Session, token: str | None) -> None:
    """Sign out the session this token belongs to, if it is live."""
    if not token:
        return
    found = session.scalar(
        select(LoginSession).where(LoginSession.token_hash == _fingerprint(token))
    )
    if found is not None:
        session.delete(found)
        session.flush()


def revoke_all(session: Session, user: User) -> None:
    """Sign an account out of every browser."""
    for existing in list(user.sessions):
        session.delete(existing)
    session.flush()


def clear_expired(session: Session) -> int:
    """Housekeeping: rows for sittings that ended by themselves."""
    stale = list(
        session.scalars(select(LoginSession).where(LoginSession.expires_at < utcnow()))
    )
    for row in stale:
        session.delete(row)
    session.flush()
    return len(stale)
