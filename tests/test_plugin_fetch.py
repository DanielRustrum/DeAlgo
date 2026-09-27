"""Taking a plugin from a git repository, and the folder it lands in.

A plugin is a folder of its own — ``<id>/plugin.lua`` — so that it can grow
more than one file without the folder above it becoming a heap.

Fetching is over HTTPS, as the archive a git host publishes. Not by running
git: a clone runs hooks, reads config out of the repository and can be
pointed at a transport that does rather more than fetch. An archive is a file
somebody else's server hands over, and nothing in it is ever run here.

Everything about an archive is treated as hostile, because it is somebody
else's — how big it says it is, how big it turns out to be, how many files
are in it, and above all what they are called.
"""

from __future__ import annotations

import io
import tarfile

import httpx
import pytest

from tests.test_plugin_page import admin  # noqa: F401

from dealgo.plugins import fetching, registry
from dealgo.plugins.runtime import PluginError

GOOD = """return {
  api = 1, name = "Letterboxd",
  augmentations = { { kind = "seen", label = "Seen",
    keep = function() return true end } },
}"""


def tarball(files: dict[str, bytes | str], wrapper: str = "repo-abc123") -> bytes:
    """An archive shaped the way a git host's is: everything in one folder."""
    held = io.BytesIO()
    with tarfile.open(fileobj=held, mode="w:gz") as archive:
        for name, body in files.items():
            raw = body.encode("utf-8") if isinstance(body, str) else body
            info = tarfile.TarInfo(f"{wrapper}/{name}" if wrapper else name)
            info.size = len(raw)
            archive.addfile(info, io.BytesIO(raw))
    return held.getvalue()


def awkward(kind: str) -> bytes:
    """An archive carrying something that is not an ordinary file."""
    held = io.BytesIO()
    with tarfile.open(fileobj=held, mode="w:gz") as archive:
        body = GOOD.encode("utf-8")
        good = tarfile.TarInfo("repo/plugin.lua")
        good.size = len(body)
        archive.addfile(good, io.BytesIO(body))

        if kind == "symlink":
            bad = tarfile.TarInfo("repo/escape.lua")
            bad.type = tarfile.SYMTYPE
            bad.linkname = "/etc/passwd"
            archive.addfile(bad)
        elif kind == "upwards":
            raw = b"-- nope"
            bad = tarfile.TarInfo("repo/../../outside.lua")
            bad.size = len(raw)
            archive.addfile(bad, io.BytesIO(raw))
        elif kind == "absolute":
            raw = b"-- nope"
            bad = tarfile.TarInfo("/etc/cron.d/evil")
            bad.size = len(raw)
            archive.addfile(bad, io.BytesIO(raw))
    return held.getvalue()


class Host:
    """A git host serving whatever archives it was set up with."""

    def __init__(self, archives: dict[str, bytes]):
        self.archives = archives
        self.asked: list[str] = []

    def stream(self, method, url, headers=None):
        self.asked.append(url)
        body = self.archives.get(url)
        answer = httpx.Response(
            200 if body is not None else 404, content=body or b"not here",
            request=httpx.Request(method, url),
        )

        class Held:
            def __enter__(self_inner):
                return answer

            def __exit__(self_inner, *_):
                return False

        return Held()


# -- reading the address ---------------------------------------------------


@pytest.mark.parametrize(
    "url, first",
    [
        ("https://github.com/one/two",
         "https://codeload.github.com/one/two/tar.gz/main"),
        ("github.com/one/two",
         "https://codeload.github.com/one/two/tar.gz/main"),
        ("https://github.com/one/two.git",
         "https://codeload.github.com/one/two/tar.gz/main"),
        # Anything else is asked the way Gitea and GitLab both answer.
        ("https://codeberg.org/one/two",
         "https://codeberg.org/one/two/archive/main.tar.gz"),
        ("https://gitlab.com/one/two",
         "https://gitlab.com/one/two/archive/main.tar.gz"),
        # A direct link to an archive is taken at its word.
        ("https://example.com/held/thing.tar.gz",
         "https://example.com/held/thing.tar.gz"),
    ],
)
def test_a_repository_address_becomes_an_archive_address(url, first):
    assert fetching.archives(url)[0][0] == first


def test_with_no_branch_named_both_of_the_usual_two_are_tried():
    said = fetching.archives("https://github.com/one/two")

    assert [ref for _, ref in said] == list(fetching.USUAL_REFS)


