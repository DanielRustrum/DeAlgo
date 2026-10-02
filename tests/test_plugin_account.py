"""Sending as the connected account, without handing over the credential.

The plugin knows the service: which endpoint answers what, what comes back,
what each call costs. What it must never learn is the token — so it does not
make the request, it says what request to make.
"""

from __future__ import annotations

import datetime as dt
import pathlib
import tempfile

import httpx
import pytest

from dealgo.models import OAuthToken, User, utcnow
from dealgo.plugins import registry
from dealgo.plugins.capabilities import account, acting_for


def a_plugin(body: str, granted=frozenset({"account"})):
    source = f"""
    return {{
      api = 1, name = "Sender",
      permissions = {{ {{ name = "account", why = "To read your playlists." }} }},
      nodes = {{ {{ kind = "probe", label = "Probe", keep = function()
        {body}
      end }} }},
    }}
    """
    folder = pathlib.Path(tempfile.mkdtemp())
    (folder / "sender.lua").write_text(source, encoding="utf-8")
    found = registry.read(folder, granted={"sender": granted})
    plugin = found.plugins[0]
    return found, plugin


def ask(found, plugin):
    return plugin.box.call(found.augmentation("sender:probe")._keep, plugin.box.table(), plugin.box.table())


@pytest.fixture
def signed_in(db):
    with db.session_scope() as session:
        session.add(User(id=1, username="me", password_hash="x"))
    with db.session_scope() as session:
        # With an expiry, or it reads as stale and the host quite rightly
        # refuses to send with it.
        session.add(OAuthToken(
            owner_pk=1,
            access_token="secret-token",
            expires_at=utcnow() + dt.timedelta(hours=1),
        ))


@pytest.fixture
def sent(monkeypatch):
    """Record every request the host actually makes, and answer from memory."""
    made: list[dict] = []

    class Client:
        def request(self, method, url, params=None, json=None, headers=None):
            made.append({
                "method": method, "url": url, "params": dict(params or {}),
                "json": json, "headers": dict(headers or {}),
            })
            return httpx.Response(
                200, request=httpx.Request(method, url), json={"items": [{"id": "x"}]}
            )

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

    from dealgo.services import sync as sync_service

    monkeypatch.setattr(sync_service, "http_client", lambda: Client())
    return made


# -- the token never leaves ------------------------------------------------


def test_a_plugin_is_never_handed_the_token(signed_in, sent):
    """The whole reason this is safe to grant. There is no call that returns
    the credential, and nothing else on the object can be reached to go
    looking for one."""
    found, plugin = a_plugin("""
      local out = {}
      local function attempt(name, f)
        local ok, v = pcall(f)
        out[name] = ok and tostring(v) or "blocked"
      end
      attempt("offered",  function() return account.connected() end)
      attempt("token",    function() return account._token end)
      attempt("klass",    function() return account.__class__ end)
      attempt("globals",  function() return account.send.__globals__ end)
      return out
    """)

    with acting_for(1):
        said = ask(found, plugin)
    assert said["offered"] == "true"
    assert said["token"] == "blocked"
    assert said["klass"] == "blocked"
    assert said["globals"] == "blocked"


def test_the_host_attaches_the_credential(signed_in, sent):
    found, plugin = a_plugin(
        'local r = account.send("GET", "https://www.googleapis.com/youtube/v3/playlists")'
        ' return { got = r ~= nil and r.items[1].id }'
    )

    with acting_for(1):
        assert ask(found, plugin)["got"] == "x"
    assert sent[0]["headers"]["Authorization"] == "Bearer secret-token"


# -- what it will and will not sign ----------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "https://evil.example/collect",
        "http://www.googleapis.com/youtube/v3/playlists",   # not https
        "https://googleapis.com.evil.example/x",            # a lookalike host
        "https://www.reddit.com/r/x/.rss",
        "file:///etc/passwd",
        "",
    ],
)
def test_nothing_is_signed_for_anywhere_but_the_accounts_own_host(signed_in, sent, url):
    """A capability that signed a request to any address would be one that
    leaks the token to the first address a plugin chose."""
    found, plugin = a_plugin(f'return {{ answered = account.send("GET", "{url}") ~= nil }}')

    with acting_for(1):
        assert ask(found, plugin)["answered"] is False
    assert sent == [], "it sent something anyway"


def test_a_method_nobody_named_is_refused(signed_in, sent):
    found, plugin = a_plugin(
        'return { answered = account.send("TRACE", '
        '"https://www.googleapis.com/youtube/v3/playlists") ~= nil }'
    )

    with acting_for(1):
        assert ask(found, plugin)["answered"] is False
    assert sent == []


# -- whose account ---------------------------------------------------------


def test_it_sends_as_nobody_outside_a_run(signed_in, sent):
    found, plugin = a_plugin(
        'return { answered = account.send("GET", '
        '"https://www.googleapis.com/youtube/v3/playlists") ~= nil }'
    )

    assert ask(found, plugin)["answered"] is False
    assert sent == []


def test_without_the_permission_there_is_no_account_at_all(signed_in, sent):
    found, plugin = a_plugin("return { has = account ~= nil }", frozenset())

    with acting_for(1):
        assert ask(found, plugin)["has"] is False


def test_it_says_whether_there_is_anything_to_send_as(db, sent):
    """Worth asking before building a request: a plugin that knows there is
    no account can do the half of its job that needs none."""
    with db.session_scope() as session:
        session.add(User(id=1, username="me", password_hash="x"))

    found, plugin = a_plugin("return { connected = account.connected() }")
    with acting_for(1):
        assert ask(found, plugin)["connected"] is False

    with pytest.MonkeyPatch.context():
        pass


def test_with_an_account_it_says_so(signed_in, sent):
    found, plugin = a_plugin("return { connected = account.connected() }")

    with acting_for(1):
        assert ask(found, plugin)["connected"] is True


# -- what it costs ---------------------------------------------------------


def test_the_day_is_charged_what_the_plugin_says(signed_in, sent, db):
    from dealgo.services import quota

    found, plugin = a_plugin(
        'account.send("POST", "https://www.googleapis.com/youtube/v3/playlistItems", nil, 50)'
        ' return { done = true }'
    )

    with acting_for(1):
        ask(found, plugin)
    with db.session_scope() as session:
        assert quota.state(session, 1).used == 50


def test_a_plugin_cannot_spend_the_day_in_one_call(signed_in, sent, db):
    """A quota unit is real money to somebody, and a plugin that miscounts —
    or lies — should not be able to."""
    from dealgo.services import quota

    found, plugin = a_plugin(
        'account.send("GET", "https://www.googleapis.com/youtube/v3/playlists", nil, 99999)'
        ' return { done = true }'
    )

    with acting_for(1):
        ask(found, plugin)
    with db.session_scope() as session:
        assert quota.state(session, 1).used == account.MOST_COST


def test_a_call_cannot_be_free(signed_in, sent, db):
    from dealgo.services import quota

    found, plugin = a_plugin(
        'account.send("GET", "https://www.googleapis.com/youtube/v3/playlists", nil, 0)'
        ' return { done = true }'
    )

    with acting_for(1):
        ask(found, plugin)
    with db.session_scope() as session:
        assert quota.state(session, 1).used == 1


def test_it_cannot_send_for_ever(signed_in, sent):
    found, plugin = a_plugin("""
      for _ = 1, 100 do
        account.send("GET", "https://www.googleapis.com/youtube/v3/playlists")
      end
      return { done = true }
    """)

    with acting_for(1):
        ask(found, plugin)
    assert len(sent) == account.MOST_CALLS
