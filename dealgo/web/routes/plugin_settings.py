"""Plugins' own settings: each account's under Settings, the admin's under Admin.

One form shape for both, drawn by _plugin_settings.html. What differs is who
may save it — anybody signed in for their own user settings, only the admin
for app settings, which the guard decides by the /admin path — and whose
values it reads and writes.
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import Response
from starlette.datastructures import FormData

from ...plugins import registry
from ...plugins.registry.plugin import Plugin
from ...plugins.registry.settings import Setting
from ...services import plugin_settings
from ...services.scope import OwnerId
from ..responses import owner_of, redirect
from ..templates import Context

router = APIRouter()

#: How long a text setting may be. An address or a key is a line, not a file.
MOST_TEXT = 2000


class Refused(ValueError):
    """A value the form sent that the setting cannot take, in words."""


def settings_view(plugin: Plugin, scope: str, owner: OwnerId = None) -> list[Context]:
    """One plugin's settings in one scope, as the form draws them.

    A secret's value is never put in the page: only whether one is saved,
    so the form can say so and offer to clear it.
    """
    saved = plugin_settings.stored(plugin.id, scope, owner if scope == "user" else None)
    shown: list[Context] = []
    for setting in plugin.settings.of(scope):
        value = saved.get(setting.name)
        shown.append(
            {
                "setting": setting,
                "value": "" if setting.kind == "secret" else (
                    setting.default if value is None else value
                ),
                "is_set": bool(value),
                # Given by the environment while nothing is saved here.
                "env": plugin_settings.env_name(plugin.id, setting.name) if scope == "app" else "",
                "from_env": scope == "app" and not value
                and bool(plugin_settings.from_env(plugin.id, setting.name)),
            }
        )
    return shown


def user_settings_panels(owner: OwnerId) -> list[Context]:
    """Every switched-on plugin with something for this account: settings of
    its own, or a service to sign in to.

    Switched-off plugins are left out: their settings would change nothing
    until the admin turns them back on, and a form that does nothing is a
    question about nothing.
    """
    return [
        {"plugin": plugin, "fields": settings_view(plugin, "user", owner)}
        for plugin in registry.current().plugins
        if plugin.ok and (plugin.settings.user or plugin.connect is not None)
    ]


@router.post("/settings/plugins/{plugin_id}")
async def save_user_settings(request: Request, plugin_id: str) -> Response:
    """Save this account's own settings for one plugin."""
    back = f"/settings#plugin-{plugin_id}"
    plugin = _plugin(plugin_id)
    if plugin is None or not plugin.ok or not plugin.settings.user:
        return redirect("/settings", err="That plugin has no settings to save.")
    return await _save(request, plugin, "user", owner_of(request), back)


@router.post("/admin/plugins/{plugin_id}/settings")
async def save_app_settings(request: Request, plugin_id: str) -> Response:
    """Save a plugin's install-wide settings. The admin's alone: /admin is guarded.

    A switched-off plugin may still be set up, so that it is ready when it is
    switched back on.
    """
    back = f"/admin/plugins#plugin-{plugin_id}"
    plugin = _plugin(plugin_id)
    if plugin is None or not plugin.loaded or not plugin.settings.app:
        return redirect("/admin/plugins", err="That plugin has no settings to save.")
    return await _save(request, plugin, "app", None, back)


def _plugin(plugin_id: str) -> Plugin | None:
    """The plugin by its id, if there is one here."""
    if not set(plugin_id) <= registry.PLAIN:
        return None
    return next((p for p in registry.current().plugins if p.id == plugin_id), None)


async def _save(
    request: Request, plugin: Plugin, scope: str, owner: OwnerId, back: str
) -> Response:
    """Read the form, check every value, and save them all or none."""
    sent = await request.form()
    try:
        values = values_from(plugin.settings.of(scope), sent)
    except Refused as said:
        return redirect(back, err=f"{plugin.title}: {said} Nothing was saved.")
    plugin_settings.save(plugin.id, scope, owner, values)
    whose = "for everyone" if scope == "app" else "for you"
    return redirect(back, ok=f"{plugin.title}’s settings are saved {whose}.")


def values_from(declared: tuple[Setting, ...], sent: FormData) -> dict[str, str]:
    """What to store for each declared setting, from what the form sent.

    Only declared names are read, whatever else the form carries. A secret
    left blank keeps what it had — it was never shown, so blank means
    "unchanged" — unless its clear box is ticked.
    """
    values: dict[str, str] = {}
    for setting in declared:
        given = sent.get(f"s_{setting.name}")
        typed = given.strip() if isinstance(given, str) else ""
        if setting.kind == "toggle":
            values[setting.name] = "1" if typed else ""
        elif setting.kind == "secret":
            if sent.get(f"clear_{setting.name}"):
                values[setting.name] = ""
            elif typed:
                values[setting.name] = typed[:MOST_TEXT]
        elif setting.kind == "number":
            if typed:
                try:
                    float(typed)
                except ValueError:
                    raise Refused(f"“{setting.label}” has to be a number.") from None
            values[setting.name] = typed
        elif setting.kind == "choice":
            if typed not in {value for value, _ in setting.choices}:
                raise Refused(f"“{setting.label}” has to be one of its choices.")
            values[setting.name] = typed
        else:
            values[setting.name] = typed[:MOST_TEXT]
    return values
