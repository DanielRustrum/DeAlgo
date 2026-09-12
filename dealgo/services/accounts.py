"""Who may sign in, and how that is proved.

The shape of it:

* Passwords are stored as scrypt hashes with a per-password salt. scrypt is in
  the standard library and is memory-hard, so no dependency is added and a
  stolen database is expensive to attack. Verification compares in constant
  time.
* A session is a random token in a cookie. Only its SHA-256 is stored, so this
  table is not enough to impersonate anyone, and sessions can be revoked at
  once — which is what makes "disable this account" mean something.
* The admin comes from the environment on every start. That is the recovery
  path: lose the password, change the variable, restart.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import logging
import secrets
from dataclasses import dataclass

from sqlalchemy import select, text
from sqlalchemy.orm import Session, selectinload

from ..config import CONFIG
from ..models import LoginSession, User, to_naive_utc, utcnow

log = logging.getLogger(__name__)

# scrypt at the parameters OWASP suggests for interactive logins: ~16 MB of
# memory per attempt, which is the point — it is what makes guessing slow.
_SCRYPT_N = 2**14
_SCRYPT_R = 8
_SCRYPT_P = 1
_KEY_LENGTH = 32
_SALT_BYTES = 16

# Long enough that guessing is hopeless, short enough to type. The limit stops
# a very long password becoming a way to make the server do a lot of work.
MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_LENGTH = 1024
MAX_USERNAME_LENGTH = 64

SESSION_COOKIE = "dealgo_session"


class AccountError(Exception):
    """Something the person doing it should be told about."""


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


# -- passwords -------------------------------------------------------------


def hash_password(password: str, *, enforce_length: bool = True) -> str:
    """`scrypt$<salt>$<key>`, both hex. The salt is per password.

    The length rule is skipped only for the admin password, which comes from
    the environment: that is the operator's own decision, and refusing it
    would mean refusing to start. Everything else goes through the rule.
    """
    if enforce_length:
        _check_password(password)
    elif not password:
        raise AccountError("A password is needed.")
    salt = secrets.token_bytes(_SALT_BYTES)
    key = _derive(password, salt)
    return f"scrypt${salt.hex()}${key.hex()}"


def verify_password(password: str, stored: str) -> bool:
    """Constant-time, and False rather than an exception for anything odd."""
    try:
        scheme, salt_hex, key_hex = stored.split("$")
        if scheme != "scrypt":
            return False
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(key_hex)
    except ValueError:
        return False
    if not password or len(password) > MAX_PASSWORD_LENGTH:
        return False
    return hmac.compare_digest(_derive(password, salt), expected)


def _derive(password: str, salt: bytes) -> bytes:
    return hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=_SCRYPT_N,
        r=_SCRYPT_R,
        p=_SCRYPT_P,
        dklen=_KEY_LENGTH,
        maxmem=64 * 1024 * 1024,
    )


def _check_password(password: str) -> None:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise AccountError(f"A password needs at least {MIN_PASSWORD_LENGTH} characters.")
    if len(password) > MAX_PASSWORD_LENGTH:
        raise AccountError("That password is longer than De-Algo will hash.")


def normalize_username(raw: str) -> str:
    name = raw.strip().lower()
    if not name:
        raise AccountError("A username is needed.")
    if len(name) > MAX_USERNAME_LENGTH:
        raise AccountError(f"A username can be at most {MAX_USERNAME_LENGTH} characters.")
    if not all(c.isalnum() or c in "._-" for c in name):
        raise AccountError("A username can hold letters, digits, dots, dashes and underscores.")
    return name


# -- accounts --------------------------------------------------------------


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


def ensure_admin(session: Session) -> User | None:
    """Make the database agree with the environment, on every start.

    The admin's password lives in the environment and nowhere else, so this
    resets it each time. That is deliberate: it is the way back in when the
    password is lost, and it is why the UI never offers to change it.
    """
    if not CONFIG.auth_enabled:
        return None
    if CONFIG.admin_password_weak:
        log.warning(
            "DEALGO_ADMIN_PASSWORD is shorter than %d characters. Fine for trying this out; "
            "change it before anyone else can reach the address.",
            MIN_PASSWORD_LENGTH,
        )
    name = normalize_username(CONFIG.admin_user)
    admin = find(session, name)
    if admin is None:
        # Any other admin account is a leftover from a previous value of the
        # variable; it should not keep its powers.
        for other in session.scalars(select(User).where(User.is_admin.is_(True))):
            other.is_admin = False
            revoke_all(session, other)
            log.info("account %s is no longer the admin", other.username)
        made = create_user(
            session, name, CONFIG.admin_password, is_admin=True, enforce_length=False
        )
        adopt_unowned(session, made)
        return made

    admin.is_admin = True
    admin.enabled = True
    adopt_unowned(session, admin)
    if not verify_password(CONFIG.admin_password, admin.password_hash):
        admin.password_hash = hash_password(CONFIG.admin_password, enforce_length=False)
        revoke_all(session, admin)
        log.info("admin password taken from the environment")
    session.flush()
    return admin


# Everything that belongs to somebody. Listed here rather than discovered, so
# adding a table is a decision about who owns its rows.
# Each with the column that has to stay unique per owner, where there is one.
OWNED_TABLES: tuple[tuple[str, str | None], ...] = (
    ("settings", None),
    ("oauth_token", None),
    ("channel", "channel_id"),
    ("playlist", "playlist_id"),
    ("video", "video_id"),
    ("quota_usage", "day"),
    ("sync_run", None),
    ("graph_node", None),
    ("graph_edge", None),
)


def adopt_unowned(session: Session, admin: User) -> int:
    """Hand rows with no owner to the admin.

    Everything made before sign-in was switched on belongs to the implicit
    owner — which is nobody, once there are accounts. Without this the admin
    would sign in to an empty De-Algo and its channels and feeds would sit
    there, invisible to everyone.

    Also covers the other direction: anything added while sign-in was off
    again is picked up the next time it is on.
    """
    adopted = 0
    for table, key in OWNED_TABLES:
        # Adopt only what will not collide. A row can be left over from a boot
        # where sign-in was off — the admin may already have one for the same
        # channel, feed or day — and a bare UPDATE would fail the per-owner
        # unique index and take startup down with it.
        clause = f"UPDATE {table} SET owner_pk = :owner WHERE owner_pk IS NULL"
        if key:
            clause += (
                f" AND NOT EXISTS (SELECT 1 FROM {table} AS mine"
                f" WHERE mine.owner_pk = :owner AND mine.{key} = {table}.{key})"
            )
        result = session.execute(text(clause), {"owner": admin.id})
        # A plain UPDATE always reports a count; the typed Result does not say so.
        adopted += getattr(result, "rowcount", 0)

    # What is left is a duplicate of something the admin already has. For the
    # bookkeeping tables that is meaningless and goes; anything else stays put
    # rather than being deleted on a guess, and says so.
    for table in ("settings", "quota_usage", "oauth_token"):
        session.execute(text(f"DELETE FROM {table} WHERE owner_pk IS NULL"))
    for table, _ in OWNED_TABLES:
        left = session.execute(
            text(f"SELECT COUNT(*) FROM {table} WHERE owner_pk IS NULL")
        ).scalar()
        if left:
            log.warning(
                "%d %s row(s) could not be adopted: %s already has one of each",
                left, table, admin.username,
            )
    if adopted:
        session.flush()
        log.info("%d row(s) with no owner are now %s's", adopted, admin.username)
    return adopted


# -- sessions --------------------------------------------------------------


def _fingerprint(token: str) -> str:
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
    if not token:
        return
    found = session.scalar(
        select(LoginSession).where(LoginSession.token_hash == _fingerprint(token))
    )
    if found is not None:
        session.delete(found)
        session.flush()


def revoke_all(session: Session, user: User) -> None:
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


# -- signing in ------------------------------------------------------------


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
