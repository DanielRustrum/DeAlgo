"""The settings a plugin asks to be given, and how each is drawn and read.

Two kinds, because there are two kinds of person setting them:

* **app** settings are the admin's, set once for the whole install on the
  plugin's card under Admin → Plugins — an API key the install pays for, a
  server address everyone shares.
* **user** settings are each account's own, under Settings — a preference
  about what that person wants from the plugin.

A plugin declares them; it never stores them. The values live in the
database (services/plugin_settings.py), and the plugin reads them back
through the `settings` capability.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..runtime import PluginError
from .storage import PLAIN

#: What a setting may be. Each is drawn as the control it names: a line of
#: text, a number, an on/off switch, a list to choose from, and a secret —
#: text that is never shown back once saved.
KINDS = ("text", "number", "toggle", "choice", "secret")

#: Who sets which. Spelled the way a plugin spells them.
SCOPES = ("app", "user")

#: How many one plugin may ask for, per scope. A form longer than this is a
#: plugin asking to be configured rather than used.
MOST_SETTINGS = 20


@dataclass(frozen=True)
class Setting:
    """One setting a plugin asked for."""

    name: str
    label: str
    #: One of `KINDS`.
    kind: str = "text"
    #: What it is until somebody sets it, as the form would send it:
    #: "1" or "" for a toggle.
    default: str = ""
    #: A line under the control, in the plugin's words.
    hint: str = ""
    placeholder: str = ""
    #: For a choice: each option as (value, label).
    choices: tuple[tuple[str, str], ...] = ()

    def read(self, stored: str | None) -> str | float | bool:
        """A stored value as the plugin should see it: typed, or the default.

        A number that no longer parses — the plugin changed a text setting to
        a number — falls back to the default rather than handing the plugin a
        string it was promised would not be one.
        """
        value = self.default if stored is None else stored
        if self.kind == "toggle":
            return value == "1"
        if self.kind == "number":
            try:
                number = float(value or self.default or 0)
            except ValueError:
                number = float(self.default or 0)
            return int(number) if number.is_integer() else number
        return value


@dataclass(frozen=True)
class Settings:
    """Everything a plugin asked to be configured with."""

    app: tuple[Setting, ...] = ()
    user: tuple[Setting, ...] = ()

    def of(self, scope: str) -> tuple[Setting, ...]:
        """The settings in one scope."""
        return self.app if scope == "app" else self.user

    def named(self, scope: str, name: str) -> Setting | None:
        """One setting by name, or None if the plugin never asked for it."""
        return next((one for one in self.of(scope) if one.name == name), None)


def settings_in(given: object) -> Settings:
    """What a plugin's `settings` table asks for, checked before it is drawn.

    Strict, like the rest of the manifest: a setting that could never be
    drawn — a kind nobody knows, a choice with nothing to choose — refuses
    the plugin with a sentence for its author, rather than becoming a field
    that quietly does nothing.
    """
    if given is None:
        return Settings()
    if not isinstance(given, dict):
        raise PluginError("`settings` has to be a table with `app` and `user` lists")
    unknown = sorted(str(key) for key in given if key not in SCOPES)
    if unknown:
        raise PluginError(f"`settings` has `app` and `user`, not “{unknown[0]}”")
    return Settings(
        app=_scope("app", given.get("app")),
        user=_scope("user", given.get("user")),
    )


def _scope(scope: str, given: object) -> tuple[Setting, ...]:
    """One scope's list of settings, checked."""
    if given is None:
        return ()
    if not isinstance(given, list):
        raise PluginError(f"`settings.{scope}` has to be a list of tables")
    if len(given) > MOST_SETTINGS:
        raise PluginError(f"`settings.{scope}` asks for more than {MOST_SETTINGS} settings")

    made: list[Setting] = []
    for entry in given:
        if not isinstance(entry, dict):
            raise PluginError(f"every entry in `settings.{scope}` has to be a table")
        setting = _setting(scope, entry)
        if any(one.name == setting.name for one in made):
            raise PluginError(f"setting “{setting.name}” is in `settings.{scope}` twice")
        made.append(setting)
    return tuple(made)


def _setting(scope: str, entry: dict[str, object]) -> Setting:
    """One setting, checked."""
    # The name is a form field's and a database row's, so it must be plain.
    name = str(entry.get("name") or "").strip()
    if not name or not set(name) <= PLAIN or len(name) > 64:
        raise PluginError(f"a setting in `settings.{scope}` needs a plain `name`")
    where = f"setting “{name}”"

    kind = str(entry.get("type") or "text").strip().lower()
    if kind not in KINDS:
        allowed = ", ".join(f"“{one}”" for one in KINDS)
        raise PluginError(f"{where}: `type` has to be one of {allowed}, not “{kind}”")

    choices = _choices(where, entry.get("choices")) if kind == "choice" else ()
    default = _default(where, kind, entry.get("default"), choices)
    return Setting(
        name=name,
        label=str(entry.get("label") or name.replace("_", " ").capitalize())[:80],
        kind=kind,
        default=default,
        hint=" ".join(str(entry.get("hint") or "").split())[:300],
        placeholder=str(entry.get("placeholder") or "")[:80],
        choices=choices,
    )


def _choices(where: str, given: object) -> tuple[tuple[str, str], ...]:
    """A choice's options: plain strings, or tables of `value` and `label`."""
    if not isinstance(given, list) or not given:
        raise PluginError(f"{where}: a choice needs a list of `choices`")
    made: list[tuple[str, str]] = []
    for one in given:
        if isinstance(one, dict):
            value = str(one.get("value") or "").strip()
            label = str(one.get("label") or value)
        else:
            value = label = str(one).strip()
        if not value:
            raise PluginError(f"{where}: every choice needs a value")
        made.append((value, label[:80]))
    return tuple(made)


def _default(
    where: str, kind: str, given: object, choices: tuple[tuple[str, str], ...]
) -> str:
    """A setting's default, as the form would send it."""
    if kind == "toggle":
        return "1" if given is True else ""
    if given is None:
        # A choice with nothing said starts on its first option: a list with
        # nothing picked is a question nobody asked.
        return choices[0][0] if choices else ""
    value = str(given)
    if kind == "number":
        try:
            float(value)
        except ValueError:
            raise PluginError(f"{where}: the default “{value}” is not a number") from None
    if choices and value not in {one for one, _ in choices}:
        raise PluginError(f"{where}: the default “{value}” is not one of its choices")
    return value