def test_a_branch_named_is_the_only_one_tried():
    said = fetching.archives("https://github.com/one/two", "v2.1")

    assert said == [("https://codeload.github.com/one/two/tar.gz/v2.1", "v2.1")]


def test_only_https_will_do():
    """A plugin is code. Fetching it over something nobody can vouch for is
    not a thing to leave to whoever pasted the address."""
    with pytest.raises(PluginError) as refused:
        fetching.archives("http://github.com/one/two")

    assert "https" in str(refused.value)


@pytest.mark.parametrize("url", ["", "   ", "https://github.com/onlyowner", "notahost"])
def test_something_that_is_not_a_repository_is_refused(url):
    with pytest.raises(PluginError):
        fetching.archives(url)


@pytest.mark.parametrize(
    "url, named",
    [
        ("https://github.com/someone/letterboxd", "letterboxd"),
        # The prefix says what it is for, which the folder already says.
        ("https://github.com/someone/dealgo-plugin-letterboxd", "letterboxd"),
        ("https://github.com/someone/plugin-letterboxd", "letterboxd"),
        ("https://gitlab.com/someone/Thing.git", "thing"),
    ],
)
def test_a_plugin_is_named_after_its_repository(url, named):
    assert fetching.repository_name(url) == named


# -- what comes out of the archive -----------------------------------------


def test_a_plugin_is_taken_out_of_the_archive():
    host = Host({
        "https://codeload.github.com/one/letterboxd/tar.gz/main": tarball(
            {"plugin.lua": GOOD, "README.md": "# Letterboxd"}
        )
    })

    got = fetching.fetch("https://github.com/one/letterboxd", host)

    assert got.plugin_id == "letterboxd"
    assert got.source == GOOD
    assert got.extras == {"README.md": b"# Letterboxd"}
    assert got.origin == "https://github.com/one/letterboxd"
    assert got.ref == "main"


def test_the_second_usual_branch_is_tried_when_the_first_is_not_there():
    host = Host({
        "https://codeload.github.com/one/two/tar.gz/master": tarball({"plugin.lua": GOOD})
    })

    got = fetching.fetch("https://github.com/one/two", host)

    assert got.ref == "master"
    assert host.asked == [
        "https://codeload.github.com/one/two/tar.gz/main",
        "https://codeload.github.com/one/two/tar.gz/master",
    ]


def test_a_repository_with_nothing_there_says_which_branches_it_looked_for():
    host = Host({})

    with pytest.raises(PluginError) as refused:
        fetching.fetch("https://github.com/one/two", host)

    assert "main or master" in str(refused.value)
    assert "public" in str(refused.value)


def test_a_plugin_one_folder_down_is_found():
    """A repository that holds its plugin in a folder of its own, which is
    the shape it will be in once it lands."""
    host = Host({
        "https://codeload.github.com/one/two/tar.gz/main": tarball(
            {"letterboxd/plugin.lua": GOOD, "letterboxd/NOTES.md": "hi",
             "elsewhere/other.lua": "-- not this"}
        )
    })

    got = fetching.fetch("https://github.com/one/two", host)

    assert got.source == GOOD
    # What is beside it is its; what is not, is not.
    assert got.extras == {"NOTES.md": b"hi"}


def test_the_shallowest_plugin_wins():
    """A repository holding an example beside its own should not have the
    example chosen for it."""
    host = Host({
        "https://codeload.github.com/one/two/tar.gz/main": tarball(
            {"plugin.lua": GOOD, "examples/toy/plugin.lua": "return {}"}
        )
    })

    assert fetching.fetch("https://github.com/one/two", host).source == GOOD


def test_a_repository_with_no_plugin_in_it_says_so():
    host = Host({
        "https://codeload.github.com/one/two/tar.gz/main": tarball({"README.md": "hi"})
    })

    with pytest.raises(PluginError) as refused:
        fetching.fetch("https://github.com/one/two", host)

    assert "No plugin.lua" in str(refused.value)


def test_something_that_is_not_an_archive_is_refused():
    host = Host({"https://codeload.github.com/one/two/tar.gz/main": b"<html>hello</html>"})

    with pytest.raises(PluginError) as refused:
        fetching.fetch("https://github.com/one/two", host)

    assert "not an archive" in str(refused.value)


# -- and everything about it distrusted ------------------------------------


