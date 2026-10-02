"""The accounts themselves: making, finding, changing, checking and removing them."""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ...models import User
from .errors import AccountError
from .passwords import hash_password, verify_password
from .sessions import revoke_all

log = logging.getLogger(__name__)


MAX_USERNAME_LENGTH = 64


def normalize_username(raw: str) -> str:
    name = raw.strip().lower()
    if not name:
        raise AccountError("A username is needed.")
    if len(name) > MAX_USERNAME_LENGTH:
        raise AccountError(f"A username can be at most {MAX_USERNAME_LENGTH} characters.")
    if not all(c.isalnum() or c in "._-" for c in name):
        raise AccountError("A username can hold letters, digits, dots, dashes and underscores.")
    return name


def list_users(session: Session) -> list[User]:
    return list(
        session.scalars(
            select(User).options(selectinload(User.sessions)).order_by(User.username)
        )
    )


def find(session: Session, username: str) -> User | None:
    return session.scalar(select(User).where(User.username == username.strip().lower()))


def create_user(
    session: Session,
    username: str,
    password: str,
    *,
    is_admin: bool = False,
    enforce_length: bool = True,
) -> User:
    name = normalize_username(username)
    if find(session, name) is not None:
        raise AccountError(f"There is already an account called {name}.")
    user = User(
        username=name,
        password_hash=hash_password(password, enforce_length=enforce_length),
        is_admin=is_admin,
        enabled=True,
    )
    session.add(user)
    session.flush()
    log.info("account created: %s%s", name, " (admin)" if is_admin else "")
    return user


def set_password(session: Session, user: User, password: str) -> None:
    user.password_hash = hash_password(password)
    # Changing a password ends every other sitting: that is usually the whole
    # reason for changing it.
    revoke_all(session, user)
    session.flush()


def set_enabled(session: Session, user: User, *, enabled: bool) -> None:
    user.enabled = enabled
    if not enabled:
        revoke_all(session, user)
    session.flush()


def delete_user(session: Session, user: User) -> None:
    if user.is_admin:
        raise AccountError("The admin account is set in the environment and cannot be deleted.")
    session.delete(user)
    session.flush()


def authenticate(session: Session, username: str, password: str) -> User:
    """The one place a password is checked. Raises with a message fit to show.

    The same message either way: which half was wrong is not something a
    stranger should be able to learn.
    """
    wrong = AccountError("That username and password do not match.")
    try:
        name = normalize_username(username)
    except AccountError:
        raise wrong from None

    user = find(session, name)
    if user is None:
        # Hash anyway, so a missing account does not answer faster than a
        # wrong password and give itself away.
        verify_password(password, hash_password("not-a-real-password"))
        raise wrong
    if not verify_password(password, user.password_hash):
        raise wrong
    if not user.enabled:
        raise AccountError("That account has been switched off.")
    return user
