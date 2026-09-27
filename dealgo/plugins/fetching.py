"""Taking a plugin from a git repository.

Over HTTPS, as the archive a git host publishes for a branch or a tag —
GitHub, GitLab, Codeberg and anything else running Gitea all serve one at a
predictable address, and a direct link to a ``.tar.gz`` works too.

Not by running git, and not only because there is no git in the image. A
clone runs hooks, reads config out of the repository, and can be pointed at
a transport that does considerably more than fetch; an archive is a file
somebody else's server hands over, and nothing in it is ever executed here.
What comes out is read exactly as an uploaded file is: judged first, put to
somebody for consent, and only then written to disk.

Everything about the archive is treated as hostile, because it is somebody
else's: how big it says it is, how big it turns out to be, how many files
are in it, what they are called and where they say they want to go.
"""

from __future__ import annotations

import io
import tarfile
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from urllib.parse import urlparse

import httpx

from .runtime import PluginError

#: How much of an archive is worth downloading. A plugin is a Lua file and
#: whatever small things sit beside it; anything approaching this is not one.
MOST_ARCHIVE_BYTES = 2 * 1024 * 1024

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

#: The branches to try when nobody said which. In order: what a host calls
#: the default today, and what it called it before.
USUAL_REFS = ("main", "master")


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


def archives(url: str, ref: str = "") -> list[tuple[str, str]]:
    """Every address worth trying for this repository, and which ref each is.

    A direct link to an archive is taken at its word. Anything else is read
    as ``<host>/<owner>/<name>`` and turned into the archive address that
    host publishes — the same shape for GitHub, GitLab, Codeberg and Gitea,
    which is most of what anybody would paste.
    """
    parts = urlparse(_whole(url))
    if parts.scheme != "https":
        raise PluginError("A plugin can only be fetched over https.")
    host = (parts.hostname or "").lower()
    if not host or "." not in host:
        raise PluginError(f"“{url}” is not the address of a repository.")

    path = parts.path
    if path.endswith((".tar.gz", ".tgz")):
        return [(f"https://{host}{path}", ref)]

    bits = [one for one in path.strip("/").split("/") if one]
    if len(bits) < 2:
        raise PluginError(
            f"“{url}” is not a repository. It wants to look like "
            "https://github.com/someone/their-plugin."
        )
    owner, name = bits[0], bits[1].removesuffix(".git")
    refs = [ref] if ref else list(USUAL_REFS)
    made: list[tuple[str, str]] = []
    for wanted in refs:
        if host in ("github.com", "www.github.com"):
            made.append((f"https://codeload.github.com/{owner}/{name}/tar.gz/{wanted}", wanted))
        else:
            # GitLab, Gitea and Codeberg all publish this one; so does
            # anything else that copied Gitea's routes, which is most of the
            # small self-hosted forges.
            made.append(
                (f"https://{host}/{owner}/{name}/archive/{wanted}.tar.gz", wanted)
            )
    return made


def repository_name(url: str) -> str:
    """What the plugin would be called, from the repository's own name.

    A repository called ``dealgo-plugin-letterboxd`` is a plugin called
    ``letterboxd``: the prefix says what it is for, which the folder it lands
    in already says.
    """
    path = urlparse(_whole(url)).path.strip("/")
    for ending in (".tar.gz", ".tgz", ".git"):
        path = path.removesuffix(ending)
    bits = [one for one in path.split("/") if one]
    if not bits:
        return ""
    name = bits[1] if len(bits) > 1 else bits[0]
    # An archive address ends in the ref, not the name: .../tar.gz/main.
    if len(bits) > 2 and bits[-1] in USUAL_REFS:
        name = bits[1]
    for prefix in ("dealgo-plugin-", "dealgo-", "plugin-"):
        if name.startswith(prefix) and len(name) > len(prefix):
            name = name[len(prefix):]
            break
    return "".join(one if one.isalnum() or one in "-_" else "-" for one in name.lower())


def fetch(url: str, client: httpx.Client, *, ref: str = "") -> Fetched:
    """Take a plugin out of a repository, or say why it could not be.

    Nothing is written and nothing is loaded: this hands back the text, and
    what happens to it is the same as for a file somebody uploaded.
    """
    tried: list[str] = []
    for address, wanted in archives(url, ref):
        body = _download(address, client)
        if body is None:
            tried.append(address)
            continue
        return _unpack(body, origin=url, ref=wanted, named=repository_name(url))
    said = "that branch" if ref else " or ".join(USUAL_REFS)
    raise PluginError(
        f"Nothing to download there. Checked {said}; is the repository public?"
    )


def _whole(url: str) -> str:
    said = (url or "").strip()
    if not said:
        raise PluginError("Give it the address of a repository.")
    return said if "://" in said else f"https://{said.lstrip('/')}"


def _download(url: str, client: httpx.Client) -> bytes | None:
    """An archive, or None where there is not one there.

    Read in pieces and stopped the moment it is too big, rather than asked
    for whole and measured afterwards: what a server says its length is, is
    somebody else's claim about it.
    """
    try:
        with client.stream("GET", url, headers={"Accept": "application/gzip, */*"}) as answer:
            if answer.status_code != 200:
                return None
            held = io.BytesIO()
            for piece in answer.iter_bytes():
                held.write(piece)
                if held.tell() > MOST_ARCHIVE_BYTES:
                    raise PluginError(
                        "That download is far too big to be a plugin "
                        f"(more than {MOST_ARCHIVE_BYTES // 1024} KB)."
                    )
            return held.getvalue()
    except httpx.HTTPError as exc:
        raise PluginError(f"Could not reach that repository: {exc}") from exc


def _unpack(body: bytes, *, origin: str, ref: str, named: str) -> Fetched:
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
