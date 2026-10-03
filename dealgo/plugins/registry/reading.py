"""Reading plugins from their folders, and judging what each turned out to be."""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .. import capabilities

# Re-exported, so that a caller handling what a plugin did wrong does not have
# to know which module the sentence came from. Said with `as` rather than with
# an `__all__`, which would also hide every function here from the reference.
from ..runtime import PluginError, load
from .manifest import augmentations_in, declared_in, publisher_in, sources_in, wants_in
from .offers import Registry
from .plugin import API, Plugin
from .settings import settings_in
from .storage import ENTRY, PLAIN, home_of, inside

log = logging.getLogger(__name__)


def read(
    *folders: Path,
    given: dict[str, object] | None = None,
    paused: frozenset[str] = frozenset(),
    granted: dict[str, frozenset[str]] | None = None,
    trusted: Path | None = None,
    http: Callable[[], Any] | None = None,
) -> Registry:
    """Load every plugin in each folder, in name order.

    A plugin is a folder of its own — ``<id>/plugin.lua`` — so that it can
    grow more than one file without the folder above it becoming a heap.
    A loose ``<id>.lua`` is still read, because that is the shape every
    plugin had until now and nobody's should stop loading; `settle` moves
    one into a folder of its own the next time De-Algo starts.

    Name order so the list is the same on every start: which plugin owns a
    source kind should not depend on how the filesystem feels.

    Later folders win. The shipped plugins are read first and a person's own
    second, so dropping a `youtube.lua` into the data folder replaces the one
    that came with De-Algo rather than fighting it — which is the only way to
    change a shipped plugin without editing the image.

    ``trusted`` is the folder whose plugins start with what they asked for.
    That is the shipped folder and nothing else: those arrive inside the
    image, they are how De-Algo does the things it has always done, and
    nobody chose to install them — so there is no moment at which a consent
    popup would have been shown. They are still listed with everything they
    hold, and every one of them can be revoked on the Admin page.
    """
    found = Registry()
    by_id: dict[str, Plugin] = {}
    for where in folders:
        if not where.is_dir():
            continue
        for path in inside(where):
            plugin = _one(path, given or {})
            stored = (granted or {}).get(plugin.id)
            if stored is None and trusted is not None and where == trusted:
                # Never decided on, and shipped: it holds what it asked for
                # until somebody says otherwise. A stored empty set is a
                # decision and is left alone.
                stored = frozenset(want.name for want in plugin.wants)
            _grant(plugin, stored or frozenset(), http)
            earlier = by_id.get(plugin.id)
            if earlier is not None:
                found.plugins.remove(earlier)
                plugin.replaces = earlier.path
            by_id[plugin.id] = plugin
            found.plugins.append(plugin)

    for plugin in found.plugins:
        plugin.paused = plugin.id in paused

    claimed: dict[str, str] = {}
    for plugin in found.plugins:
        if plugin.paused:
            # It offers nothing while it is off, so it claims nothing either
            # — which is what makes a paused plugin the way to hand a source
            # kind over to a replacement.
            continue
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
    # A path it does not have yet: it is being read, not kept, and where it
    # would land is the caller's to decide once somebody has agreed to it.
    plugin = Plugin(id=stem, path=Path(stem) / ENTRY)
    return _judge(plugin, source, {})


def _one(path: Path, given: dict[str, object]) -> Plugin:
    """Read one file, and turn anything that goes wrong into a sentence.

    Twice, when it has been granted something. The first pass is with an
    empty world, which is how its manifest is read without its own code ever
    having had a capability in scope; only then is it loaded again with what
    it was actually granted. A plugin cannot talk its way into a permission
    by what it does while being read.
    """
    plugin = Plugin(id=home_of(path).name, path=path)
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
    """Run a plugin's file and decide what it turned out to be.

    With a `dealgo` that has been granted nothing. It is in scope so that a
    plugin can be written against it unconditionally, and it answers nothing
    about anybody — the capabilities that actually do something arrive on the
    second pass, once there is a manifest to weigh them against.
    """
    def nothing_yet(lua: Any) -> dict[str, object]:
        """The plugin's world for the first pass: a `dealgo` granted nothing,
        and its own settings, which need no permission to read."""
        return {
            **given,
            **capabilities.granted_to(plugin.id, frozenset(), None, lua),
            "settings": capabilities.PluginSettings(plugin),
        }

    try:
        box, made = load(plugin.id, source, given=nothing_yet, home=plugin.home)
    except PluginError as exc:
        plugin.trouble = str(exc).split(": ", 1)[-1]
        return plugin

    if not isinstance(made, dict):
        plugin.trouble = "did not end with `return { … }`"
        return plugin

    plugin.box = box
    # Its folder's name when it gives none. Not the file's: every plugin's
    # file is called plugin.lua, so that would title them all "plugin".
    plugin.name = str(made.get("name") or plugin.id)
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
        plugin.wants = wants_in(made.get("permissions"))
        plugin.settings = settings_in(made.get("settings"))
        plugin.sources = sources_in(plugin, made.get("sources"))
        plugin.augments = augmentations_in(plugin, declared_in(made))
        plugin.publishes, plugin.costs = publisher_in(made.get("publisher"))
    except PluginError as exc:
        plugin.trouble = str(exc)
        return plugin
    return plugin


def _grant(plugin: Plugin, allowed: frozenset[str], http: Callable[[], Any] | None) -> None:
    """Hand a plugin what it was granted, by loading it again with it.

    Only what it asked for, and only what this version understands: a grant
    stored against a permission that has since been removed from the
    vocabulary gives nothing, rather than giving something nobody can name.
    """
    wanted = {want.name for want in plugin.wants if want.known}
    plugin.granted = frozenset(allowed & wanted)
    if plugin.trouble is not None:
        return
    # Nothing to hand over and nothing to read back: a plugin that asked for
    # nothing already has the `dealgo` it will ever have, and loading it a
    # second time to give it the same thing would only cost a start-up.
    if not plugin.wants:
        return

    asked = tuple((want.name, want.why) for want in plugin.wants)

    def able(lua: Any) -> dict[str, object]:
        """The plugin's world with what it was granted."""
        return {
            **capabilities.granted_to(plugin.title, plugin.granted, http, lua, asked),
            "settings": capabilities.PluginSettings(plugin),
        }

    try:
        source = plugin.path.read_text(encoding="utf-8")
        box, made = load(plugin.id, source, given=able, home=plugin.home)
    except (OSError, UnicodeDecodeError, PluginError) as exc:
        # It loaded a moment ago with nothing, so this is something about the
        # capabilities themselves. It keeps what it had and is left with none.
        log.warning("%s could not be given what it was granted: %s", plugin.title, exc)
        plugin.granted = frozenset()
        return
    if not isinstance(made, dict):  # pragma: no cover - it was a dict a moment ago
        plugin.granted = frozenset()
        return

    plugin.box = box
    try:
        plugin.sources = sources_in(plugin, made.get("sources"))
        plugin.augments = augmentations_in(plugin, declared_in(made))
        plugin.publishes, plugin.costs = publisher_in(made.get("publisher"))
    except PluginError as exc:  # pragma: no cover - it parsed a moment ago
        plugin.trouble = str(exc)
