"""Build the Docker image and publish it on the repository's Releases page.

usage:
    publish_release.py check TAG          the tag matches the version in the code
    publish_release.py build TAG OUT      build one image per platform into OUT
    publish_release.py publish TAG OUT    attach everything in OUT to the TAG release

A release carries the image as a file rather than in a registry: one
`dealgo-<tag>-<arch>.tar.gz` per platform, loadable with `docker load`, and a
`SHA256SUMS.txt` to check them against. Nothing is pushed anywhere else and
nothing is added to the repository.

`publish` reads its target from the environment, as a Forgejo Action sets it:
`FORGE_URL` (https://host), `REPOSITORY` (owner/name) and `RELEASE_TOKEN` (a
token that may write to the repository). Running it again for the same tag
replaces the files on that release rather than adding copies.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tomllib
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent

#: What each release is built for: the platforms the old registry image had.
#: `RELEASE_PLATFORMS=linux/amd64` narrows it, for a quicker build.
PLATFORMS = tuple(
    one.strip()
    for one in os.environ.get("RELEASE_PLATFORMS", "linux/amd64,linux/arm64").split(",")
    if one.strip()
)

CHECKSUMS = "SHA256SUMS.txt"


# -- the version --------------------------------------------------------------


def code_versions() -> dict[str, str]:
    """The version each place in the code says this is."""
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"]
    package = re.search(
        r'^__version__ = "([^"]+)"', (ROOT / "dealgo" / "__init__.py").read_text(), re.M
    )
    return {"pyproject.toml": project, "dealgo/__init__.py": package.group(1) if package else ""}


def check(tag: str) -> str:
    """The version a tag names, if every place in the code agrees with it."""
    if not re.fullmatch(r"v\d+\.\d+\.\d+(?:[-.][0-9A-Za-z.]+)?", tag):
        raise SystemExit(f"“{tag}” is not a version tag like v1.2.3")
    version = tag[1:]
    wrong = {where: said for where, said in code_versions().items() if said != version}
    if wrong:
        said = ", ".join(f"{where} says {value}" for where, value in wrong.items())
        raise SystemExit(f"{tag} does not match the code: {said}")
    return version


# -- building -------------------------------------------------------------------


def image_file(tag: str, platform: str) -> str:
    """The release file for one platform: dealgo-v1.2.3-amd64.tar.gz."""
    return f"dealgo-{tag}-{platform.split('/')[-1]}.tar.gz"


def build(tag: str, out: Path) -> list[Path]:
    """One image per platform, saved and compressed, and their checksums."""
    version = check(tag)
    out.mkdir(parents=True, exist_ok=True)
    made: list[Path] = []
    for platform in PLATFORMS:
        tarball = out / image_file(tag, platform)[: -len(".gz")]
        print(f"building {platform} …", flush=True)
        # Exporting to a file needs a docker-container builder: CI's setup step
        # makes one the default; locally, name one in BUILDX_BUILDER.
        builder = os.environ.get("BUILDX_BUILDER", "")
        subprocess.run(
            [
                "docker", "buildx", "build",
                *(["--builder", builder] if builder else []),
                "--platform", platform,
                "--tag", f"dealgo:{version}",
                "--label", f"org.opencontainers.image.version={version}",
                # A file `docker load` takes, rather than an image in a daemon.
                "--output", f"type=docker,dest={tarball}",
                str(ROOT),
            ],
            check=True,
        )
        packed = tarball.with_name(tarball.name + ".gz")
        with tarball.open("rb") as raw, gzip.open(packed, "wb", compresslevel=6) as squeezed:
            shutil.copyfileobj(raw, squeezed)
        tarball.unlink()
        made.append(packed)

    sums = "".join(f"{_sha256(path)}  {path.name}\n" for path in made)
    (out / CHECKSUMS).write_text(sums)
    print(sums, end="")
    return made + [out / CHECKSUMS]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as held:
        for block in iter(lambda: held.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


# -- publishing -----------------------------------------------------------------


def _api(
    method: str, url: str, token: str, *, body: bytes | None = None, kind: str = "application/json"
) -> tuple[int, Any]:
    """Call the forge's API; the status and the decoded answer, if any."""
    request = urllib.request.Request(
        url, method=method, data=body,
        headers={
            "Authorization": f"token {token}",
            "Content-Type": kind,
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=600) as answer:
            text = answer.read()
            return int(answer.status), json.loads(text) if text else None
    except urllib.error.HTTPError as refused:
        text = refused.read()
        try:
            return refused.code, json.loads(text) if text else None
        except ValueError:
            return refused.code, text.decode(errors="replace")[:300]


def notes(tag: str, files: list[Path], downloads: str) -> str:
    """The release's description: what is attached and how to use it."""
    images = [path.name for path in files if path.name.endswith(".tar.gz")]
    image = images[0] if images else "dealgo.tar.gz"
    lines = [
        f"De-Algo {tag[1:]} as a Docker image, one file per platform"
        f" ({', '.join(one.split('/')[-1] for one in PLATFORMS)}).",
        "",
        "```bash",
        f"curl -LO {downloads}/{image}",
        f"curl -LO {downloads}/{CHECKSUMS}",
        f"sha256sum --check --ignore-missing {CHECKSUMS}",
        f"gunzip -c {image} | docker load",
        "```",
        "",
        f"The image is then `dealgo:{tag[1:]}`;"
        " point `DEALGO_IMAGE` at it in `docker-compose.yml`.",
    ]
    return "\n".join(lines) + "\n"


def release_for(
    api: str, token: str, tag: str, files: list[Path], downloads: str
) -> dict[str, Any]:
    """The release for this tag: the one already there, or a new one."""
    status, found = _api("GET", f"{api}/releases/tags/{urllib.parse.quote(tag)}", token)
    if status == 200 and isinstance(found, dict):
        return found
    if status in (401, 403):
        raise SystemExit(f"the forge refused the token (HTTP {status}); check RELEASE_TOKEN")
    asked = {
        "tag_name": tag,
        "name": f"De-Algo {tag[1:]}",
        "body": notes(tag, files, downloads),
        # A version with a suffix (v1.2.0-rc.1) is offered, not recommended.
        "prerelease": "-" in tag,
    }
    status, made = _api("POST", f"{api}/releases", token, body=json.dumps(asked).encode())
    if status not in (200, 201) or not isinstance(made, dict):
        raise SystemExit(f"could not create the release for {tag} (HTTP {status}): {made}")
    return made


def attach(api: str, token: str, release: dict[str, Any], path: Path) -> None:
    """Upload one file to the release, replacing one of the same name."""
    for old in release.get("assets") or []:
        if old.get("name") == path.name:
            _api("DELETE", f"{api}/releases/{release['id']}/assets/{old['id']}", token)

    boundary = uuid.uuid4().hex
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="attachment"; filename="{path.name}"\r\n'
        "Content-Type: application/octet-stream\r\n\r\n"
    ).encode() + path.read_bytes() + f"\r\n--{boundary}--\r\n".encode()
    name = urllib.parse.quote(path.name)
    status, said = _api(
        "POST", f"{api}/releases/{release['id']}/assets?name={name}", token,
        body=body, kind=f"multipart/form-data; boundary={boundary}",
    )
    if status not in (200, 201):
        raise SystemExit(f"could not attach {path.name} (HTTP {status}): {said}")
    print(f"attached {path.name} ({path.stat().st_size / 1_048_576:.1f} MB)")


def publish(tag: str, out: Path) -> None:
    """Attach every file in `out` to the release for `tag`."""
    check(tag)
    forge = os.environ["FORGE_URL"].rstrip("/")
    repository = os.environ["REPOSITORY"]
    token = os.environ["RELEASE_TOKEN"]
    api = f"{forge}/api/v1/repos/{repository}"

    files = sorted(path for path in out.iterdir() if path.is_file())
    if not files:
        raise SystemExit(f"nothing to publish in {out}; run build first")
    downloads = f"{forge}/{repository}/releases/download/{urllib.parse.quote(tag)}"
    release = release_for(api, token, tag, files, downloads)
    for path in files:
        attach(api, token, release, path)
    print(f"published {tag}: {forge}/{repository}/releases/tag/{urllib.parse.quote(tag)}")


def main(argv: list[str]) -> int:
    if len(argv) == 2 and argv[0] == "check":
        print(check(argv[1]))
        return 0
    if len(argv) == 3 and argv[0] == "build":
        build(argv[1], Path(argv[2]))
        return 0
    if len(argv) == 3 and argv[0] == "publish":
        publish(argv[1], Path(argv[2]))
        return 0
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
