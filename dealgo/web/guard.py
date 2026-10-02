"""Which requests need an account, and which need the admin's.

Kept as plain functions so the rules can be read and tested on their own,
rather than being spread across sixty route decorators where one forgotten
dependency is a hole nobody notices.

The default is deny: anything not named public needs a signed-in account.
"""

from __future__ import annotations

# Reachable without signing in. The login page, the things a browser fetches
# before it can be told to sign in, and the health check a container polls.
PUBLIC_EXACT = frozenset(
    {
        "/login",
        "/logout",
        "/healthz",
        "/offline",
        "/sw.js",
        "/manifest.webmanifest",
        "/favicon.ico",
    }
)
PUBLIC_PREFIXES = ("/static/",)

# The admin's own — and it is only one thing, now that every account keeps its
# own settings, its own Google connection and its own feeds. The admin manages
# *accounts*; everything else belongs to whoever is signed in.
ADMIN_EXACT: frozenset[str] = frozenset()
ADMIN_PREFIXES = ("/admin",)


def is_public(path: str) -> bool:
    """Whether a path can be reached without signing in."""
    return path in PUBLIC_EXACT or path.startswith(PUBLIC_PREFIXES)


def needs_admin(path: str) -> bool:
    """Whether a path belongs to the admin."""
    if is_public(path):
        return False
    return path in ADMIN_EXACT or path.startswith(ADMIN_PREFIXES)


def safe_next(target: str | None) -> str:
    """Where to go after signing in.

    Only ever a path on this site: an open redirect turns a login page into a
    way to send someone somewhere else while looking like it did not.
    """
    if not target:
        return "/"
    if not target.startswith("/") or target.startswith("//"):
        return "/"
    # A backslash reads as a slash to some browsers, so "/\evil" can become
    # "//evil" — the off-site form the line above refuses. Control characters
    # would let a response header be split.
    if any(bad in target for bad in ("\\", "\n", "\r", "\t")):
        return "/"
    return target
