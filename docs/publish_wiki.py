"""Publish docs/wiki to the repository's Forgejo wiki.

usage:
    publish_wiki.py build OUT                 write the wiki's pages into OUT
    publish_wiki.py publish                   build, then push to the wiki

`publish` reads its target from the environment, as a Forgejo Action sets it:
`FORGE_URL` (https://host), `REPOSITORY` (owner/name), `WIKI_TOKEN` (a token
that may write to the repository), and optionally `SOURCE_REF` and `SOURCE_SHA`
for the commit message and for links to files outside the wiki.

docs/wiki is the source; the wiki is a copy. Every publish replaces the wiki's
pages with what docs/wiki says, so an edit made in the wiki's own editor is
overwritten — the footer on every page says so.

A Forgejo wiki is one flat folder of pages named with dashes for spaces, and a
page in a subfolder is never served. So the tree is flattened:

    README.md                        → Home
    The Feed Page.md                 → The-Feed-Page
    Nodes/README.md                  → Nodes                (a folder's entry page)
    Nodes/Filter.md                  → Nodes-Filter
    Creating A Plugin/GETTING STARTED.md → Creating-A-Plugin
    Creating A Plugin/Sources.md     → Creating-A-Plugin-Sources

and every link between pages is rewritten to the page it now points at.
"""

from __future__ import annotations

import base64
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

WIKI = Path(__file__).resolve().parent / "wiki"
REPO_ROOT = WIKI.parent.parent

#: What makes a file a folder's entry page, in order of preference.
ENTRY_PAGES = ("README.md", "GETTING STARTED.md")

#: A Markdown link or image: [text](target) or ![alt](target).
LINK = re.compile(r"(!?\[[^\]]*\]\()([^)\s]+)(\))")
FENCE = re.compile(r"^(```|~~~)")

FOOTER = (
    "*This wiki is published from [`docs/wiki`]({source}) in the repository. "
    "Edit it there: changes made here are replaced on the next publish.*\n"
)


# -- naming -----------------------------------------------------------------


def page_name(source: Path) -> str:
    """The wiki page a file under docs/wiki becomes."""
    relative = source.relative_to(WIKI)
    folders = list(relative.parent.parts)
    if relative.name in ENTRY_PAGES and _entry_page(source.parent) == source:
        words = folders or ["Home"]
    else:
        words = folders + [relative.stem]
    return "-".join(" ".join(words).split())


def _entry_page(folder: Path) -> Path | None:
    """The page that stands for a folder, if it has one."""
    for name in ENTRY_PAGES:
        if (folder / name).exists():
            return folder / name
    return None


def sources() -> list[Path]:
    """Every page in docs/wiki, in a stable order."""
    return sorted(WIKI.rglob("*.md"))


# -- rewriting --------------------------------------------------------------


def rewrite(text: str, source: Path, blob_url: str) -> str:
    """The page's text with every relative link pointing where it now lives.

    A link to another page becomes that page's wiki name; a link to anything
    else in the repository becomes a link to the file in the repository.
    Links inside code blocks are left alone.
    """
    out: list[str] = []
    fenced = False
    for line in text.splitlines(keepends=True):
        if FENCE.match(line.lstrip()):
            fenced = not fenced
        out.append(line if fenced else LINK.sub(lambda m: _relink(m, source, blob_url), line))
    return "".join(out)


def _relink(match: re.Match[str], source: Path, blob_url: str) -> str:
    """One link, rewritten if it points at a file by a relative path."""
    opening, target, closing = match.groups()
    if re.match(r"^[a-z][a-z0-9+.-]*:", target, re.I) or target.startswith(("#", "/")):
        return match.group(0)  # absolute, or an anchor on this page
    path, hash_, anchor = target.partition("#")
    found = (source.parent / urllib.parse.unquote(path)).resolve()
    suffix = f"#{anchor}" if hash_ else ""
    if found.suffix == ".md" and WIKI in found.parents and found.exists():
        return f"{opening}{page_name(found)}{suffix}{closing}"
    if REPO_ROOT in found.parents and found.exists():
        where = urllib.parse.quote(found.relative_to(REPO_ROOT).as_posix())
        return f"{opening}{blob_url}/{where}{suffix}{closing}"
    return match.group(0)


def sidebar() -> str:
    """The wiki's sidebar: the home page's index, links and all."""
    home = (WIKI / "README.md").read_text(encoding="utf-8")
    keep = [
        line for line in home.splitlines()
        if line.startswith("## ") or line.lstrip().startswith("- ")
    ]
    # Written as source paths, like any page's links, and rewritten with them.
    lines = ["**[Home](README.md)** · [Contents](Table%20of%20Contents.md)", ""]
    for line in keep:
        if line.startswith("## "):
            lines += ["", f"**{line[3:].strip()}**", ""]
        else:
            # Only the link: the descriptions are for the home page.
            lines.append(line.split(" — ")[0])
    return "\n".join(lines).strip() + "\n"