@pytest.mark.parametrize("kind", ["symlink", "upwards", "absolute"])
def test_nothing_but_an_ordinary_file_comes_out(kind):
    """A link, a path that walks upwards and an absolute path are the three
    ways an archive reaches outside where it was unpacked. None of them has
    anything to do with being a plugin."""
    host = Host({"https://codeload.github.com/one/two/tar.gz/main": awkward(kind)})

    got = fetching.fetch("https://github.com/one/two", host)

    assert got.source == GOOD
    assert got.extras == {}


def test_only_what_a_plugin_is_made_of_is_kept():
    host = Host({
        "https://codeload.github.com/one/two/tar.gz/main": tarball({
            "plugin.lua": GOOD,
            "helper.lua": "-- fine",
            "README.md": "fine",
            "LICENSE": "fine",
            "install.sh": "rm -rf /",
            "Makefile": "all:",
            ".github/workflows/ci.yml": "on: push",
            "thing.so": "\x7fELF",
        })
    })

    got = fetching.fetch("https://github.com/one/two", host)

    assert sorted(got.extras) == ["LICENSE", "README.md", "helper.lua"]


def test_an_archive_that_is_too_big_to_download_is_stopped_partway(monkeypatch):
    monkeypatch.setattr(fetching, "MOST_ARCHIVE_BYTES", 64)
    host = Host({
        "https://codeload.github.com/one/two/tar.gz/main": tarball(
            {"plugin.lua": GOOD, "big.md": "x" * 100_000}
        )
    })

    with pytest.raises(PluginError) as refused:
        fetching.fetch("https://github.com/one/two", host)

    assert "far too big" in str(refused.value)


def test_an_archive_that_unpacks_to_far_more_than_it_downloads_is_refused(monkeypatch):
    """Compressing well is not the same as being small, and reading it into
    memory is how that becomes our problem."""
    monkeypatch.setattr(fetching, "MOST_UNPACKED_BYTES", 1024)
    host = Host({
        "https://codeload.github.com/one/two/tar.gz/main": tarball(
            {"plugin.lua": GOOD, "big.md": "x" * 500_000}
        )
    })

    with pytest.raises(PluginError) as refused:
        fetching.fetch("https://github.com/one/two", host)

    assert "unpacks to far more" in str(refused.value)


def test_a_repository_with_far_too_many_files_is_refused(monkeypatch):
    monkeypatch.setattr(fetching, "MOST_FILES", 5)
    host = Host({
        "https://codeload.github.com/one/two/tar.gz/main": tarball(
            {"plugin.lua": GOOD, **{f"f{n}.md": "x" for n in range(20)}}
        )
    })

    with pytest.raises(PluginError) as refused:
        fetching.fetch("https://github.com/one/two", host)

    assert "too many files" in str(refused.value)


# -- the folder a plugin lives in ------------------------------------------


@pytest.fixture
def here(tmp_path, monkeypatch):
    """A plugins folder of its own, so a test never writes into the real one."""
    folder = tmp_path / "plugins"
    folder.mkdir()
    monkeypatch.setattr(registry, "folder", lambda: folder)
    yield folder
    registry.reload()


def test_a_plugin_is_written_into_a_folder_of_its_own(here):
    registry.keep("mine", GOOD, {"README.md": b"hi", "lib/helper.lua": b"-- x"})

    assert (here / "mine" / "plugin.lua").read_text() == GOOD
    assert (here / "mine" / "README.md").read_bytes() == b"hi"
    assert (here / "mine" / "lib" / "helper.lua").read_bytes() == b"-- x"


@pytest.mark.parametrize(
    "name", ["../escape.lua", "/etc/passwd", "a/../../b", "plugin.lua", "", "./x"]
)
def test_a_file_that_would_land_outside_the_folder_is_refused(here, name):
    """Refused outright rather than reduced to something safe: a file landing
    somewhere nobody chose is worse to be surprised by than an error."""
    with pytest.raises(PluginError):
        registry.keep("mine", GOOD, {name: b"no"})


@pytest.mark.parametrize("plugin_id", ["../other", "a/b", "", "has space"])
def test_a_name_that_is_not_a_plugin_id_is_refused(here, plugin_id):
    with pytest.raises(PluginError):
        registry.keep(plugin_id, GOOD)


def test_both_shapes_of_plugin_are_read(here):
    """A loose file is what every plugin was until now, and nobody's should
    stop loading."""
    (here / "old.lua").write_text(GOOD)
    registry.keep("new", GOOD)

    assert [one.name for one in registry.inside(here)] == ["plugin.lua", "old.lua"]
    assert {registry.home_of(one).name for one in registry.inside(here)} == {"new", "old"}


