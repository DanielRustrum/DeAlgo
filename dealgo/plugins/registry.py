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
from collections.abc import Callable
from pathlib import Path
from typing import Any

from . import permissions
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


@dataclass(frozen=True)
class Asked:
    """One permission a plugin wants, and the reason it gave.

    The reason is the plugin's own words. It is shown to the person deciding
    and never acted on: a plugin explaining itself is not a plugin being
    believed.
    """

    name: str
    why: str

    @property
    def known(self) -> bool:
        return self.name in permissions.BY_NAME

    @property
    def detail(self) -> permissions.Permission:
        return permissions.describe(self.name)


@dataclass(frozen=True)
class Field:
    """One setting on a plugin's box, as its popover will draw it."""

    name: str
    label: str
    #: "text" or "number". Anything else is drawn as text, because a field
    #: nobody can fill in is worse than one drawn plainly.
    type: str = "text"
    default: str = ""
    placeholder: str = ""


@dataclass(frozen=True)
class NodeKind:
    """A box a plugin puts in the palette.

    It is a filter: given an item and whatever its fields were set to, it
    answers whether that item may carry on down the path. A pure question
    with a yes-or-no answer, which is the one shape that fits inside the
    sandbox — no network, no database, nothing to be trusted with.
    """

    #: Unique across every plugin, because a node has to be found again from
    #: what is stored against it. Written "<plugin>:<node>".
    ref: str
    kind: str
    label: str
    blurb: str
    fields: tuple[Field, ...]
    plugin: str
    plugin_id: str
    _keep: Any = None


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
    nodes: list[NodeKind] = field(default_factory=list)
    #: What it asked for, in the order it asked.
    wants: list[Asked] = field(default_factory=list)
    #: What it actually has. Never more than it asked for, and never anything
    #: this version does not understand.
    granted: frozenset[str] = frozenset()
    box: Sandbox | None = None
    #: What the file said it was, for showing on the Admin page even when the
    #: rest of it was refused.
    api: int = 0
    #: The shipped plugin this one stands in for, when somebody has put their
    #: own copy in the data folder. Worth saying out loud: a stale override is
    #: otherwise indistinguishable from a bug in De-Algo.
    replaces: Path | None = None
    #: Switched off by hand. It still loaded, and everything about it is
    #: still readable — it simply offers nothing while it is off, which is
    #: the only way to turn off a plugin that ships in the image.
    paused: bool = False

    @property
    def ok(self) -> bool:
        """Loaded, and switched on. The two are different questions and the
        page asks them separately: a paused plugin is not a broken one."""
        return self.trouble is None and not self.paused

    @property
    def loaded(self) -> bool:
        """It made sense, whether or not it is switched on."""
        return self.trouble is None

    @property
    def title(self) -> str:
        return self.name or self.id

    @property
    def wanting(self) -> list[Asked]:
        """What it asked for and has not been given.

        Shown on its row, because a plugin quietly doing less than it was
        written to do is the hardest kind of broken to notice.
        """
        return [want for want in self.wants if want.name not in self.granted]


@dataclass
class Registry:
    """Every plugin the folder held, in the order they were read."""

    plugins: list[Plugin] = field(default_factory=list)

    @property
    def working(self) -> list[Plugin]:
        return [plugin for plugin in self.plugins if plugin.ok]

    @property
    def broken(self) -> list[Plugin]:
        """Ones that did not load. A paused plugin is not among them: it is
        working fine and has been asked to stand down."""
        return [plugin for plugin in self.plugins if plugin.trouble is not None]

    @property
    def paused(self) -> list[Plugin]:
        return [plugin for plugin in self.plugins if plugin.paused]

    def source_kinds(self) -> list[SourceKind]:
        return [kind for plugin in self.working for kind in plugin.sources]

    def node_kinds(self) -> list[NodeKind]:
        return [kind for plugin in self.working for kind in plugin.nodes]

    def node(self, ref: str) -> NodeKind | None:
        return next((k for k in self.node_kinds() if k.ref == ref), None)

    def keeps(self, ref: str, item: dict[str, object], settings: dict[str, str]) -> bool:
        """Whether a plugin's box lets this item carry on.

        A box that throws, or answers with something that is not a yes or a
        no, lets the item by. A filter nobody can read the mind of should not
        silently swallow a feed: the failure belongs in the log, and the item
        belongs wherever it was going.
        """
        found = self.node(ref)
        if found is None or found._keep is None:
            return True
        plugin = next((p for p in self.working if p.id == found.plugin_id), None)
        if plugin is None or plugin.box is None:
            return True
        try:
            said = plugin.box.call(
                found._keep, plugin.box.table(**item), plugin.box.table(**settings)
            )
        except PluginError as exc:
            log.warning("%s could not judge an item: %s", found.plugin, exc)
            return True
        return said is not False

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
            _loaded = _everything()
        return _loaded