# -- building ---------------------------------------------------------------


def build(out: Path, blob_url: str) -> list[str]:
    """Write every page, the sidebar and the footer into `out`; return the page names."""
    out.mkdir(parents=True, exist_ok=True)
    names: dict[str, Path] = {}
    for source in sources():
        name = page_name(source)
        if name in names:
            raise SystemExit(f"{source} and {names[name]} would both be the page {name}")
        names[name] = source
        text = rewrite(source.read_text(encoding="utf-8"), source, blob_url)
        (out / f"{name}.md").write_text(text, encoding="utf-8")
    (out / "_Sidebar.md").write_text(
        rewrite(sidebar(), WIKI / "README.md", blob_url), encoding="utf-8"
    )
    (out / "_Footer.md").write_text(
        FOOTER.format(source=f"{blob_url}/docs/wiki"), encoding="utf-8"
    )
    return sorted(names)


# -- publishing -------------------------------------------------------------


def _api(method: str, url: str, token: str, body: dict[str, object] | None = None) -> int:
    """Call the forge's API; returns the HTTP status."""
    request = urllib.request.Request(
        url,
        method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Authorization": f"token {token}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as answer:
            return int(answer.status)
    except urllib.error.HTTPError as refused:
        return refused.code


def _git(*args: str, cwd: Path | None = None) -> str:
    """Run git, returning what it printed; stop the publish if it fails."""
    done = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    if done.returncode != 0:
        # The token is in the remote's URL: never echo the command line.
        raise SystemExit(f"git {args[0]} failed: {done.stderr.strip()}")
    return done.stdout


def ensure_wiki(api: str, token: str) -> None:
    """Make sure the wiki exists: a push cannot create it, but adding a page can."""
    found = _api("GET", f"{api}/wiki/pages", token)
    if found == 200:
        return
    if found in (401, 403):
        raise SystemExit(f"the forge refused the token (HTTP {found}); check WIKI_TOKEN")
    placeholder = base64.b64encode(b"Being published from docs/wiki.").decode()
    first = {"title": "Home", "content_base64": placeholder}
    status = _api("POST", f"{api}/wiki/new", token, first)
    if status not in (200, 201):
        raise SystemExit(f"could not create the wiki (HTTP {status}); is the wiki enabled?")


def publish() -> None:
    """Build the pages and push them as the wiki's whole content."""
    forge = os.environ["FORGE_URL"].rstrip("/")
    repository = os.environ["REPOSITORY"]
    token = os.environ["WIKI_TOKEN"]
    ref = os.environ.get("SOURCE_REF", "main")
    sha = os.environ.get("SOURCE_SHA", "")

    api = f"{forge}/api/v1/repos/{repository}"
    ensure_wiki(api, token)

    parts = urllib.parse.urlsplit(forge)
    signed_in = f"publisher:{token}@{parts.netloc}"
    remote = urllib.parse.urlunsplit(
        (parts.scheme, signed_in, f"{parts.path}/{repository}.wiki.git", "", "")
    )
    with tempfile.TemporaryDirectory() as scratch:
        clone = Path(scratch) / "wiki"
        _git("clone", "--quiet", remote, str(clone))
        branch = _git("rev-parse", "--abbrev-ref", "HEAD", cwd=clone).strip()

        # The wiki becomes exactly what docs/wiki says: everything old goes.
        for old in clone.iterdir():
            if old.name != ".git":
                shutil.rmtree(old) if old.is_dir() else old.unlink()
        names = build(clone, f"{forge}/{repository}/src/branch/{ref}")

        _git("add", "--all", cwd=clone)
        if not _git("status", "--porcelain", cwd=clone).strip():
            print(f"the wiki already matches docs/wiki ({len(names)} pages)")
            return
        said = f"Publish docs/wiki at {sha[:12]}" if sha else "Publish docs/wiki"
        _git(
            "-c", "user.name=Wiki publisher", "-c", "user.email=wiki@localhost",
            "commit", "--quiet", "-m", said, cwd=clone,
        )
        _git("push", "--quiet", "origin", f"HEAD:{branch}", cwd=clone)
    print(f"published {len(names)} pages to {forge}/{repository}/wiki")


def main(argv: list[str]) -> int:
    if len(argv) == 2 and argv[0] == "build":
        names = build(Path(argv[1]), "https://forge.invalid/owner/repo/src/branch/main")
        print(f"{len(names)} pages in {argv[1]}")
        return 0
    if argv == ["publish"]:
        publish()
        return 0
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
