"""Where plugins live on disk, and putting them there.

Every plugin is a folder of its own. Everything about that shape is decided
here, so that adding one, fetching one and replacing one all produce the same
thing — and nothing written here can land outside the plugins folder.
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path, PurePosixPath

# Re-exported, so that a caller handling what a plugin did wrong does not have
# to know which module the sentence came from. Said with `as` rather than with
# an `__all__`, which would also hide every function here from the reference.
from ..runtime import PluginError

log = logging.getLogger(__name__)


#: What a plugin's own file is called inside its folder. A plugin is a folder
#: of its own so that it can grow more than one file without the folder above
#: it becoming a heap.
ENTRY = "plugin.lua"


#: A plugin id has to survive being a filename, a form field and a CSS class.
PLAIN = frozenset("abcdefghijklmnopqrstuvwxyz0123456789-_")


def shipped() -> Path:
    """The plugins that come with De-Algo. Read-only, and replaced wholesale
    by an upgrade, so a new version's YouTube plugin arrives with it."""
    return Path(__file__).resolve().parent.parent / "builtin"


def folder() -> Path:
    """Where a person's own plugins live. Beside the database, so they
    survive an upgrade and travel with a backup of the data volume."""
    from ...config import CONFIG

    return CONFIG.data_dir / "plugins"


def inside(where: Path) -> list[Path]:
    """Every plugin file in a folder, by the id it will load under.

    Both shapes: a folder of its own with `plugin.lua` in it, and the loose
    `<id>.lua` that every plugin was until now. A folder wins over a loose
    file of the same name, because that is the shape being moved to and
    `settle` leaves nothing behind when it moves one.
    """
    found: dict[str, Path] = {}
    for path in sorted(where.glob("*.lua")):
        if path.is_file():
            found[path.stem] = path
    for child in sorted(where.iterdir()):
        # A dot is the app's own, not somebody's plugin: a fetch waiting to
        # be agreed to lives in one, and must not load while it waits.
        if child.name.startswith("."):
            continue
        entry = child / ENTRY
        if child.is_dir() and entry.is_file():
            found[child.name] = entry
    return [found[name] for name in sorted(found)]


def home_of(path: Path) -> Path:
    """The folder a plugin lives in, whichever shape it is in.

    Its own folder, or the plugins folder for one that is still a loose
    file. What is beside it is the plugin's; what is above it is not.
    """
    return path.parent if path.name == ENTRY else path.parent / path.stem


def settle(where: Path) -> int:
    """Move every loose ``<id>.lua`` into a folder of its own.

    Run on start, so a plugins folder written by an older version becomes the
    shape this one keeps without anybody being asked to do anything. Moved
    rather than copied, so there is one file and not two claiming the same id.

    A loose file whose folder already exists is left where it is: something
    has already put a plugin there, and deciding which of the two somebody
    meant is not this function's to do.
    """
    if not where.is_dir():
        return 0
    moved = 0
    for path in sorted(where.glob("*.lua")):
        if not path.is_file() or path.name.startswith("."):
            continue
        home = where / path.stem
        if home.exists():
            log.warning(
                "%s and %s/ are both here; leaving the loose file alone",
                path.name, path.stem,
            )
            continue
        try:
            home.mkdir(parents=True)
            path.replace(home / ENTRY)
        except OSError as exc:  # pragma: no cover - a full or unwritable volume
            log.warning("could not move %s into a folder of its own: %s", path.name, exc)
            continue
        moved += 1
    if moved:
        log.info("moved %d plugin(s) into folders of their own", moved)
    return moved


#: Where a fetch puts what it downloaded while somebody decides about it.
#: A dot so that `inside` never mistakes it for a plugin, and inside the
#: plugins folder so that moving one into place is a rename rather than a
#: copy across a filesystem.
STAGING = ".staged"


def stage(plugin_id: str, source: str, extras: dict[str, bytes] | None = None) -> Path:
    """Hold a fetched plugin until somebody has agreed to it.

    Written down rather than carried through the form, for two reasons. A
    plugin may be more than one file, and a form field is a poor way to
    carry bytes somebody else chose. And what was read and judged is then
    exactly what lands — re-fetching on the way past consent would leave a
    gap in which the repository could become something else.
    """
    _staged(plugin_id)  # cleared, so a second fetch is not layered on a first
    return keep(plugin_id, source, extras, where=_staging())


