"""Where a git host publishes the archive of a branch or tag, and what to call what is in it."""

from __future__ import annotations

from urllib.parse import urlparse

from ..runtime import PluginError

#: The branches to try when nobody said which. In order: what a host calls
#: the default today, and what it called it before.
USUAL_REFS = ("main", "master")


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


def _whole(url: str) -> str:
    said = (url or "").strip()
    if not said:
        raise PluginError("Give it the address of a repository.")
    return said if "://" in said else f"https://{said.lstrip('/')}"
