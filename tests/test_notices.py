"""A plugin's notices: what it needs before it can do its job, as a toast.

The YouTube plugin says, in its own words, that an account should connect,
reconnect, or that the admin has not set it up. The host picks which applies
and shows it as a standing toast on every page, rather than a banner on one.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from fakes import give_youtube_a_client, use_config
from pamphlets.plugins import registry
from pamphlets.plugins.registry.connect import connect_in
from pamphlets.plugins.registry.settings import settings_in
from pamphlets.plugins.runtime import PluginError
from pamphlets.services import accounts

ADMIN = ("admin", "admin")
MEMBER = ("sam", "member-password")


@pytest.fixture
def site(db, monkeypatch):
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


def toasts(page: str) -> str:
    return page.split('id="toasts"', 1)[1].split("</div>\n\n{#", 1)[0]


def test_the_youtube_plugin_says_what_it_needs_in_its_own_words():
    youtube = next(plugin for plugin in registry.current().working if plugin.id == "youtube")
    said = dict(youtube.connect.notices)
    assert set(said) == {"connect", "reconnect", "setup"}
    assert said["connect"].startswith("Connect your Google account")


def test_without_a_client_everyone_hears_so_and_only_the_admin_is_sent_to_fix_it(site):
    member_toasts = toasts(signed_in(site, MEMBER).get("/feed").text)
    assert 'data-toast="plugin-youtube-setup"' in member_toasts
    assert "/admin/plugins" not in member_toasts

    admin_toasts = toasts(signed_in(site, ADMIN).get("/feed").text)
    assert 'href="/admin/plugins#plugin-youtube-setup"' in admin_toasts


def test_with_a_client_an_account_that_has_not_signed_in_is_asked_to(site):
    give_youtube_a_client()
    page = signed_in(site, MEMBER).get("/settings").text
    found = toasts(page)

    assert 'data-toast="plugin-youtube-connect"' in found
    assert "Connect your Google account" in found
    assert 'href="/settings#plugin-youtube"' in found


def test_the_configuration_page_no_longer_carries_the_banner(site):
    give_youtube_a_client()
    page = signed_in(site, MEMBER).get("/channels").text
    body = page.split('id="toasts"', 1)[0]
    assert "Connect your Google account" not in body.split("<main", 1)[1]


def test_nobody_signed_in_hears_nothing(site):
    assert "plugin-youtube" not in TestClient(site).get("/login").text


def test_a_plugin_can_only_speak_of_the_states_there_are():
    settings = settings_in({"app": [{"name": "client_id"}, {"name": "client_secret"}]})
    base = {
        "name": "Thing", "authorize": "https://example.com/a", "token": "https://example.com/t",
        "hosts": ["example.com"],
    }
    made = connect_in({**base, "notices": {"connect": "  Sign   in, please. "}}, settings)
    assert made is not None and dict(made.notices) == {"connect": "Sign in, please."}
    with pytest.raises(PluginError):
        connect_in({**base, "notices": {"celebrate": "Hooray"}}, settings)
