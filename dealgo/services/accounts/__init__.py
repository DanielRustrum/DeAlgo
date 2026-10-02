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

from .admin import ensure_admin
from .errors import AccountError
from .passwords import MIN_PASSWORD_LENGTH, hash_password, verify_password
from .sessions import (
    SESSION_COOKIE,
    Identity,
    clear_expired,
    end_session,
    identify,
    revoke_all,
    start_session,
)
from .users import (
    authenticate,
    create_user,
    delete_user,
    find,
    list_users,
    normalize_username,
    set_enabled,
    set_password,
)

__all__ = [
    "AccountError",
    "authenticate",
    "clear_expired",
    "create_user",
    "delete_user",
    "end_session",
    "ensure_admin",
    "find",
    "hash_password",
    "identify",
    "Identity",
    "list_users",
    "MIN_PASSWORD_LENGTH",
    "normalize_username",
    "revoke_all",
    "SESSION_COOKIE",
    "set_enabled",
    "set_password",
    "start_session",
    "verify_password",
]
