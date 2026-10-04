"""Publishing a built release to the hubs listed in ops/hubs.toml."""

from __future__ import annotations

import gzip
import hashlib
from pathlib import Path

import pytest

from ops import publish_image as pub

TWO_HUBS = """
[[hub]]
name = "docker-hub"
registry = "docker.io"
repository = "someone/dealgo"
tags = ["{version}", "latest"]

[[hub]]
name = "home"
registry = "registry.example"
repository = "rusty/dealgo"
enabled = false
"""


def hubs_file(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "hubs.toml"
    path.write_text(text)
    return path


def a_release(tmp_path: Path, archs=("amd64",), version="1.2.3") -> Path:
    """A releases/ folder holding fake image files and their checksums."""
    folder = tmp_path / "releases" / version
    folder.mkdir(parents=True)
    lines = []
    for arch in archs:
        name = f"dealgo-v{version}-{arch}.tar.gz"
        (folder / name).write_bytes(gzip.compress(arch.encode()))
        lines.append(f"{hashlib.sha256((folder / name).read_bytes()).hexdigest()}  {name}\n")
    (folder / pub.CHECKSUMS).write_text("".join(lines))
    return tmp_path / "releases"


def test_the_shipped_hubs_file_reads():
    hubs = pub.load_hubs()
    assert [hub.name for hub in hubs] == ["docker-hub"]
    assert hubs[0].registry == "docker.io"


def test_every_enabled_hub_is_chosen_unless_some_are_named(tmp_path):
    hubs = pub.load_hubs(hubs_file(tmp_path, TWO_HUBS))
    assert [hub.name for hub in pub.choose(hubs, [])] == ["docker-hub"]
    # Naming one sends to it even when it is not enabled by default.
    assert [hub.name for hub in pub.choose(hubs, ["home"])] == ["home"]
    with pytest.raises(pub.PublishError, match="No hub called nowhere"):
        pub.choose(hubs, ["nowhere"])


@pytest.mark.parametrize("text, said", [
    ('[[hub]]\nname = "x"\nrepository = ""\n', "has no repository yet"),
    ('[[hub]]\nname = "x"\nrepository = "Not Valid"\n', "not a repository Docker accepts"),
    ('[[hub]]\nname = "x"\nrepository = "a/b"\ntags = ["bad tag"]\n', "not a tag Docker accepts"),
    ('[[hub]]\nname = "x"\nrepository = "a/b"\nenabled = false\n', "No hub is enabled"),
])
def test_a_hub_that_cannot_be_pushed_to_is_refused_by_name(tmp_path, text, said):
    hubs = pub.load_hubs(hubs_file(tmp_path, text))
    with pytest.raises(pub.PublishError, match=said):
        pub.choose(hubs, [])


@pytest.mark.parametrize("text, said", [
    ('[[hub]]\nname = "x"\nrepo = "a/b"\n', "unknown keys: repo"),
    ('[[hub]]\nname = "x"\n[[hub]]\nname = "x"\n', "share a name"),
    ('[[hub]]\nname = "x"\ntags = "latest"\n', "must be a list"),
    ("this is not toml =", "not readable TOML"),
])
def test_a_malformed_hubs_file_says_what_is_wrong(tmp_path, text, said):
    with pytest.raises(pub.PublishError, match=said):
        pub.load_hubs(hubs_file(tmp_path, text))


def test_a_release_is_checked_against_its_checksums(tmp_path):
    root = a_release(tmp_path, ("amd64", "arm64"))
    release = pub.find_release("1.2.3", root)
    assert sorted(release.images) == ["amd64", "arm64"]

    (root / "1.2.3" / "dealgo-v1.2.3-arm64.tar.gz").write_bytes(b"tampered")
    with pytest.raises(pub.PublishError, match="does not match its checksum"):
        pub.find_release("1.2.3", root)


def test_a_missing_release_says_how_to_make_one(tmp_path):
    with pytest.raises(pub.PublishError, match="make release"):
        pub.find_release("9.9.9", tmp_path / "releases")


def test_one_platform_is_tagged_and_pushed_under_each_tag(tmp_path):
    (hub, _) = pub.load_hubs(hubs_file(tmp_path, TWO_HUBS))
    release = pub.Release("1.2.3", tmp_path, {"amd64": tmp_path / "x"})
    assert pub.plan(release, hub, {"amd64": "dealgo:1.2.3"}) == [
        ["docker", "tag", "dealgo:1.2.3", "docker.io/someone/dealgo:1.2.3"],
        ["docker", "push", "docker.io/someone/dealgo:1.2.3"],
        ["docker", "tag", "dealgo:1.2.3", "docker.io/someone/dealgo:latest"],
        ["docker", "push", "docker.io/someone/dealgo:latest"],
    ]


def test_several_platforms_are_joined_under_one_name(tmp_path):
    (hub, _) = pub.load_hubs(hubs_file(tmp_path, TWO_HUBS))
    release = pub.Release("1.2.3", tmp_path)
    commands = pub.plan(
        release, hub, {"amd64": "dealgo:1.2.3-amd64", "arm64": "dealgo:1.2.3-arm64"}
    )
    assert ["docker", "push", "docker.io/someone/dealgo:1.2.3-arm64"] in commands
    assert commands[-1] == [
        "docker", "buildx", "imagetools", "create", "--tag", "docker.io/someone/dealgo:latest",
        "docker.io/someone/dealgo:1.2.3-amd64", "docker.io/someone/dealgo:1.2.3-arm64",
    ]


def test_signing_in_never_prints_or_passes_the_token_as_an_argument(monkeypatch, capsys):
    hub = pub.Hub("h", "docker.io", "a/b", username_env="HUB_USER", token_env="HUB_TOKEN")
    ran: list[tuple[list[str], str | None]] = []

    class Done:
        returncode = 0

    monkeypatch.setattr(pub.subprocess, "run",
                        lambda command, input=None, **_: ran.append((command, input)) or Done())
    monkeypatch.setenv("HUB_USER", "someone")
    monkeypatch.setenv("HUB_TOKEN", "s3cret-token")

    pub.sign_in(hub, dry_run=False)

    (command, given), = ran
    assert "--password-stdin" in command and "s3cret-token" not in command
    assert given == "s3cret-token"
    assert "s3cret-token" not in capsys.readouterr().out


def test_without_credentials_the_existing_login_is_used(monkeypatch, capsys):
    monkeypatch.delenv("HUB_TOKEN", raising=False)
    hub = pub.Hub("h", "docker.io", "a/b", username_env="HUB_USER", token_env="HUB_TOKEN")
    monkeypatch.setattr(pub.subprocess, "run", lambda *a, **k: pytest.fail("ran docker"))
    pub.sign_in(hub, dry_run=False)
    assert "existing `docker login`" in capsys.readouterr().out


def test_a_dry_run_runs_nothing(tmp_path, monkeypatch, capsys):
    root = a_release(tmp_path)
    monkeypatch.setattr(pub, "RELEASES", root)
    monkeypatch.setattr(pub.subprocess, "run", lambda *a, **k: pytest.fail("ran docker"))
    monkeypatch.setattr(pub.subprocess, "Popen", lambda *a, **k: pytest.fail("ran docker"))

    pub.publish("1.2.3", [], dry_run=True, hubs_file=hubs_file(tmp_path, TWO_HUBS))

    out = capsys.readouterr().out
    assert "+ docker push docker.io/someone/dealgo:latest" in out
    assert "would publish docker.io/someone/dealgo:1.2.3" in out
