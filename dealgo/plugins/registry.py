"""What plugins there are, what each one offers, and what went wrong.

A plugin is one ``.lua`` file in the plugins folder. This reads them all on
start, judges what each returned, and keeps the ones that make sense — with
a note against the ones that do not, because a plugin that quietly fails to
load is worse than one that says why.

Nothing is thrown away on a bad plugin. A file that will not parse, or comes
back without the fields it needs, becomes a row on the Admin page saying so;
the rest of the app carries on with the plugins that did load.

Held in memory and rebuilt on demand rather than stored: the folder is the
truth, and a registry that could disagree with it would be a second place to
look when something is missing.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .runtime import PluginError, Sandbox, load

log = logging.getLogger(__name__)

#: The version of the plugin API this host speaks. A plugin says which it was
#: written against, and one written against a later version is refused rather
#: than half-run.
API = 1

#: A plugin id has to survive being a filename, a form field and a CSS class.
PLAIN = frozenset("abcdefghijklmnopqrstuvwxyz0123456789-_")


@dataclass(frozen=True)
class Recognised:
    """What a reference turned out to be, according to a plugin."""

    kind: str
    key: str
    feed_url: str
    title: str
    plugin: str
    #: True when the plugin knows the kind but cannot finish alone — the one
    #: case being a YouTube handle, which needs the Google connection.
    needs_host: bool = False
    #: True when the plugin is offering rather than asserting. A certain
    #: answer from anybody beats every guess.
    guess: bool = False


@dataclass(frozen=True)
class SourceKind:
    """A kind of somewhere to watch, as a plugin describes it."""

    kind: str
    label: str
    example: str
    playlistable: bool
    #: Which plugin this came from, for the Admin page and for errors.
    plugin: str
    _recognise: Any = None
    _item_url: Any = None
    _mirror: Any = None


@dataclass
class Plugin:
    """One file in the plugins folder, loaded or not."""

    id: str
    path: Path
    name: str = ""
    version: str = ""
    #: None while it is fine. A sentence when it is not, and then nothing
    #: else on this object is to be trusted.
    trouble: str | None = None
    sources: list[SourceKind] = field(default_factory=list)
    box: Sandbox | None = None
    #: What the file said it was, for showing on the Admin page even when the
    #: rest of it was refused.
    api: int = 0
    #: The shipped plugin this one stands in for, when somebody has put their
    #: own copy in the data folder. Worth saying out loud: a stale override is
    #: otherwise indistinguishable from a bug in De-Algo.
    replaces: Path | None = None

    @property
    def ok(self) -> bool:
        return self.trouble is None

    @property
    def title(self) -> str:
        return self.name or self.id


@dataclass
class Registry:
    """Every plugin the folder held, in the order they were read."""

    plugins: list[Plugin] = field(default_factory=list)

    @property
    def working(self) -> list[Plugin]:
        return [plugin for plugin in self.plugins if plugin.ok]

    @property
    def broken(self) -> list[Plugin]:
        return [plugin for plugin in self.plugins if not plugin.ok]

    def source_kinds(self) -> list[SourceKind]:
        return [kind for plugin in self.working for kind in plugin.sources]

    def kind(self, name: str) -> SourceKind | None:
        return next((k for k in self.source_kinds() if k.kind == name), None)

    def recognise(self, reference: str) -> "Recognised | None":
        """Ask every plugin whose reference this is.

        A certain answer beats a guess, whoever answered first. Some kinds
        are recognisable outright — "r/python" is a subreddit and nothing
        else — while others can only be guessed at: a Bluesky handle may be
        any domain at all, so "example.com" *might* be one and might equally
        be a newsletter nobody has written a plugin for yet.

        Without that distinction the answer would depend on filename order,
        and "name.substack.com" would be read as a Bluesky account because
        B comes before S.

        A plugin that throws while recognising has failed at the one thing it
        was asked; it is left out of the answer rather than taking the whole
        attempt down with it.
        """
        typed = (reference or "").strip()
        if not typed:
            return None
        guess: Recognised | None = None
        for plugin in self.working:
            for kind in plugin.sources:
                if plugin.box is None or kind._recognise is None:
                    continue
                try:
                    said = plugin.box.call(kind._recognise, typed)
                except PluginError as exc:
                    log.warning("%s could not read %r: %s", plugin.title, typed, exc)
                    continue
                if not isinstance(said, dict):
                    continue
                key = str(said.get("key") or "").strip()
                if not key:
                    continue
                answer = Recognised(
                    kind=kind.kind,
                    key=key,
                    feed_url=str(said.get("feed") or "").strip(),
                    title=str(said.get("title") or key),
                    plugin=plugin.title,
                    # A plugin may know what something is without being able
                    # to finish: a YouTube @handle needs this account's Google
                    # connection, which is not a plugin's to hold.
                    needs_host=said.get("needs_host") is True,
                    guess=said.get("guess") is True,
                )
                if not answer.guess:
                    return answer
                guess = guess or answer
        return guess

    def mirror(self, kind: str, key: str) -> str | None:
        """A second address for the same feed, where the plugin offers one."""
        said = self._ask(kind, "_mirror", key)
        return said if isinstance(said, str) and said else None

    def _ask(self, kind: str, hook: str, *args: object) -> object:
        """Call one of a kind's optional functions, or give back None.

        A plugin that throws here has failed at something optional; it is
        worth a line in the log and nothing more, because the caller has a
        perfectly good answer without it.
        """
        found = self.kind(kind)
        if found is None:
            return None
        fn = getattr(found, hook, None)
        if fn is None:
            return None
        plugin = next((p for p in self.working if p.title == found.plugin), None)
        if plugin is None or plugin.box is None:
            return None
        try:
            return plugin.box.call(fn, *args)
        except PluginError as exc:
            log.warning("%s could not answer %s: %s", found.plugin, hook.strip("_"), exc)
            return None

    def item_url(self, kind: str, key: str, link: str | None) -> str | None:
        """Where one of this kind's items lives, if its plugin says so."""
        said = self._ask(kind, "_item_url", key, link)
        return said if isinstance(said, str) and said else link