def reload() -> Registry:
    """Read the folders again. What the Admin page's button does, what an
    upload does once the file has landed, and what switching one on or off
    does — the switch changes what the registry offers, so the registry has
    to be built again to offer it."""
    global _loaded
    with _lock:
        _loaded = _everything()
        return _loaded


def _everything() -> Registry:
    """Both folders, with the switches and the grants applied."""
    from ..services.sync import http_client

    off, granted = _state()
    return read(shipped(), folder(), paused=off, granted=granted, http=http_client)


def _state() -> tuple[frozenset[str], dict[str, frozenset[str]]]:
    """Which plugins are off, and what each has been granted.

    One read for both, because they live in one row. A database that cannot
    be reached is read as "everything on, nothing granted": the safe way
    round, since a plugin quietly keeping a capability through a failed query
    is the one outcome nobody would want.
    """
    import json

    from ..db import session_scope
    from ..models import PluginState

    try:
        with session_scope() as session:
            off: set[str] = set()
            granted: dict[str, frozenset[str]] = {}
            for row in session.query(PluginState):
                if not row.enabled:
                    off.add(row.plugin_id)
                granted[row.plugin_id] = _names(row.granted)
            return frozenset(off), granted
    except Exception:  # pragma: no cover - a database that is not there yet
        log.warning("could not read plugin state; nothing is granted")
        return frozenset(), {}


def _names(stored: str | None) -> frozenset[str]:
    import json

    if not stored:
        return frozenset()
    try:
        loaded = json.loads(stored)
    except (TypeError, ValueError):
        return frozenset()
    if not isinstance(loaded, list):
        return frozenset()
    return frozenset(str(name) for name in loaded)


def paused_ids() -> frozenset[str]:
    """Which plugins have been switched off."""
    return _state()[0]


def set_granted(plugin_id: str, names: frozenset[str]) -> None:
    """Record what a person granted a plugin, and hand it over.

    Only names this version understands are kept: a grant for a permission
    that has since been removed from the vocabulary would be a row nobody can
    read, and quietly dropping it is better than storing a promise that
    cannot be honoured.
    """
    import json

    from ..db import session_scope
    from ..models import PluginState, utcnow

    kept = sorted(name for name in names if name in permissions.BY_NAME)
    with session_scope() as session:
        row = (
            session.query(PluginState)
            .filter(PluginState.plugin_id == plugin_id)
            .one_or_none()
        )
        if row is None:
            row = PluginState(plugin_id=plugin_id)
            session.add(row)
        row.granted = json.dumps(kept)
        row.changed_at = utcnow()
    reload()


def read(
    *folders: Path,
    given: dict[str, object] | None = None,
    paused: frozenset[str] = frozenset(),
    granted: dict[str, frozenset[str]] | None = None,
    http: Callable[[], Any] | None = None,
) -> Registry:
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
            _grant(plugin, (granted or {}).get(plugin.id, frozenset()), http)
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


def set_paused(plugin_id: str, *, paused: bool) -> None:
    """Switch a plugin off, or back on, and rebuild what is offered."""
    from ..db import session_scope
    from ..models import PluginState, utcnow

    with session_scope() as session:
        row = (
            session.query(PluginState)
            .filter(PluginState.plugin_id == plugin_id)
            .one_or_none()
        )
        if row is None:
            row = PluginState(plugin_id=plugin_id)
            session.add(row)
        row.enabled = not paused
        row.changed_at = utcnow()
    reload()


