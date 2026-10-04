"""Publish a release built by `make release` to every hub in ops/hubs.toml.

usage:
    publish_image.py [--version X.Y.Z] [--hub NAME ...] [--dry-run] [--hubs FILE]

Takes `releases/<version>/` — the version in the code unless --version says
otherwise — checks its files against their SHA256SUMS.txt, loads the image
into Docker, and pushes it to each enabled hub under that hub's tags.

A release of one platform is tagged and pushed as it is. A release of several
is pushed per platform (`<tag>-<arch>`) and then joined under each tag as one
multi-platform image, so `docker pull` gets the right one on any machine.

Hubs are listed in ops/hubs.toml, which says how to add and remove them.
Signing in is either `docker login` done beforehand, or a hub's
`username_env` and `token_env`, when both are set in the environment; the
token goes to docker on standard input and is never printed.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import subprocess
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HUBS = Path(__file__).resolve().parent / "hubs.toml"
RELEASES = ROOT / "releases"
CHECKSUMS = "SHA256SUMS.txt"

#: A release file's name: dealgo-v1.2.3-amd64.tar.gz.
IMAGE_FILE = re.compile(r"dealgo-v(?P<version>[^-]+(?:-[^-]+)*)-(?P<arch>[a-z0-9]+)\.tar\.gz")
#: A repository Docker accepts: lowercase path parts separated by slashes.
REPOSITORY = re.compile(r"[a-z0-9]+(?:[._-][a-z0-9]+)*(?:/[a-z0-9]+(?:[._-][a-z0-9]+)*)+")


class PublishError(SystemExit):
    """Something to say instead of publishing."""


@dataclass(frozen=True)
class Hub:
    """One place the image is published to."""

    name: str
    registry: str
    repository: str
    tags: tuple[str, ...] = ("{version}",)
    enabled: bool = True
    username_env: str = ""
    token_env: str = ""

    def reference(self, tag: str) -> str:
        """The full name to push as: docker.io/me/dealgo:1.2.3."""
        return f"{self.registry}/{self.repository}:{tag}"


@dataclass
class Release:
    """A built release: its version and one image file per platform."""

    version: str
    folder: Path
    images: dict[str, Path] = field(default_factory=dict)  # arch -> file


# -- reading what to do -----------------------------------------------------------


def load_hubs(path: Path = HUBS) -> list[Hub]:
    """Every hub in the file, checked. Disabled ones are kept, to be named."""
    try:
        data = tomllib.loads(path.read_text())
    except FileNotFoundError:
        raise PublishError(f"No hubs file at {path}.") from None
    except tomllib.TOMLDecodeError as exc:
        raise PublishError(f"{path.name} is not readable TOML: {exc}") from None
    hubs = []
    for index, entry in enumerate(data.get("hub", []), start=1):
        if not isinstance(entry, dict):
            raise PublishError(f"Hub {index} in {path.name} is not a table.")
        known = {"name", "registry", "repository", "tags", "enabled", "username_env", "token_env"}
        unknown = set(entry) - known
        if unknown:
            raise PublishError(
                f"Hub {index} in {path.name} has unknown keys: {', '.join(sorted(unknown))}"
            )
        name = str(entry.get("name") or f"hub-{index}")
        tags = entry.get("tags", ["{version}"])
        if not isinstance(tags, list) or not tags or not all(
            isinstance(t, str) and t for t in tags
        ):
            raise PublishError(f"Hub {name}: `tags` must be a list of names.")
        hubs.append(Hub(
            name=name,
            registry=str(entry.get("registry") or "docker.io"),
            repository=str(entry.get("repository") or ""),
            tags=tuple(tags),
            enabled=bool(entry.get("enabled", True)),
            username_env=str(entry.get("username_env") or ""),
            token_env=str(entry.get("token_env") or ""),
        ))
    names = [hub.name for hub in hubs]
    if len(set(names)) != len(names):
        raise PublishError(f"Two hubs in {path.name} share a name.")
    return hubs


def choose(hubs: list[Hub], wanted: list[str]) -> list[Hub]:
    """The hubs to publish to: those named, or every enabled one."""
    if wanted:
        by_name = {hub.name: hub for hub in hubs}
        missing = [name for name in wanted if name not in by_name]
        if missing:
            raise PublishError(
                f"No hub called {', '.join(missing)}. The hubs are: {', '.join(by_name) or 'none'}."
            )
        chosen = [by_name[name] for name in wanted]
    else:
        chosen = [hub for hub in hubs if hub.enabled]
    if not chosen:
        raise PublishError("No hub is enabled in ops/hubs.toml, so there is nowhere to publish.")
    for hub in chosen:
        if not hub.repository:
            raise PublishError(
                f"Hub {hub.name} has no repository yet. Set `repository` in ops/hubs.toml, "
                "like \"yourname/dealgo\"."
            )
        if not REPOSITORY.fullmatch(hub.repository):
            raise PublishError(
                f"Hub {hub.name}: “{hub.repository}” is not a repository Docker accepts "
                "(lowercase, like \"yourname/dealgo\")."
            )
        for tag in hub.tags:
            rendered = tag.format(version="0.0.0")
            if not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}", rendered):
                raise PublishError(f"Hub {hub.name}: “{tag}” is not a tag Docker accepts.")
    return chosen


def code_version() -> str:
    """The version the code says this is."""
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"]
    return str(project)


def find_release(version: str, root: Path | None = None) -> Release:
    """A release folder's images, after checking each against its checksums."""
    folder = (root or RELEASES) / version
    sums = folder / CHECKSUMS
    if not sums.exists():
        raise PublishError(f"No release at {folder}. Build one first with `make release`.")
    expected: dict[str, str] = {}
    for line in sums.read_text().splitlines():
        if line.strip():
            digest, _, name = line.partition("  ")
            expected[name.strip()] = digest.strip()
    release = Release(version=version, folder=folder)
    for name, digest in expected.items():
        match = IMAGE_FILE.fullmatch(name)
        if not match:
            continue
        path = folder / name
        if not path.exists():
            raise PublishError(f"{name} is listed in {CHECKSUMS} but missing.")
        if _sha256(path) != digest:
            raise PublishError(
                f"{name} does not match its checksum. Rebuild it with `make release FORCE=1`."
            )
        release.images[match.group("arch")] = path
    if not release.images:
        raise PublishError(f"{folder} holds no image files.")
    return release


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as held:
        for block in iter(lambda: held.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


# -- the plan -----------------------------------------------------------------------


def plan(release: Release, hub: Hub, loaded: dict[str, str]) -> list[list[str]]:
    """The docker commands that publish `loaded` (arch -> local image) to one hub.

    Kept apart from running them, so --dry-run shows exactly what would happen
    and the tests can read it.
    """
    commands: list[list[str]] = []
    tags = [tag.format(version=release.version) for tag in hub.tags]
    if len(loaded) == 1:
        (image,) = loaded.values()
        for tag in tags:
            commands.append(["docker", "tag", image, hub.reference(tag)])
            commands.append(["docker", "push", hub.reference(tag)])
        return commands
    # Each platform under its own tag, then one name for all of them.
    per_arch = []
    for arch, image in sorted(loaded.items()):
        target = hub.reference(f"{release.version}-{arch}")
        commands.append(["docker", "tag", image, target])
        commands.append(["docker", "push", target])
        per_arch.append(target)
    for tag in tags:
        commands.append(
            ["docker", "buildx", "imagetools", "create", "--tag", hub.reference(tag), *per_arch]
        )
    return commands


# -- doing it -----------------------------------------------------------------------


def _run(command: list[str], *, dry_run: bool, stdin: str | None = None) -> None:
    """Run one docker command, its output straight to the terminal."""
    print("+ " + " ".join(command), flush=True)
    if dry_run:
        return
    if subprocess.run(command, input=stdin, text=True, check=False).returncode != 0:
        raise PublishError(f"`{' '.join(command[:3])}` failed; nothing after it was done.")


def load(release: Release, *, dry_run: bool) -> dict[str, str]:
    """Load each image file into Docker; arch -> the image name it carries."""
    loaded = {}
    for arch, path in sorted(release.images.items()):
        if dry_run:
            print(f"+ gunzip -c {path.name} | docker load")
            suffix = "" if len(release.images) == 1 else f"-{arch}"
            loaded[arch] = f"dealgo:{release.version}{suffix}"
            continue
        print(f"+ gunzip -c {path.name} | docker load", flush=True)
        unzip = subprocess.Popen(["gunzip", "-c", str(path)], stdout=subprocess.PIPE)
        answer = subprocess.run(
            ["docker", "load"], stdin=unzip.stdout, capture_output=True, text=True
        )
        unzip.wait()
        if answer.returncode != 0 or unzip.returncode != 0:
            raise PublishError(f"Could not load {path.name}: {answer.stderr.strip()}")
        names = re.findall(r"Loaded image: (\S+)", answer.stdout)
        if not names:
            raise PublishError(f"Loading {path.name} named no image.")
        loaded[arch] = names[-1]
    return loaded


def sign_in(hub: Hub, *, dry_run: bool) -> None:
    """Sign in with the hub's environment variables, when both are set."""
    user = os.environ.get(hub.username_env, "") if hub.username_env else ""
    token = os.environ.get(hub.token_env, "") if hub.token_env else ""
    if not (user and token):
        print(f"{hub.name}: using the existing `docker login` for {hub.registry}")
        return
    command = ["docker", "login", hub.registry, "--username", user, "--password-stdin"]
    _run(command, dry_run=dry_run, stdin=token)


def publish(
    version: str | None, wanted: list[str], *, dry_run: bool, hubs_file: Path = HUBS
) -> None:
    hubs = choose(load_hubs(hubs_file), wanted)
    release = find_release(version or code_version())
    print(f"publishing {release.version} ({', '.join(sorted(release.images))}) "
          f"to {', '.join(hub.name for hub in hubs)}{' — dry run' if dry_run else ''}")
    loaded = load(release, dry_run=dry_run)
    for hub in hubs:
        sign_in(hub, dry_run=dry_run)
        for command in plan(release, hub, loaded):
            _run(command, dry_run=dry_run)
        for tag in hub.tags:
            said = "would publish" if dry_run else "published"
            print(f"{said} {hub.reference(tag.format(version=release.version))}")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--version", help="the release to publish (default: the version in the code)"
    )
    parser.add_argument(
        "--hub", action="append", default=[], help="publish to this hub only (repeatable)"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="say what would be done, and do none of it"
    )
    parser.add_argument(
        "--hubs", type=Path, default=HUBS, help="a hubs file other than ops/hubs.toml"
    )
    args = parser.parse_args(argv)
    wanted = [name for given in args.hub for name in given.split(",") if name.strip()]
    publish(args.version, wanted, dry_run=args.dry_run, hubs_file=args.hubs)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
