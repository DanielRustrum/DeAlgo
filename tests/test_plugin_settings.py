"""Plugins' own settings: the admin's for everyone, and each account's own.

A plugin declares them in its table, the admin sets the app ones on its card
under Admin → Plugins, each account sets its user ones under Settings, and
the plugin reads them back through `settings` — its own, and the account in
hand's, and nobody else's.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from fakes import use_config
from pamphlets.plugins import capabilities, registry
from pamphlets.plugins.registry.settings import settings_in
from pamphlets.services import accounts, plugin_settings

ADMIN = ("admin", "admin")
MEMBER = ("sam", "member-password")

#: A plugin with one of each: an app setting its source reads, a secret, and
#: a user setting its condition reads.
TUNED = """return {
  name = "Tuned", version = "1.0.0", api = 1,
  settings = {
    app = {
      { name = "server", label = "Server", default = "https://one.example",
        hint = "Where everyone's feeds come from." },
      { name = "token", label = "API token", type = "secret" },
      { name = "limit", type = "number", default = 10 },
    },
    user = {
      { name = "keep_all", label = "Keep everything", type = "toggle", default = true },
      { name = "mood", type = "choice", choices = { "calm", { value = "loud", label = "Loud" } } },
    },
  },
  sources = { { kind = "tuned", colour = "jade",
    recognise = function(r)
      local n = string.match(r, "^tuned/(%w+)$")
      if n then return { key = n, feed = settings.app("server") .. "/" .. n } end
    end } },
  augmentations = { { kind = "gate", under = "filter",
    keep = function(item) return settings.user("keep_all") end } },
}"""


@pytest.fixture
def here(tmp_path, monkeypatch):
    """A plugins folder of its own, holding the plugin above."""
    folder = tmp_path / "plugins"
    folder.mkdir()
    (folder / "tuned.lua").write_text(TUNED, encoding="utf-8")
    monkeypatch.setattr(registry.storage, "folder", lambda: folder)
    registry.reload()
    yield folder
    registry.reload()


def tuned():
    return next(p for p in registry.current().plugins if p.id == "tuned")


# -- declaring them ------------------------------------------------------------


def test_every_kind_of_setting_is_understood():
    declared = settings_in({
        "app": [{"name": "server"}, {"name": "token", "type": "secret"}],
        "user": [
            {"name": "on", "type": "toggle", "default": True},
            {"name": "n", "type": "number", "default": 3},
            {"name": "pick", "type": "choice", "choices": ["a", {"value": "b", "label": "Bee"}]},
        ],
    })

    assert [one.name for one in declared.app] == ["server", "token"]
    on, n, pick = declared.user
    assert on.default == "1" and on.read(None) is True
    assert n.read(None) == 3 and n.read("2.5") == 2.5
    assert pick.choices == (("a", "a"), ("b", "Bee")) and pick.default == "a"
    assert declared.app[0].label == "Server"


@pytest.mark.parametrize("given, said", [
    ({"app": [{"name": "x", "type": "colour"}]}, "`type` has to be one of"),
    ({"user": [{"name": "x", "type": "choice"}]}, "needs a list of `choices`"),
    ({"user": [{"name": "x", "type": "choice", "choices": ["a"], "default": "b"}]},
     "not one of its choices"),
    ({"app": [{"name": "x", "type": "number", "default": "lots"}]}, "is not a number"),
    ({"app": [{"name": "x"}, {"name": "x"}]}, "twice"),
    ({"app": [{"name": "Not Plain"}]}, "plain `name`"),
    ({"everyone": []}, "not “everyone”"),
])
def test_a_setting_that_could_never_be_drawn_refuses_the_plugin(given, said):
    with pytest.raises(registry.PluginError, match=said):
        settings_in(given)


def test_a_bad_settings_table_is_a_plugin_that_does_not_load(tmp_path):
    (tmp_path / "bad.lua").write_text(
        'return { api = 1, settings = { app = { { name = "x", type = "nope" } } } }'
    )
    found = registry.read(tmp_path)
    assert "`type` has to be one of" in found.broken[0].trouble


# -- reading them from Lua -------------------------------------------------------


def test_an_app_setting_reads_its_default_until_the_admin_sets_it(db, here):
    assert registry.current().recognise("tuned/a").feed_url == "https://one.example/a"

    plugin_settings.save("tuned", "app", None, {"server": "https://two.example"})
    assert registry.current().recognise("tuned/a").feed_url == "https://two.example/a"


def test_a_user_setting_is_the_account_in_hands_own(db, here):
    with db.session_scope() as session:
        ann = accounts.create_user(session, "ann", "ann-password-1").id
        bob = accounts.create_user(session, "bob", "bob-password-1").id
    plugin_settings.save("tuned", "user", ann, {"keep_all": ""})
    found = registry.current()

    with capabilities.acting_for(ann):
        assert found.keeps("tuned:gate", {}, {}) is False
    with capabilities.acting_for(bob):
        # Never set: the default, not Ann's choice.
        assert found.keeps("tuned:gate", {}, {}) is True


def test_with_no_account_in_hand_a_user_setting_is_its_default(db, here):
    plugin_settings.save("tuned", "user", None, {"keep_all": ""})
    plugin = tuned()
    reader = capabilities.PluginSettings(plugin)

    assert reader.user("keep_all") is True
    assert reader.app("never_declared") is None


# -- setting them --------------------------------------------------------------


@pytest.fixture
def site(db, monkeypatch, here):
    """The app with sign-in on: an admin, and a member called sam."""
    from pamphlets import config, scheduler
    from pamphlets.web import app as web_app

    secured = config.Config(
        **{**config.CONFIG.__dict__, "admin_user": ADMIN[0], "admin_password": ADMIN[1]}
    )
    use_config(monkeypatch, secured)
    monkeypatch.setattr(scheduler, "start", lambda: None)
    monkeypatch.setattr(scheduler, "shutdown", lambda: None)
    monkeypatch.setattr(scheduler, "next_run_time", lambda: None)
    monkeypatch.setattr(web_app, "init_db", lambda: None)
    with db.session_scope() as session:
        accounts.ensure_admin(session)
        accounts.create_user(session, *MEMBER)
    return web_app.app


def signed_in(app, who):
    client = TestClient(app)
    client.post("/login", data=dict(zip(("username", "password"), who)))
    return client


def test_app_settings_are_on_the_plugins_card_beside_what_it_may_do(site):
    page = signed_in(site, ADMIN).get("/admin/plugins").text
    card = page.split('id="plugin-tuned"', 1)[1].split("</li>", 1)[0]

    assert "Settings for everyone" in card
    assert 'action="/admin/plugins/tuned/settings"' in card
    assert 'value="https://one.example"' in card
    assert "Where everyone&#39;s feeds come from." in card or "Where everyone's feeds come from." in card
    # Marked as the same plugin everywhere it appears.
    assert 'class="plugin-mark" data-colour="jade"' in card


def test_the_admin_saves_app_settings_for_everyone(site):
    admin = signed_in(site, ADMIN)
    done = admin.post("/admin/plugins/tuned/settings", data={
        "s_server": "https://three.example", "s_token": "sekrit", "s_limit": "25",
    }, follow_redirects=True)

    assert "saved for everyone" in done.text
    assert plugin_settings.stored("tuned", "app") == {
        "server": "https://three.example", "token": "sekrit", "limit": "25",
    }
    # A secret is never written back into the page.
    assert "sekrit" not in done.text
    assert "Saved — type to replace it" in done.text


def test_a_blank_secret_keeps_what_was_saved_and_clearing_removes_it(site):
    admin = signed_in(site, ADMIN)
    admin.post("/admin/plugins/tuned/settings", data={"s_token": "first"})
    admin.post("/admin/plugins/tuned/settings", data={"s_token": ""})
    assert plugin_settings.stored("tuned", "app")["token"] == "first"

    admin.post("/admin/plugins/tuned/settings", data={"clear_token": "1"})
    assert plugin_settings.stored("tuned", "app")["token"] == ""


def test_a_value_the_setting_cannot_take_saves_nothing(site):
    admin = signed_in(site, ADMIN)
    done = admin.post("/admin/plugins/tuned/settings", data={
        "s_server": "https://changed.example", "s_limit": "lots",
    }, follow_redirects=True)

    assert "has to be a number" in done.text and "Nothing was saved" in done.text
    assert plugin_settings.stored("tuned", "app") == {}


def test_a_member_cannot_reach_the_app_settings(site):
    member = signed_in(site, MEMBER)
    member.post("/admin/plugins/tuned/settings", data={"s_server": "https://evil.example"})
    assert plugin_settings.stored("tuned", "app") == {}


def test_each_account_sets_its_own_under_settings(site):
    member = signed_in(site, MEMBER)
    page = member.get("/settings").text
    assert 'id="plugin-tuned"' in page
    assert 'action="/settings/plugins/tuned"' in page
    # Only the user ones: the app ones are the admin's.
    assert 's_server' not in page

    member.post("/settings/plugins/tuned", data={"s_mood": "loud"})
    sam = member_id()
    assert plugin_settings.stored("tuned", "user", sam) == {"keep_all": "", "mood": "loud"}
    # The admin's are untouched.
    assert plugin_settings.stored("tuned", "user", None) == {}


def test_a_choice_off_the_list_is_refused(site):
    member = signed_in(site, MEMBER)
    done = member.post("/settings/plugins/tuned", data={"s_mood": "furious"}, follow_redirects=True)
    assert "has to be one of its choices" in done.text


def test_a_switched_off_plugin_offers_no_user_settings(site):
    registry.set_paused("tuned", paused=True)
    registry.reload()
    member = signed_in(site, MEMBER)

    assert 'id="plugin-tuned"' not in member.get("/settings").text
    member.post("/settings/plugins/tuned", data={"s_mood": "loud"})
    sam = member_id()
    assert plugin_settings.stored("tuned", "user", sam) == {}


def test_removing_a_plugin_takes_its_settings_with_it(site):
    plugin_settings.save("tuned", "app", None, {"server": "https://x.example"})
    plugin_settings.save("tuned", "user", None, {"mood": "loud"})
    signed_in(site, ADMIN).post("/admin/plugins/tuned/remove")

    assert plugin_settings.stored("tuned", "app") == {}
    assert plugin_settings.stored("tuned", "user", None) == {}


def member_id() -> int:
    from pamphlets.db import session_scope

    with session_scope() as session:
        return next(user.id for user in accounts.list_users(session) if user.username == MEMBER[0])


def test_what_the_admin_decides_is_folded_together_on_the_card(site):
    """What it may do, how it signs in and its settings for everyone: one
    section, folded until opened, and reopened by a save."""
    page = signed_in(site, ADMIN).get("/admin/plugins").text
    card = page.split('id="plugin-tuned"', 1)[1].split("</li>", 1)[0]
    fold = card.split('id="plugin-tuned-setup"', 1)[1].split("</details>", 1)[0]
    assert "Settings for everyone" in fold
    assert "settings for everyone" in fold.split("</summary>", 1)[0]