def judge(stem: str, source: str) -> Plugin:
    """Load a plugin from text, without keeping it.

    What an upload is checked with: a file that will not load is one nobody
    wants in the folder, and saying so before it lands beats a broken row on
    the page afterwards.
    """
    plugin = Plugin(id=stem, path=Path(f"{stem}.lua"))
    return _judge(plugin, source, {})


def _one(path: Path, given: dict[str, object]) -> Plugin:
    """Read one file, and turn anything that goes wrong into a sentence.

    Twice, when it has been granted something. The first pass is with an
    empty world, which is how its manifest is read without its own code ever
    having had a capability in scope; only then is it loaded again with what
    it was actually granted. A plugin cannot talk its way into a permission
    by what it does while being read.
    """
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
        plugin.wants = _wants(made.get("permissions"))
        plugin.sources = _sources(plugin, made.get("sources"))
        plugin.nodes = _nodes(plugin, made.get("nodes"))
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

    def able(lua: Any) -> dict[str, object]:
        return permissions.capabilities(plugin.title, plugin.granted, http, lua)

    try:
        source = plugin.path.read_text(encoding="utf-8")
        box, made = load(plugin.path.name, source, given=able)
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
        plugin.sources = _sources(plugin, made.get("sources"))
        plugin.nodes = _nodes(plugin, made.get("nodes"))
    except PluginError as exc:  # pragma: no cover - it parsed a moment ago
        plugin.trouble = str(exc)


def _wants(given: object) -> list[Asked]:
    """The permissions a plugin asks for, and why.

    A reason is required. "network" with no explanation is a request nobody
    can weigh, and refusing it here means the person deciding always has
    something to decide on.
    """
    if given is None:
        return []
    if not isinstance(given, list):
        raise PluginError("`permissions` has to be a list of tables")

    asked: list[Asked] = []
    seen: set[str] = set()
    for entry in given:
        if not isinstance(entry, dict):
            raise PluginError("every entry in `permissions` has to be a table")
        name = str(entry.get("name") or "").strip()
        why = " ".join(str(entry.get("why") or "").split())
        if not name:
            raise PluginError("a permission needs a `name`")
        if not why:
            raise PluginError(f"permission “{name}” needs a `why` — say what it is for")
        if name in seen:
            raise PluginError(f"permission “{name}” is asked for twice")
        seen.add(name)
        asked.append(Asked(name=name, why=why[:400]))
    return asked


def _nodes(plugin: Plugin, given: object) -> list[NodeKind]:
    """The boxes a plugin puts in the palette, checked before they are drawn."""
    if given is None:
        return []
    if not isinstance(given, list):
        raise PluginError("`nodes` has to be a list of tables")

    made: list[NodeKind] = []
    for entry in given:
        if not isinstance(entry, dict):
            raise PluginError("every entry in `nodes` has to be a table")
        name = str(entry.get("kind") or "").strip()
        if not name:
            raise PluginError("a node needs a `kind`")
        if not set(name) <= PLAIN:
            raise PluginError(f"“{name}” is not a usable node kind")
        if not callable(entry.get("keep")):
            raise PluginError(f"node “{name}” needs a `keep` function")
        made.append(
            NodeKind(
                ref=f"{plugin.id}:{name}",
                kind=name,
                label=str(entry.get("label") or name.title()),
                blurb=str(entry.get("blurb") or ""),
                fields=_fields(name, entry.get("fields")),
                plugin=plugin.title,
                plugin_id=plugin.id,
                _keep=entry.get("keep"),
            )
        )
    return made


def _fields(node: str, given: object) -> tuple[Field, ...]:
    if given is None:
        return ()
    if not isinstance(given, list):
        raise PluginError(f"node “{node}”: `fields` has to be a list of tables")
    made: list[Field] = []
    for entry in given:
        if not isinstance(entry, dict):
            raise PluginError(f"node “{node}”: every field has to be a table")
        name = str(entry.get("name") or "").strip()
        if not name or not set(name) <= PLAIN:
            raise PluginError(f"node “{node}”: a field needs a plain `name`")
        made.append(
            Field(
                name=name,
                label=str(entry.get("label") or name.replace("_", " ").title()),
                type="number" if entry.get("type") == "number" else "text",
                default=str(entry.get("default") or ""),
                placeholder=str(entry.get("placeholder") or ""),
            )
        )
    return tuple(made)


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