def test_a_loose_file_is_moved_into_a_folder_of_its_own(here):
    (here / "old.lua").write_text(GOOD)

    assert registry.settle(here) == 1

    assert (here / "old" / "plugin.lua").read_text() == GOOD
    assert not (here / "old.lua").exists()
    # And again changes nothing: there is nothing loose left.
    assert registry.settle(here) == 0


def test_a_loose_file_whose_folder_is_already_there_is_left_alone(here):
    """Something has already put a plugin there, and deciding which of the
    two was meant is not a migration's to do."""
    registry.keep("both", GOOD)
    (here / "both.lua").write_text("-- the other one")

    assert registry.settle(here) == 0
    assert (here / "both.lua").is_file()
    assert (here / "both" / "plugin.lua").read_text() == GOOD


def test_a_plugin_is_taken_off_the_disk_folder_and_all(here):
    registry.keep("mine", GOOD, {"README.md": b"hi"})

    assert registry.discard("mine") is True
    assert not (here / "mine").exists()
    assert registry.discard("mine") is False


def test_a_loose_plugin_can_still_be_taken_off_the_disk(here):
    (here / "old.lua").write_text(GOOD)

    assert registry.discard("old") is True
    assert not (here / "old.lua").exists()


@pytest.mark.parametrize("plugin_id", ["..", "../..", "a/b", "", "has space"])
def test_discarding_something_that_is_not_a_plugin_id_removes_nothing(here, plugin_id):
    """This removes a directory tree, and the one thing it must never do is
    take a tree somebody meant to keep."""
    keeper = here.parent / "keep-me"
    keeper.mkdir()
    (keeper / "important.txt").write_text("mine")

    assert registry.discard(plugin_id) is False
    assert (keeper / "important.txt").is_file()


# -- held aside until somebody agrees to it --------------------------------


def test_a_fetch_is_held_aside_rather_than_written_where_it_would_load(here):
    registry.stage("mine", GOOD, {"README.md": b"hi"})

    assert (here / registry.STAGING / "mine" / "plugin.lua").read_text() == GOOD
    # Nothing loads out of it while it waits.
    assert registry.inside(here) == []


def test_taking_a_staged_plugin_moves_it_into_place_with_what_came_with_it(here):
    registry.stage("mine", GOOD, {"README.md": b"hi"})

    assert registry.take_staged("mine") is True

    assert (here / "mine" / "plugin.lua").read_text() == GOOD
    assert (here / "mine" / "README.md").read_bytes() == b"hi"
    assert not (here / registry.STAGING / "mine").exists()
    # And there is nothing left to take.
    assert registry.take_staged("mine") is False


def test_a_second_fetch_is_not_layered_on_the_first(here):
    registry.stage("mine", GOOD, {"gone.md": b"from the first"})
    registry.stage("mine", GOOD, {"kept.md": b"from the second"})

    registry.take_staged("mine")

    assert (here / "mine" / "kept.md").is_file()
    assert not (here / "mine" / "gone.md").exists()


def test_taking_a_staged_plugin_replaces_what_was_there(here):
    registry.keep("mine", GOOD, {"stale.md": b"old"})
    registry.stage("mine", GOOD, {"fresh.md": b"new"})

    registry.take_staged("mine")

    assert (here / "mine" / "fresh.md").is_file()
    assert not (here / "mine" / "stale.md").exists()


@pytest.mark.parametrize("plugin_id", ["..", "a/b", "", "has space"])
def test_nothing_but_a_plugin_id_can_be_taken_from_staging(here, plugin_id):
    assert registry.take_staged(plugin_id) is False


# -- from the Admin page ---------------------------------------------------


@pytest.fixture
def serving(monkeypatch):
    """A git host, in place of the real one, for the route to reach."""
    host = Host({})
    from dealgo.services import sync as sync_service

    class Held:
        def __enter__(self_inner):
            return host

        def __exit__(self_inner, *_):
            return False

    monkeypatch.setattr(sync_service, "http_client", lambda: Held())
    return host


