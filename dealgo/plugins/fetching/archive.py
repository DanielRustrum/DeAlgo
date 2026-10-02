"""Opening somebody else's archive without trusting anything about it.

How big it says it is, how big it turns out to be, how many files are in it,
what they are called and where they say they want to go: all checked before
anything is read.
"""

from __future__ import annotations

import io
import tarfile
from dataclasses import dataclass, field
from pathlib import PurePosixPath

from ..runtime import PluginError

#: And how much it is allowed to become once unpacked, which is a different
#: number: an archive that is small because it compresses well can still be
#: enormous, and reading it into memory is how that becomes our problem.
MOST_UNPACKED_BYTES = 8 * 1024 * 1024


#: How many files are worth looking at. A repository with more than this in
#: it is not a plugin, whatever else it may be.
MOST_FILES = 200


#: What may come out of an archive and be kept. Only what a plugin is made
#: of and what a plugin says about itself — nothing that another program
#: would treat as something to run.
KEEPABLE = (".lua", ".md", ".txt", ".json", ".toml")


#: Files worth keeping that carry no extension at all.
KEEPABLE_NAMES = ("LICENSE", "LICENCE", "COPYING", "NOTICE")


@dataclass(frozen=True)
class Fetched:
    """A plugin taken out of a repository, not yet judged or kept."""

    #: The id it would load under, from the repository's own name.
    plugin_id: str
    source: str
    #: Whatever else came with it, by path inside the plugin's folder.
    extras: dict[str, bytes] = field(default_factory=dict)
    #: Where it came from and which ref, so it can be fetched again.
    origin: str = ""
    ref: str = ""


def unpack(body: bytes, *, origin: str, ref: str, named: str) -> Fetched:
    """The plugin inside an archive, with everything about it distrusted.

    A host's archive wraps the whole repository in one directory named after
    the commit, so the first segment of every path is dropped — and every
    remaining name is checked rather than used, because a name is the one
    thing in an archive that decides where a file would land.
    """
    try:
        with tarfile.open(fileobj=io.BytesIO(body), mode="r:gz") as archive:
            files = _members(archive)
    except (tarfile.TarError, EOFError, OSError) as exc:
        raise PluginError(f"That download is not an archive this can read: {exc}") from exc

    entry = _entry(files)
    if entry is None:
        raise PluginError(
            "No plugin.lua in that repository. A plugin is a plugin.lua at "
            "the top of it, or in a folder of its own."
        )
    root = str(PurePosixPath(entry).parent)
    try:
        source = files[entry].decode("utf-8")
    except UnicodeDecodeError as exc:
        raise PluginError("That repository's plugin.lua is not text.") from exc

    extras: dict[str, bytes] = {}
    for path, held in files.items():
        if path == entry:
            continue
        inside = PurePosixPath(path)
        if root != "." and root not in {str(one) for one in inside.parents}:
            continue
        name = str(inside.relative_to(root)) if root != "." else path
        if _keepable(name):
            extras[name] = held

    plugin_id = named or PurePosixPath(root).name
    return Fetched(
        plugin_id=plugin_id, source=source, extras=extras, origin=origin, ref=ref
    )


def _members(archive: tarfile.TarFile) -> dict[str, bytes]:
    """Every ordinary file in an archive, by its path with the wrapper gone.

    Only ordinary files: a link, a device or a directory with a name that
    walks upwards is how an archive reaches outside where it was unpacked,
    and none of the three has anything to do with being a plugin.
    """
    found: dict[str, bytes] = {}
    unpacked = 0
    for member in archive:
        if len(found) >= MOST_FILES:
            raise PluginError("That repository has far too many files in it to be a plugin.")
        if not member.isfile():
            continue
        path = PurePosixPath(member.name)
        if path.is_absolute() or any(part == ".." for part in path.parts):
            continue
        if len(path.parts) < 2:
            continue  # the wrapper directory's own entries, if any
        unpacked += max(0, member.size)
        if unpacked > MOST_UNPACKED_BYTES:
            raise PluginError("That archive unpacks to far more than a plugin could be.")
        pulled = archive.extractfile(member)
        if pulled is None:  # pragma: no cover - isfile() said otherwise
            continue
        found[str(PurePosixPath(*path.parts[1:]))] = pulled.read(MOST_UNPACKED_BYTES)
    return found


def _entry(files: dict[str, bytes]) -> str | None:
    """Where the plugin's own file is: at the top, or one folder down.

    Shallowest first, so a repository holding an example plugin beside its
    own does not have the example chosen for it.
    """
    wanted = [path for path in files if PurePosixPath(path).name == "plugin.lua"]
    if not wanted:
        return None
    return sorted(wanted, key=lambda path: (len(PurePosixPath(path).parts), path))[0]


def _keepable(name: str) -> bool:
    inside = PurePosixPath(name)
    if inside.is_absolute() or any(part in ("..", "") for part in inside.parts):
        return False
    if len(inside.parts) > 3:
        return False  # a plugin is not a source tree
    return inside.suffix.lower() in KEEPABLE or inside.name in KEEPABLE_NAMES
