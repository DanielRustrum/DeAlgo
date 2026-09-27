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


def offer(client, name, body):
    """Upload one, which now only *offers* it: nothing is written yet."""
    return client.post(
        "/admin/plugins",
        files={"file": (name, body.encode(), "text/plain")},
        follow_redirects=True,
    )


def upload(client, name, body, **granting):
    """Offer one and agree to it, which is what adding a plugin now means."""
    answer = offer(client, name, body)
    if "/admin/plugins/confirm" not in answer.text:
        return answer   # it was refused before anybody was asked anything
    return client.post(
        "/admin/plugins/confirm",
        data={"name": name, "source": body, **{f"grant_{k}": "1" for k in granting}},
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


# -- switching one off -----------------------------------------------------


def test_a_shipped_plugin_can_be_switched_off(admin):
    """Removing one is impossible — it lives in the image — so this is the
    only way to turn YouTube off."""
    answer = admin.post("/admin/plugins/youtube/pause", data={"on": "0"}, follow_redirects=True)

    assert "switched off" in answer.text
    assert registry.current().recognise("@mkbhd") is None
    # And the rest carry on.
    assert registry.current().recognise("r/python").kind == "reddit"


def test_switching_one_off_does_not_make_it_broken(admin):
    """A paused plugin is working fine and has been asked to stand down."""
    admin.post("/admin/plugins/youtube/pause", data={"on": "0"})
    found = registry.current()

    assert found.broken == []
    youtube = next(p for p in found.plugins if p.id == "youtube")
    assert youtube.loaded is True and youtube.paused is True
    # Still readable, so you can see what you switched off.
    assert admin.get("/admin/plugins/youtube/source").status_code == 200


def test_switching_it_back_on_restores_what_it_offered(admin):
    admin.post("/admin/plugins/youtube/pause", data={"on": "0"})
    assert registry.current().recognise("@mkbhd") is None

    answer = admin.post("/admin/plugins/youtube/pause", data={"on": "1"}, follow_redirects=True)

    assert "switched on" in answer.text
    assert registry.current().recognise("@mkbhd").kind == "youtube"


def test_the_switch_outlives_a_restart(admin, db):
    """It is a decision about the install, so it is stored rather than held
    in the process that happened to make it."""
    admin.post("/admin/plugins/youtube/pause", data={"on": "0"})

    registry.reload()   # as a fresh start would

    assert "youtube" in registry.paused_ids()
    assert registry.current().recognise("@mkbhd") is None


def test_sources_already_watched_keep_working_while_it_is_off(admin, db):
    """Nothing is deleted and nothing stops polling: a channel holds its own
    feed address, and the plugin's job was only to work it out once."""
    from dealgo.models import Channel

    with db.session_scope() as session:
        session.add(Channel(
            channel_id="r/python", title="r/python", source_kind="reddit",
            source_url="https://www.reddit.com/r/python/.rss", enabled=True,
        ))

    admin.post("/admin/plugins/reddit/pause", data={"on": "0"})

    with db.session_scope() as session:
        kept = session.query(Channel).filter(Channel.channel_id == "r/python").one()
        assert kept.enabled is True
        assert kept.feed_url == "https://www.reddit.com/r/python/.rss"


def test_the_page_says_how_much_is_leaning_on_one(admin, db):
    """Switching one off should be a decision rather than a discovery."""
    from dealgo.models import Channel

    with db.session_scope() as session:
        for name in ("r/a", "r/b"):
            session.add(Channel(channel_id=name, title=name, source_kind="reddit",
                                source_url=f"https://www.reddit.com/{name}/.rss"))

    body = admin.get("/admin/plugins").text

    assert "2 watched sources" in body


def test_a_paused_plugin_hands_its_kind_to_a_replacement(admin, here):
    """Which is what makes pausing useful: a shipped plugin steps aside so
    one of your own can own the kind."""
    admin.post("/admin/plugins/reddit/pause", data={"on": "0"})
    (here / "myreddit.lua").write_text("""
        return { api = 1, name = "My Reddit", sources = { { kind = "reddit",
          recognise = function(r)
            if string.match(r, "^r/") then return { key = r, feed = "https://mine/" .. r } end
          end } } }
    """, encoding="utf-8")
    registry.reload()

    found = registry.current().recognise("r/python")

    assert found.plugin == "My Reddit"
    assert [p.trouble for p in registry.current().plugins if p.trouble] == []


def test_switching_something_that_is_not_here_is_refused(admin):
    answer = admin.post("/admin/plugins/nope/pause", data={"on": "0"}, follow_redirects=True)

    assert "not a plugin here" in answer.text


# -- reading one -----------------------------------------------------------


def test_a_plugin_can_be_read_without_leaving_the_page(admin):
    """It is code that runs here. Being able to read it is the least this
    owes anybody."""
    body = admin.get("/admin/plugins/reddit/source").text

    assert "recognise" in body
    assert "openrss.org" in body, "the whole file, not a summary"


def test_reading_something_that_is_not_here_is_refused(admin):
    answer = admin.get("/admin/plugins/nope/source", follow_redirects=True)

    assert "not a plugin here" in answer.text


def test_a_member_cannot_read_a_plugin(admin):
    admin.post("/logout")
    admin.post("/login", data={"username": "sam", "password": "member-password"})

    refused = admin.get("/admin/plugins/reddit/source", follow_redirects=False)

    assert refused.status_code in (302, 303, 403)


# -- what a plugin is allowed to do ----------------------------------------

ASKS = """return {
  api = 1, name = "Asker",
  permissions = {
    { name = "network", why = "To read the page each post links to." },
    { name = "clock",   why = "To tell how old a post is." },
  },
  nodes = { { kind = "probe", label = "Probe", keep = function()
    return { net = net ~= nil, clock = clock ~= nil }
  end } },
}"""


def probe(plugin_id="asks"):
    """What the plugin can actually see from inside its own sandbox."""
    found = registry.current()
    node = found.augmentation(f"{plugin_id}:probe")
    owner = next(p for p in found.plugins if p.id == plugin_id)
    return owner.box.call(node._keep, owner.box.table(), owner.box.table())


def test_nothing_is_written_until_somebody_agrees(admin, here):
    """A plugin nobody said yes to is never on disk at all."""
    answer = offer(admin, "asks.lua", ASKS)

    assert list(here.glob("*.lua")) == []
    assert "wants to be added" in answer.text


def test_the_offer_says_what_it_wants_and_why(admin, here):
    answer = offer(admin, "asks.lua", ASKS)

    assert "Make network requests" in answer.text
    assert "To read the page each post links to." in answer.text
    assert "Read the time" in answer.text
    assert "To tell how old a post is." in answer.text
    # And what granting it actually allows, in the host's words rather than
    # the plugin's.
    assert "anything it has been shown could leave this machine" in answer.text


def test_the_offer_also_says_what_it_offers(admin, here):
    """The same screen answers "what is this for", which is the other half
    of deciding."""
    answer = offer(admin, "asks.lua", ASKS)

    assert "What it offers" in answer.text
    assert "Probe" in answer.text


def test_a_plugin_asking_for_nothing_says_so(admin, here):
    answer = offer(admin, "mine.lua", GOOD)

    assert "It asks for nothing" in answer.text


def test_agreeing_grants_exactly_what_was_ticked(admin, here):
    upload(admin, "asks.lua", ASKS, clock=True)

    plugin = next(p for p in registry.current().plugins if p.id == "asks")
    assert plugin.granted == frozenset({"clock"})
    assert probe() == {"clock": True, "net": False}


def test_agreeing_to_none_of_it_still_adds_the_plugin(admin, here):
    """It loads, it works, and it finds the capability missing."""
    upload(admin, "asks.lua", ASKS)

    assert (here / "asks.lua").is_file()
    assert probe() == {"clock": False, "net": False}


def test_a_permission_it_never_asked_for_cannot_be_ticked_in(admin, here):
    """Whatever the form says. The manifest is the ceiling."""
    offer(admin, "mine.lua", GOOD)
    admin.post(
        "/admin/plugins/confirm",
        data={"name": "mine.lua", "source": GOOD, "grant_network": "1"},
        follow_redirects=True,
    )

    plugin = next(p for p in registry.current().plugins if p.id == "mine")
    assert plugin.granted == frozenset()


def test_a_permission_with_no_reason_is_refused(admin, here):
    """"network" with no explanation is a request nobody can weigh."""
    answer = offer(admin, "mute.lua", """return {
      api = 1, name = "Mute", permissions = { { name = "network" } },
    }""")

    assert "needs a `why`" in answer.text
    assert list(here.glob("*.lua")) == []


def test_a_permission_this_version_does_not_know_grants_nothing(admin, here):
    answer = offer(admin, "odd.lua", """return {
      api = 1, name = "Odd",
      permissions = { { name = "telepathy", why = "To read your mind." } },
    }""")

    assert "does not know what that is" in answer.text
    admin.post(
        "/admin/plugins/confirm",
        data={"name": "odd.lua", "source": """return {
          api = 1, name = "Odd",
          permissions = { { name = "telepathy", why = "To read your mind." } },
        }""", "grant_telepathy": "1"},
        follow_redirects=True,
    )
    plugin = next(p for p in registry.current().plugins if p.id == "odd")
    assert plugin.granted == frozenset()


# -- changing your mind afterwards -----------------------------------------


def test_the_row_says_what_it_may_do(admin, here):
    upload(admin, "asks.lua", ASKS, clock=True)

    body = admin.get("/admin/plugins").text

    assert "Allowed to" in body
    assert "To tell how old a post is." in body


def test_a_permission_can_be_taken_back(admin, here):
    upload(admin, "asks.lua", ASKS, clock=True, network=True)
    assert probe() == {"clock": True, "net": True}

    admin.post("/admin/plugins/asks/permissions", data={"grant_clock": "1"},
               follow_redirects=True)

    assert probe() == {"clock": True, "net": False}


def test_a_permission_can_be_given_later(admin, here):
    upload(admin, "asks.lua", ASKS)
    assert probe() == {"clock": False, "net": False}

    admin.post("/admin/plugins/asks/permissions",
               data={"grant_clock": "1", "grant_network": "1"}, follow_redirects=True)

    assert probe() == {"clock": True, "net": True}


def test_a_grant_outlives_a_restart(admin, here):
    upload(admin, "asks.lua", ASKS, network=True)

    registry.reload()   # as a fresh start would

    plugin = next(p for p in registry.current().plugins if p.id == "asks")
    assert plugin.granted == frozenset({"network"})


def test_the_row_says_when_it_is_doing_less_than_it_was_written_to(admin, here):
    """A plugin quietly doing less is the hardest kind of broken to notice."""
    upload(admin, "asks.lua", ASKS, clock=True)

    body = admin.get("/admin/plugins").text

    assert "has not been given" in body


def test_a_member_cannot_change_what_a_plugin_may_do(admin, here):
    upload(admin, "asks.lua", ASKS)
    admin.post("/logout")
    admin.post("/login", data={"username": "sam", "password": "member-password"})

    refused = admin.post(
        "/admin/plugins/asks/permissions",
        data={"grant_network": "1"}, follow_redirects=False,
    )

    assert refused.status_code in (302, 303, 403)
    plugin = next(p for p in registry.current().plugins if p.id == "asks")
    assert plugin.granted == frozenset()


# -- a plugin's source box in the palette ----------------------------------


def palette(client) -> str:
    html = client.get("/channels").text
    start = html.index('class="graph-palette"')
    return html[start : html.index("</aside>", start)]


def test_a_plugin_offers_its_source_box_beside_its_filters(admin):
    """The way to watch a subreddit is to drag out the Subreddit box. There is
    no generic Channel box to drag out instead."""
    drawer = palette(admin)

    assert 'data-source-kind="youtube"' in drawer
    assert "YouTube channel" in drawer
    assert 'data-source-kind="reddit"' in drawer
    assert "Subreddit" in drawer


def test_the_only_source_box_that_is_not_a_plugins_is_the_address_one():
    """RSS is the floor every plugin's parsing is built on, so it is not
    filed under Plugins with the rest."""
    from dealgo.sources import kinds

    assert kinds.RSS.noun == "Feed address"
    assert kinds.RSS.plugin == ""


def test_a_paused_plugin_takes_its_source_box_with_it(admin):
    """It offers nothing while it is off, and a box for a kind nothing
    provides is a box that refuses everything typed into it."""
    admin.post("/admin/plugins/reddit/pause", data={"paused": "1"})
    try:
        drawer = palette(admin)
        assert 'data-source-kind="reddit"' not in drawer
        assert 'data-source-kind="youtube"' in drawer
    finally:
        admin.post("/admin/plugins/reddit/pause", data={"paused": ""})
