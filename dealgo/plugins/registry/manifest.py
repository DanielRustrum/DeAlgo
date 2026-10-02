"""Understanding the table a plugin returns: what it asks for and what it offers.

Everything here takes whatever came back and either makes sense of it or
raises a PluginError saying what is wrong, in words for the plugin's author.
"""

from __future__ import annotations

from typing import Any

# Re-exported, so that a caller handling what a plugin did wrong does not have
# to know which module the sentence came from. Said with `as` rather than with
# an `__all__`, which would also hide every function here from the reference.
from ..runtime import PluginError
from .plugin import AUGMENTS, Asked, Augmentation, Field, Plugin, SourceKind
from .storage import PLAIN


def wants_in(given: object) -> list[Asked]:
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


def publisher_in(given: object) -> tuple[dict[str, Any], dict[str, int]]:
    """How a plugin writes back to its own service.

    Only the names the host asks by. A plugin offering something nobody here
    calls is offering nothing, and a plugin missing one simply cannot do that
    — the host says so rather than failing at the call.
    """
    if given is None:
        return {}, {}
    if not isinstance(given, dict):
        raise PluginError("`publisher` has to be a table")

    # The calls the host makes, where the plugin offers them.
    doing = {
        name: given[name]
        for name in (
            "resolve", "describe", "details", "whoami",
            "playlists", "playlist", "create", "rename",
            "contents", "add", "remove",
        )
        if callable(given.get(name))
    }
    # What each call costs against the quota; anything unreadable is left at the default.
    prices: dict[str, int] = {}
    asked = given.get("costs")
    if isinstance(asked, dict):
        for name, value in asked.items():
            try:
                prices[str(name)] = max(1, int(float(str(value))))
            except (TypeError, ValueError):
                continue
    return doing, prices


def augmentations_in(plugin: Plugin, given: object) -> list[Augmentation]:
    """What a plugin adds to the app's boxes, checked before it is drawn.

    Each says which box it slots under and answers the question that box
    asks: `keep` for a Filter, `rank` for a Sort. Both are checked here, so
    an augmentation that could never do anything is a plugin that does not
    load rather than a piece that quietly sits there.
    """
    if given is None:
        return []
    if not isinstance(given, list):
        raise PluginError("`augmentations` has to be a list of tables")

    made: list[Augmentation] = []
    for entry in given:
        if not isinstance(entry, dict):
            raise PluginError("every entry in `augmentations` has to be a table")
        # The kind becomes half of the piece's ref, `plugin:kind`, so it must be a plain name.
        name = str(entry.get("kind") or "").strip()
        if not name:
            raise PluginError("an augmentation needs a `kind`")
        if not set(name) <= PLAIN:
            raise PluginError(f"“{name}” is not a usable augmentation kind")

        # Where it slots decides which hook it needs: `keep` under a Filter, `rank` under a Sort.
        under = str(entry.get("under") or "filter").strip().lower()
        wanted = AUGMENTS.get(under)
        if wanted is None:
            named = " or ".join(f"“{one}”" for one in AUGMENTS)
            raise PluginError(
                f"augmentation “{name}”: `under` has to be {named}, not “{under}”"
            )
        if not callable(entry.get(wanted)):
            raise PluginError(
                f"augmentation “{name}” goes under a {under}, "
                f"so it needs a `{wanted}` function"
            )
        made.append(
            Augmentation(
                ref=f"{plugin.id}:{name}",
                kind=name,
                label=str(entry.get("label") or name.title()),
                blurb=str(entry.get("blurb") or ""),
                fields=_fields(name, entry.get("fields")),
                plugin=plugin.title,
                plugin_id=plugin.id,
                under=under,
                _keep=entry.get("keep"),
                _rank=entry.get("rank"),
            )
        )
    return made


def declared_in(made: dict[str, object]) -> object:
    """What a plugin's file offered, under either name.

    `nodes` was the name when what a plugin declared was a box of its own.
    It is an augmentation of one of the app's boxes now, and `augmentations`
    is what to call it — but a plugin written against the old name still
    reads, because nothing about what it declares has changed.
    """
    offered = made.get("augmentations")
    return made.get("nodes") if offered is None else offered


def _fields(node: str, given: object) -> tuple[Field, ...]:
    """The settings an augmentation asks for, checked; raises `PluginError` if malformed."""
    if given is None:
        return ()
    if not isinstance(given, list):
        raise PluginError(f"augmentation “{node}”: `fields` has to be a list of tables")
    made: list[Field] = []
    for entry in given:
        if not isinstance(entry, dict):
            raise PluginError(f"augmentation “{node}”: every field has to be a table")
        name = str(entry.get("name") or "").strip()
        if not name or not set(name) <= PLAIN:
            raise PluginError(f"augmentation “{node}”: a field needs a plain `name`")
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


def sources_in(plugin: Plugin, given: object) -> list[SourceKind]:
    """The source kinds a plugin declares, checked before they are believed."""
    if given is None:
        return []
    if not isinstance(given, list):
        raise PluginError("`sources` has to be a list of tables")

    kinds: list[SourceKind] = []
    for entry in given:
        if not isinstance(entry, dict):
            raise PluginError("every entry in `sources` has to be a table")
        # The kind is stored on every source of it, so it must be a plain name.
        name = str(entry.get("kind") or "").strip()
        if not name:
            raise PluginError("a source needs a `kind`")
        if not set(name) <= PLAIN:
            raise PluginError(f"“{name}” is not a usable kind name")
        if not callable(entry.get("recognise")):
            raise PluginError(f"“{name}” needs a `recognise` function")
        # Every other hook is optional; `recognise` is the one the app cannot do without.
        kinds.append(
            SourceKind(
                kind=name,
                label=str(entry.get("label") or name.title()),
                example=str(entry.get("example") or ""),
                playlistable=entry.get("playlistable") is True,
                plugin=plugin.title,
                noun=str(entry.get("noun") or entry.get("label") or name.title()),
                blurb=str(entry.get("blurb") or ""),
                _recognise=entry.get("recognise"),
                _accept=entry.get("accept"),
                _item_url=entry.get("item_url"),
                _mirror=entry.get("mirror"),
                _refine=entry.get("refine"),
                _posts=entry.get("posts"),
                _home=entry.get("home"),
            )
        )
    return kinds
