"""Managing plugins, which is managing code that runs in this process.

Under Admin because adding one is adding code to the install, not a per-account
preference — and behind the same guard as accounts for the same reason.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from dealgo.plugins import registry
from dealgo.services import accounts

ADMIN = ("admin", "admin")

GOOD = """return {
  id = "mine", name = "Mine", version = "0.1.0", api = 1,
  sources = { { kind = "mine", label = "Mine", example = "mine/x",
    recognise = function(r)
      local n = string.match(r, "^mine/(%w+)$")
      if n then return { key = "mine/" .. n, feed = "https://x/" .. n } end
    end } },
}"""


@pytest.fixture
def here(tmp_path, monkeypatch):
    """A plugins folder of its own, so a test never writes into the real one."""
    folder = tmp_path / "plugins"
    folder.mkdir()
    monkeypatch.setattr(registry, "folder", lambda: folder)
    registry.reload()
    yield folder
    registry.reload()


@pytest.fixture
def admin(db, monkeypatch, here):
    from dealgo import config, scheduler
    from dealgo.services import accounts as accounts_module
    from dealgo.web import app as web_app

    secured = config.Config(
        **{**config.CONFIG.__dict__, "admin_user": ADMIN[0], "admin_password": ADMIN[1]}
    )
    for module in (config, web_app, accounts_module):
        monkeypatch.setattr(module, "CONFIG", secured)
    monkeypatch.setattr(scheduler, "start", lambda: None)
    monkeypatch.setattr(scheduler, "shutdown", lambda: None)
    monkeypatch.setattr(scheduler, "next_run_time", lambda: None)
    monkeypatch.setattr(web_app, "init_db", lambda: None)

    with db.session_scope() as session:
        accounts.ensure_admin(session)
        accounts.create_user(session, "sam", "member-password")

    with TestClient(web_app.app) as client:
        client.post("/login", data=dict(zip(("username", "password"), ADMIN)))
        yield client


def upload(client, name, body):
    return client.post(
        "/admin/plugins",
        files={"file": (name, body.encode(), "text/plain")},
        follow_redirects=True,
    )


# -- who may see it --------------------------------------------------------


def test_only_the_admin_reaches_the_plugins_page(admin):
    """Adding a plugin is adding code to this install. A member managing
    their own feeds has no business doing that."""
    assert admin.get("/admin/plugins").status_code == 200

    admin.post("/logout")
    admin.post("/login", data={"username": "sam", "password": "member-password"})
    refused = admin.get("/admin/plugins", follow_redirects=False)

    assert refused.status_code in (302, 303, 403)
    assert "Mine" not in admin.get("/", follow_redirects=True).text


# -- what the page says ----------------------------------------------------


def test_the_shipped_plugins_are_listed_as_shipped(admin):
    body = admin.get("/admin/plugins").text

    for name in ("YouTube", "Reddit", "Bluesky", "Substack"):
        assert name in body
    assert "shipped" in body


def test_the_page_says_what_a_plugin_is_allowed_to_do(admin):
    """It runs here. Saying so is not optional."""
    body = admin.get("/admin/plugins").text

    assert "A plugin is code, and it runs here" in body
    assert "no network" in body


def test_a_broken_plugin_is_a_row_saying_why(admin, here):
    (here / "broken.lua").write_text("this is not lua {{{", encoding="utf-8")
    registry.reload()

    body = admin.get("/admin/plugins").text

    assert "not loaded" in body
    assert "syntax error" in body
    # And it does not take the working ones down with it.
    assert "YouTube" in body


# -- adding one ------------------------------------------------------------


def test_a_good_plugin_is_taken_and_read_at_once(admin, here):
    answer = upload(admin, "mine.lua", GOOD)

    assert "Mine added" in answer.text
    assert (here / "mine.lua").is_file()
    # And it is working immediately, not after a restart.
    assert registry.current().recognise("mine/thing").kind == "mine"


def test_a_plugin_that_will_not_load_is_never_written(admin, here):
    """A file that cannot load is one nobody wants in the folder, and saying
    so now beats a broken row afterwards."""
    answer = upload(admin, "bad.lua", "this is not lua {{{")

    assert "syntax error" in answer.text
    assert list(here.glob("*.lua")) == []


def test_only_a_lua_file_is_taken(admin, here):
    answer = upload(admin, "notes.txt", GOOD)

    assert "a .lua file" in answer.text.lower()
    assert list(here.glob("*.lua")) == []


def test_a_name_that_would_not_survive_being_a_filename_is_refused(admin, here):
    for name in ("has space.lua", "Caps.lua", ".lua"):
        answer = upload(admin, name, GOOD)
        assert "letters, numbers" in answer.text, name
    assert list(here.glob("*.lua")) == []


def test_a_filename_with_a_path_in_it_is_refused_rather_than_trimmed(admin, here, tmp_path):
    """Trimming "../" would be safe and would also mean somebody's file
    landing under a name they did not choose."""
    answer = upload(admin, "../escape.lua", GOOD)

    assert "no path in it" in answer.text
    assert list(here.glob("*.lua")) == []
    assert not (tmp_path / "escape.lua").exists()


def test_something_far_too_big_to_be_a_plugin_is_refused(admin, here):
    answer = upload(admin, "huge.lua", "-- " + "x" * (256 * 1024 + 10))

    assert "far too big" in answer.text
    assert list(here.glob("*.lua")) == []


def test_a_file_that_is_not_text_is_refused(admin, here):
    answer = admin.post(
        "/admin/plugins",
        files={"file": ("binary.lua", b"\xff\xfe\x00\x01", "application/octet-stream")},
        follow_redirects=True,
    )

    assert "not text" in answer.text
    assert list(here.glob("*.lua")) == []


def test_uploading_a_shipped_name_replaces_it(admin, here):
    """The only way to change a shipped plugin without editing the image."""
    upload(admin, "reddit.lua", GOOD.replace('"mine"', '"reddit"').replace("Mine", "My Reddit"))

    body = admin.get("/admin/plugins").text
    assert "My Reddit" in body
    assert "replaces the shipped one" in body
    # One row, not two fighting over the kind.
    assert body.count("replaces the shipped one") == 1


# -- taking one away -------------------------------------------------------


def test_one_of_your_own_can_be_removed(admin, here):
    upload(admin, "mine.lua", GOOD)

    answer = admin.post("/admin/plugins/mine/remove", follow_redirects=True)

    assert "removed" in answer.text
    assert not (here / "mine.lua").exists()
    assert registry.current().recognise("mine/thing") is None


def test_a_shipped_plugin_has_no_remove_button(admin):
    """It lives in the image and would come back on the next start, so a
    button offering to remove it would be a lie."""
    body = admin.get("/admin/plugins").text

    assert "/admin/plugins/youtube/remove" not in body


def test_removing_a_shipped_plugin_by_address_is_refused(admin):
    answer = admin.post("/admin/plugins/youtube/remove", follow_redirects=True)

    assert "not a plugin you added" in answer.text
    assert registry.current().recognise("UCzzzzzzzzzzzzzzzzzzzzzz") is not None


@pytest.mark.parametrize("target", ["..%2F..%2Fdealgo", "..", "sub%2Fthing", "Caps"])
def test_a_removal_cannot_reach_outside_the_folder(admin, here, target):
    answer = admin.post(f"/admin/plugins/{target}/remove", follow_redirects=True)

    # Refused by the router or by the route; either is a refusal.
    assert answer.status_code in (200, 404)
    if answer.status_code == 200:
        assert "not a plugin" in answer.text


# -- reading the folder again ----------------------------------------------


def test_a_file_put_there_by_hand_is_picked_up(admin, here):
    """The folder is the truth; the page is a view of it."""
    (here / "byhand.lua").write_text(GOOD.replace("mine", "byhand").replace("Mine", "By Hand"), encoding="utf-8")

    answer = admin.post("/admin/plugins/reload", follow_redirects=True)

    assert "By Hand" in answer.text
    assert registry.current().recognise("byhand/thing") is not None
