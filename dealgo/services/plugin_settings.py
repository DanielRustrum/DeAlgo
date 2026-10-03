"""The values plugins' settings are set to.

What a plugin asked for lives in its file (registry/settings.py); what
somebody answered lives here. App settings are the admin's, one value for the
whole install; user settings are each account's own.

Read on every call into a plugin that asks — a Filter's `keep` runs once per
item — so what has been read is held in memory, and any save drops it.
"""

from __future__ import annotations

from sqlalchemy import delete, select

from ..db import session_scope
from ..models import PluginAppSetting, PluginUserSetting
from .scope import OwnerId, belongs_to

#: What has been read, by (plugin, scope, owner). The owner is None for app
#: settings, which have none.
_held: dict[tuple[str, str, OwnerId], dict[str, str]] = {}


def key_for(plugin_id: str, name: str) -> str:
    """How one setting is stored: `<plugin id>:<name>`."""
    return f"{plugin_id}:{name}"


def stored(plugin_id: str, scope: str, owner: OwnerId = None) -> dict[str, str]:
    """Every value set for one plugin in one scope, by setting name.

    Only what somebody saved: a setting never touched is absent, and its
    declaration supplies the default.
    """
    held = (plugin_id, scope, owner if scope == "user" else None)
    if held in _held:
        return _held[held]
    prefix = key_for(plugin_id, "")
    with session_scope() as session:
        if scope == "app":
            rows = session.execute(
                select(PluginAppSetting.key, PluginAppSetting.value)
                .where(PluginAppSetting.key.startswith(prefix, autoescape=True))
            )
        else:
            rows = session.execute(
                select(PluginUserSetting.key, PluginUserSetting.value)
                .where(belongs_to(PluginUserSetting, owner))
                .where(PluginUserSetting.key.startswith(prefix, autoescape=True))
            )
        found = {key[len(prefix):]: value for key, value in rows}
    _held[held] = found
    return found


def save(plugin_id: str, scope: str, owner: OwnerId, values: dict[str, str]) -> None:
    """Set some of one plugin's values in one scope, leaving the rest as they were."""
    with session_scope() as session:
        for name, value in values.items():
            key = key_for(plugin_id, name)
            if scope == "app":
                app_row = session.scalar(select(PluginAppSetting).where(PluginAppSetting.key == key))
                if app_row is None:
                    session.add(PluginAppSetting(key=key, value=value))
                else:
                    app_row.value = value
            else:
                user_row = session.scalar(
                    select(PluginUserSetting)
                    .where(belongs_to(PluginUserSetting, owner))
                    .where(PluginUserSetting.key == key)
                )
                if user_row is None:
                    session.add(PluginUserSetting(owner_pk=owner, key=key, value=value))
                else:
                    user_row.value = value
    _held.clear()


def forget(plugin_id: str) -> None:
    """Every value anybody set for a plugin, gone with the plugin itself."""
    prefix = key_for(plugin_id, "")
    with session_scope() as session:
        session.execute(
            delete(PluginAppSetting).where(PluginAppSetting.key.startswith(prefix, autoescape=True))
        )
        session.execute(
            delete(PluginUserSetting)
            .where(PluginUserSetting.key.startswith(prefix, autoescape=True))
        )
    _held.clear()


def drop_held() -> None:
    """Forget what has been read, so the next read goes to the database.

    For anything that changes the tables behind this module's back — a
    restore, an account removed — and for tests.
    """
    _held.clear()
