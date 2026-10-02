"""What a plugin may ask for beyond the table it starts with.

Everything past pure Lua is asked for by name and granted by a person. The
vocabulary is closed and lives here. A plugin says which of these it wants and
why it wants them; it cannot invent one, because a permission nobody has
written down is a permission nobody can reason about.

What each permission actually hands over is in `capabilities`.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Permission:
    """One thing a plugin can ask for."""

    name: str
    label: str
    #: What granting it actually allows, said plainly enough that somebody
    #: who does not write Lua can decide.
    means: str
    #: Why it is worth pausing over. Empty for the ones that are not.
    caution: str = ""


KNOWN: tuple[Permission, ...] = (
    Permission(
        name="network",
        label="Make network requests",
        means=(
            "Fetch web addresses of its own choosing while it runs. Requests go "
            "through De-Algo, so they wait when a host asks them to and are "
            "capped in size and number."
        ),
        caution=(
            "This is the one worth thinking about. A plugin that can fetch can "
            "also send — anything it has been shown could leave this machine."
        ),
    ),
    Permission(
        name="clock",
        label="Read the time",
        means="Ask what the time is now, so it can judge how old something is.",
    ),
    Permission(
        name="read",
        label="See what you are watching",
        means=(
            "Read the shape of the account it is working for: which sources "
            "are watched, which feeds exist, what is tagged what. Never what "
            "you have read or watched, and never another account's."
        ),
    ),
    Permission(
        name="manage",
        label="Change what you are watching",
        means=(
            "Add a source, or switch one on or off — for the account it is "
            "working for. Anything it adds arrives paused, so it can suggest "
            "and cannot start fetching."
        ),
        caution=(
            "It can rearrange a setup you built. Nothing is deleted, but "
            "things can appear and be switched off."
        ),
    ),
    Permission(
        name="account",
        label="Act as your connected account",
        means=(
            "Make requests to the service your connected account belongs to — "
            "reading your playlists, adding to them, looking up channels. "
            "De-Algo signs and sends them and charges the day's allowance; "
            "the plugin never sees the credential, and nothing is signed for "
            "any address but that service's own."
        ),
        caution=(
            "It acts as you there. Anything the account can do, a plugin with "
            "this can do — including changing playlists."
        ),
    ),
    Permission(
        name="log",
        label="Write to the log",
        means=(
            "Leave lines in De-Algo's own log, which is how a plugin explains "
            "itself when it is not doing what you expected."
        ),
    ),
)


BY_NAME = {permission.name: permission for permission in KNOWN}


def describe(name: str) -> Permission:
    """A permission by name, falling back rather than failing: a plugin that
    asks for something this version does not know still has to draw."""
    known = BY_NAME.get(name)
    if known is not None:
        return known
    return Permission(
        name=name,
        label=name,
        means="This version of De-Algo does not know what that is, so it is refused.",
        caution="Nothing is granted for a permission nobody here understands.",
    )