def take_staged(plugin_id: str) -> bool:
    """Move what was staged into place, replacing whatever was there.

    Answers False where there is nothing staged, which is the ordinary case
    for a plugin that was uploaded rather than fetched.
    """
    held = _staged(plugin_id, clear=False)
    if held is None:
        return False
    home = folder() / plugin_id
    if home.exists():
        shutil.rmtree(home)
    held.replace(home)
    return True


def _staging() -> Path:
    """Where fetched plugins wait for consent: `plugins/.staged/`."""
    return folder() / STAGING


def _staged(plugin_id: str, *, clear: bool = True) -> Path | None:
    """Where a fetch of this plugin is being held, if anywhere.

    Only ever one directory directly inside the staging folder, named as a
    plugin id: this removes a tree, and the one thing it must never do is
    remove a tree somebody meant to keep.
    """
    if not plugin_id or not set(plugin_id) <= PLAIN:
        return None
    held = _staging() / plugin_id
    if not held.is_dir() or held.resolve().parent != _staging().resolve():
        return None
    if clear:
        shutil.rmtree(held)
        return None
    return held


def keep(
    plugin_id: str,
    source: str,
    extras: dict[str, bytes] | None = None,
    *,
    where: Path | None = None,
) -> Path:
    """Write a plugin into a folder of its own, and answer where it landed.

    Everything about the shape of a plugin on disk is decided here, so that
    adding one, fetching one and replacing one all produce the same thing.

    `extras` are whatever else came with it, by path relative to its folder.
    Checked here rather than trusted from wherever they came: a name with a
    separator or a `..` in it is refused outright rather than reduced to
    something safe, because a file landing somewhere nobody chose is worse to
    be surprised by than an error.
    """
    if not plugin_id or not set(plugin_id) <= PLAIN:
        raise PluginError(f"“{plugin_id}” is not a usable plugin name")
    home = (where or folder()) / plugin_id
    home.mkdir(parents=True, exist_ok=True)
    (home / ENTRY).write_text(source, encoding="utf-8")
    # Each extra file goes beside plugin.lua, refused if its name would reach outside the folder.
    for name, body in (extras or {}).items():
        if not _beside(name):
            raise PluginError(f"“{name}” is not a name a plugin may bring with it")
        where = home / name
        where.parent.mkdir(parents=True, exist_ok=True)
        where.write_bytes(body)
    return home / ENTRY


def _beside(name: str) -> bool:
    """Whether a name is somewhere inside a plugin's own folder.

    Said of the name rather than of the path it makes, so a name is refused
    before anything is created: no absolute paths, no walking up, no drive
    letters, and nothing reserved by the shape itself.
    """
    if not name or name == ENTRY or name.startswith((" ", "/", "\\")):
        return False
    if ":" in name or "\\" in name:
        return False
    inside = PurePosixPath(name)
    parts = inside.parts
    if not parts or any(part in ("..", ".", "") for part in parts):
        return False
    if inside.is_absolute():
        return False
    # And nothing that means something other than what it says: "./x" and
    # "a//b" both land somewhere safe and somewhere other than written, and
    # a file arriving under a name nobody chose is the thing being avoided.
    return str(inside) == name


def discard(plugin_id: str) -> bool:
    """Take one of somebody's own plugins off the disk, folder and all.

    Only ever inside the plugins folder, and only ever a name that could be a
    plugin id: this deletes a directory tree, and the one thing it must never
    do is take a tree somebody meant to keep.
    """
    if not plugin_id or not set(plugin_id) <= PLAIN:
        return False
    where = folder()
    home = where / plugin_id
    loose = where / f"{plugin_id}.lua"
    # Resolved and checked, so a name that somehow got past the character
    # test still cannot point out of the folder.
    if home.is_dir() and home.resolve().parent == where.resolve():
        shutil.rmtree(home)
        return True
    if loose.is_file():
        loose.unlink()
        return True
    return False