_lock = threading.Lock()
_loaded: Registry | None = None


def shipped() -> Path:
    """The plugins that come with De-Algo. Read-only, and replaced wholesale
    by an upgrade, so a new version's YouTube plugin arrives with it."""
    return Path(__file__).resolve().parent / "builtin"


def folder() -> Path:
    """Where a person's own plugins live. Beside the database, so they
    survive an upgrade and travel with a backup of the data volume."""
    from ..config import CONFIG

    return CONFIG.data_dir / "plugins"


def current() -> Registry:
    """The registry as it stands, reading the folders on first use."""
    global _loaded
    with _lock:
        if _loaded is None:
            _loaded = read(shipped(), folder())
        return _loaded


def reload() -> Registry:
    """Read the folders again. What the Admin page's button does, and what an
    upload does once the file has landed."""
    global _loaded
    with _lock:
        _loaded = read(shipped(), folder())
        return _loaded


def read(*folders: Path, given: dict[str, object] | None = None) -> Registry:
    """Load every ``.lua`` in each folder, in name order.

    Name order so the list is the same on every start: which plugin owns a
    source kind should not depend on how the filesystem feels.

    Later folders win. The shipped plugins are read first and a person's own
    second, so dropping a `youtube.lua` into the data folder replaces the one
    that came with De-Algo rather than fighting it — which is the only way to
    change a shipped plugin without editing the image.
    """
    found = Registry()
    by_id: dict[str, Plugin] = {}
    for where in folders:
        if not where.is_dir():
            continue
        for path in sorted(where.glob("*.lua")):
            plugin = _one(path, given or {})
            earlier = by_id.get(plugin.id)
            if earlier is not None:
                found.plugins.remove(earlier)
                plugin.replaces = earlier.path
            by_id[plugin.id] = plugin
            found.plugins.append(plugin)

    claimed: dict[str, str] = {}
    for plugin in found.plugins:
        # Two plugins cannot both own a source kind: the second to ask is
        # refused, and told which one has it.
        for kind in list(plugin.sources):
            owner = claimed.get(kind.kind)
            if owner is not None:
                plugin.sources.remove(kind)
                plugin.trouble = f"“{kind.kind}” is already provided by {owner}"
            else:
                claimed[kind.kind] = plugin.title
    return found


def judge(stem: str, source: str) -> Plugin:
    """Load a plugin from text, without keeping it.

    What an upload is checked with: a file that will not load is one nobody
    wants in the folder, and saying so before it lands beats a broken row on
    the page afterwards.
    """
    plugin = Plugin(id=stem, path=Path(f"{stem}.lua"))
    return _judge(plugin, source, {})


def _one(path: Path, given: dict[str, object]) -> Plugin:
    """Read one file, and turn anything that goes wrong into a sentence."""
    plugin = Plugin(id=path.stem, path=path)
    try:
        source = path.read_text(encoding="utf-8")
    except OSError as exc:
        plugin.trouble = f"could not be read: {exc}"
        return plugin
    except UnicodeDecodeError:
        plugin.trouble = "is not text"
        return plugin

    return _judge(plugin, source, given)


def _judge(plugin: Plugin, source: str, given: dict[str, object]) -> Plugin:
    """Run a plugin's file and decide what it turned out to be."""
    path = plugin.path
    try:
        box, made = load(path.name, source, given=given)
    except PluginError as exc:
        plugin.trouble = str(exc).split(": ", 1)[-1]
        return plugin

    if not isinstance(made, dict):
        plugin.trouble = "did not end with `return { … }`"
        return plugin

    plugin.box = box
    plugin.name = str(made.get("name") or path.stem)
    plugin.version = str(made.get("version") or "")
    plugin.api = int(made.get("api") or 0)

    if plugin.api != API:
        plugin.trouble = (
            f"is written for plugin API {plugin.api or 'none'}, and this is {API}"
        )
        return plugin
    if not set(plugin.id) <= PLAIN:
        plugin.trouble = "has a name outside a-z, 0-9, dash and underscore"
        return plugin

    try:
        plugin.sources = _sources(plugin, made.get("sources"))
    except PluginError as exc:
        plugin.trouble = str(exc)
        return plugin
    return plugin


def _sources(plugin: Plugin, given: object) -> list[SourceKind]:
    """The source kinds a plugin declares, checked before they are believed."""
    if given is None:
        return []
    if not isinstance(given, list):
        raise PluginError("`sources` has to be a list of tables")

    kinds: list[SourceKind] = []
    for entry in given:
        if not isinstance(entry, dict):
            raise PluginError("every entry in `sources` has to be a table")
        name = str(entry.get("kind") or "").strip()
        if not name:
            raise PluginError("a source needs a `kind`")
        if not set(name) <= PLAIN:
            raise PluginError(f"“{name}” is not a usable kind name")
        if not callable(entry.get("recognise")):
            raise PluginError(f"“{name}” needs a `recognise` function")
        kinds.append(
            SourceKind(
                kind=name,
                label=str(entry.get("label") or name.title()),
                example=str(entry.get("example") or ""),
                playlistable=entry.get("playlistable") is True,
                plugin=plugin.title,
                _recognise=entry.get("recognise"),
                _item_url=entry.get("item_url"),
                _mirror=entry.get("mirror"),
            )
        )
    return kinds