def test_fetching_offers_a_plugin_rather_than_installing_it(admin, here, serving):
    """The same door as an upload, reached a different way: fetching is not
    installing, and nothing is on disk until somebody has said yes."""
    serving.archives["https://codeload.github.com/one/letterboxd/tar.gz/main"] = tarball(
        {"plugin.lua": GOOD, "README.md": "how it works"}
    )

    answer = admin.post(
        "/admin/plugins/fetch",
        data={"url": "https://github.com/one/letterboxd", "ref": ""},
        follow_redirects=True,
    )

    assert "wants to be added" in answer.text
    assert "github.com/one/letterboxd" in answer.text
    assert "README.md" in answer.text
    # Held aside, not where it would load from.
    assert not (here / "letterboxd" / "plugin.lua").exists()
    assert (here / registry.STAGING / "letterboxd" / "plugin.lua").is_file()


def test_agreeing_to_it_lands_it_with_what_came_with_it(admin, here, serving, db):
    from dealgo.models import PluginState

    serving.archives["https://codeload.github.com/one/letterboxd/tar.gz/main"] = tarball(
        {"plugin.lua": GOOD, "README.md": "how it works"}
    )
    admin.post(
        "/admin/plugins/fetch",
        data={"url": "https://github.com/one/letterboxd"},
        follow_redirects=True,
    )

    answer = admin.post(
        "/admin/plugins/confirm",
        data={
            "name": "letterboxd.lua", "source": GOOD,
            "origin": "https://github.com/one/letterboxd", "ref": "main",
        },
        follow_redirects=True,
    )

    assert "Letterboxd added" in answer.text
    assert (here / "letterboxd" / "plugin.lua").read_text() == GOOD
    assert (here / "letterboxd" / "README.md").read_text() == "how it works"
    # And where it came from is remembered, so it can be fetched again.
    with db.session_scope() as session:
        row = session.query(PluginState).filter_by(plugin_id="letterboxd").one()
        assert row.origin == "https://github.com/one/letterboxd"
        assert row.origin_ref == "main"
        assert row.fetched_at is not None


def test_the_row_says_where_it_came_from_and_offers_to_fetch_it_again(
    admin, here, serving
):
    serving.archives["https://codeload.github.com/one/letterboxd/tar.gz/main"] = tarball(
        {"plugin.lua": GOOD}
    )
    admin.post(
        "/admin/plugins/fetch",
        data={"url": "https://github.com/one/letterboxd"}, follow_redirects=True,
    )
    admin.post(
        "/admin/plugins/confirm",
        data={
            "name": "letterboxd.lua", "source": GOOD,
            "origin": "https://github.com/one/letterboxd", "ref": "main",
        },
        follow_redirects=True,
    )

    body = admin.get("/admin/plugins").text

    assert 'href="https://github.com/one/letterboxd"' in body
    assert ">Update</button>" in body


def test_a_repository_that_is_not_there_says_so_and_writes_nothing(admin, here, serving):
    answer = admin.post(
        "/admin/plugins/fetch",
        data={"url": "https://github.com/one/nope"}, follow_redirects=True,
    )

    assert "Nothing to download there" in answer.text
    assert list(here.iterdir()) == []


def test_a_plugin_that_will_not_load_is_never_kept(admin, here, serving):
    """Read before it is kept, with nothing granted, exactly as an upload is."""
    serving.archives["https://codeload.github.com/one/broken/tar.gz/main"] = tarball(
        {"plugin.lua": "this is not lua at all ((("}
    )

    answer = admin.post(
        "/admin/plugins/fetch",
        data={"url": "https://github.com/one/broken"}, follow_redirects=True,
    )

    assert "wants to be added" not in answer.text
    assert not (here / registry.STAGING).exists()


def test_a_branch_name_with_a_space_in_it_is_refused(admin, here, serving):
    answer = admin.post(
        "/admin/plugins/fetch",
        data={"url": "https://github.com/one/two", "ref": "not a branch"},
        follow_redirects=True,
    )

    assert "not a branch or tag name" in answer.text
    assert serving.asked == []


def test_only_an_admin_may_fetch_a_plugin(admin, here, serving):
    """Adding a plugin is adding code that runs in this process. A member
    managing their own feeds has no business doing that."""
    serving.archives["https://codeload.github.com/one/two/tar.gz/main"] = tarball(
        {"plugin.lua": GOOD}
    )
    admin.post("/logout")
    admin.post("/login", data={"username": "sam", "password": "member-password"})

    refused = admin.post(
        "/admin/plugins/fetch",
        data={"url": "https://github.com/one/two"}, follow_redirects=False,
    )

    assert refused.status_code in (302, 303, 403)
    # It never reached the host, and nothing was written.
    assert serving.asked == []
    assert list(here.iterdir()) == []
