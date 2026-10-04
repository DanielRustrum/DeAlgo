"""The admin, who comes from the environment on every start, and what it adopts."""

from __future__ import annotations

import logging

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from ...config import CONFIG
from ...models import User
from .passwords import MIN_PASSWORD_LENGTH, hash_password, verify_password
from .sessions import revoke_all
from .users import create_user, find, normalize_username

log = logging.getLogger(__name__)


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
    ("sync_run", None),
    ("graph_node", None),
    ("graph_edge", None),
    ("plugin_user_setting", "key"),
    ("user_theme", "slot"),
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
    # bookkeeping tables, and a theme when the admin has one of its own, that
    # is meaningless and goes; anything else stays put rather than being
    # deleted on a guess, and says so.
    for table in ("settings", "oauth_token", "user_theme"):
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
