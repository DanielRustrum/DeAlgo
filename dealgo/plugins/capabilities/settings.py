"""`settings`: what the admin and each account set for this plugin.

Always there, and asks no permission: a plugin reading back what it was
told is not reaching anything of anyone's. It reads only its own values, and
`user` only the values of the account whose work is in hand — the same
owner `dealgo` and `account` answer about.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .owner import whose

if TYPE_CHECKING:
    from ..registry.plugin import Plugin


class PluginSettings:
    """What a plugin is handed as `settings`."""

    #: What a plugin may reach on this. Anything not named here is
    #: unreachable, which is what keeps `__class__` — and the whole
    #: machine behind it — out of a plugin's hands.
    LUA_OFFERS = frozenset({"app", "user"})

    def __init__(self, plugin: Plugin):
        """Bound to the plugin it was made for, whose declarations it reads.

        The plugin rather than its settings: the capability is made before
        the file has run, and the declarations are only known after.
        """
        self._plugin = plugin

    def app(self, name: object) -> str | float | bool | None:
        """An install-wide setting, as the admin left it: typed, or its default.

        None for a name the plugin never declared, so a typo reads as nothing
        rather than as an error inside somebody's sync.
        """
        return self._read("app", str(name), None)

    def user(self, name: object) -> str | float | bool | None:
        """This account's own setting, or its default while no account is in hand."""
        owner, acting = whose()
        if not acting:
            declared = self._plugin.settings.named("user", str(name))
            return None if declared is None else declared.read(None)
        return self._read("user", str(name), owner)

    def _read(self, scope: str, name: str, owner: int | None) -> str | float | bool | None:
        """One value from the database, through its declaration."""
        from ...services import plugin_settings

        declared = self._plugin.settings.named(scope, name)
        if declared is None:
            return None
        if scope == "app":
            return declared.read(plugin_settings.app_value(self._plugin.id, name))
        stored = plugin_settings.stored(self._plugin.id, scope, owner)
        return declared.read(stored.get(name))
