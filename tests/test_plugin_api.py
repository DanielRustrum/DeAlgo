"""The `dealgo` object: how a plugin reaches the rest of the app.

What a plugin returns is configuration and does nothing. Everything it *does*
goes through this object, which it is handed rather than importing, and only
if somebody granted it.

The hard part is not the functions. It is whose data they are about.
"""

from __future__ import annotations

import pathlib
import tempfile

import pytest
from sqlalchemy import select

from dealgo.models import Channel, Playlist
from dealgo.plugins import registry, site


def a_plugin(source: str, granted=frozenset(), plugin_id="api"):
    """Load one plugin from text, with what it was granted."""
    folder = pathlib.Path(tempfile.mkdtemp())
    (folder / f"{plugin_id}.lua").write_text(source, encoding="utf-8")
    found = registry.read(folder, granted={plugin_id: granted})
    return found, found.plugins[0]


def ask(plugin, found, lua: str):
    """Run a snippet inside the plugin, through its own `probe` box."""
    node = found.node(f"{plugin.id}:probe")
    return plugin.box.call(node._keep, plugin.box.table(), plugin.box.table())


def probing(body: str, wants=("read", "manage")) -> str:
    asked = ",\n".join(
        f'{{ name = "{name}", why = "To test with." }}' for name in wants
    )
    return f"""
return {{
  api = 1, name = "Api",
  permissions = {{ {asked} }},
  nodes = {{ {{ kind = "probe", label = "Probe", keep = function()
    {body}
  end }} }},
}}
"""


@pytest.fixture
def two_accounts(db):
    """Two accounts, each watching something of its own.

    Real rows, not just numbers: owner_pk is a foreign key, and a test that
    only pretends there are two accounts is not testing the thing that keeps
    them apart.
    """
    from dealgo.models import User

    with db.session_scope() as session:
        session.add_all([
            User(id=1, username="mine", password_hash="x"),
            User(id=2, username="theirs", password_hash="x"),
        ])
    with db.session_scope() as session:
        session.add_all([
            Channel(owner_pk=1, channel_id="r/mine", title="Mine", source_kind="reddit",
                    source_url="https://x/1", tags="keep"),
            Channel(owner_pk=2, channel_id="r/theirs", title="Theirs", source_kind="reddit",
                    source_url="https://x/2"),
            Playlist(owner_pk=1, playlist_id="generic:mine", title="My Feed"),
            Playlist(owner_pk=2, playlist_id="generic:theirs", title="Their Feed"),
        ])


# -- the object is always there --------------------------------------------


def test_the_object_is_there_even_with_nothing_granted():
    """One object with parts that stay shut is kinder to write against than
    an object that might not exist."""
    found, plugin = a_plugin(probing("return { has = dealgo ~= nil }"), frozenset())

    assert ask(plugin, found, "")["has"] is True


def test_the_version_needs_no_permission():
    """It is on every page. A plugin needs it to tell an older host from a
    newer one and do less rather than fail."""
    found, plugin = a_plugin(probing("return { v = dealgo.version }"), frozenset())

    assert ask(plugin, found, "")["v"] == "0.1.0"


# -- reading ---------------------------------------------------------------


def test_without_the_read_permission_it_sees_nothing(db, two_accounts):
    found, plugin = a_plugin(probing("return { n = #dealgo.sources() }"), frozenset())

    with site.acting_for(1):
        assert ask(plugin, found, "")["n"] == 0


def test_with_it_granted_it_sees_the_account_in_hand(db, two_accounts):
    found, plugin = a_plugin(
        probing("local s = dealgo.sources() return { n = #s, first = s[1] and s[1].title }"),
        frozenset({"read"}),
    )

    with site.acting_for(1):
        said = ask(plugin, found, "")
    assert said["n"] == 1
    assert said["first"] == "Mine"


def test_it_never_sees_another_account(db, two_accounts):
    """A plugin is install-wide: one file, loaded once, used by everybody.
    What it can see has to be whose work it is doing."""
    found, plugin = a_plugin(
        probing("local s = dealgo.sources() return { first = s[1] and s[1].title }"),
        frozenset({"read"}),
    )

    with site.acting_for(1):
        assert ask(plugin, found, "")["first"] == "Mine"
    with site.acting_for(2):
        assert ask(plugin, found, "")["first"] == "Theirs"


def test_outside_anybodys_work_it_sees_nothing(db, two_accounts):
    """The honest answer with no account in hand is nobody, rather than
    somebody picked arbitrarily."""
    found, plugin = a_plugin(
        probing("return { n = #dealgo.sources() }"), frozenset({"read"})
    )

    assert ask(plugin, found, "")["n"] == 0


def test_what_it_sees_is_the_shape_and_not_the_history(db, two_accounts):
    """Never what anybody has read or watched."""
    found, plugin = a_plugin(
        probing("""
          local s = dealgo.sources()[1]
          local names = {}
          for key in pairs(s) do names[#names + 1] = key end
          table.sort(names)
          return { names = table.concat(names, ",") }
        """),
        frozenset({"read"}),
    )

    with site.acting_for(1):
        said = ask(plugin, found, "")
    assert said["names"] == "enabled,key,kind,tags,title"


def test_it_can_see_the_feeds_too(db, two_accounts):
    found, plugin = a_plugin(
        probing("local f = dealgo.feeds() return { n = #f, first = f[1] and f[1].title }"),
        frozenset({"read"}),
    )

    with site.acting_for(1):
        said = ask(plugin, found, "")
    assert said["n"] == 1 and said["first"] == "My Feed"


def test_what_it_gets_back_is_a_table_it_can_walk(db, two_accounts):
    """A Python list handed straight across is something ipairs cannot walk,
    which is not an answer."""
    found, plugin = a_plugin(
        probing("""
          local n = 0
          for _, one in ipairs(dealgo.sources()) do n = n + 1 end
          return { walked = n }
        """),
        frozenset({"read"}),
    )

    with site.acting_for(1):
        assert ask(plugin, found, "")["walked"] == 1


# -- changing --------------------------------------------------------------


def test_without_the_manage_permission_nothing_changes(db, two_accounts):
    found, plugin = a_plugin(
        probing('return { did = dealgo.tag("r/mine", "loud") }'), frozenset({"read"})
    )

    with site.acting_for(1):
        assert ask(plugin, found, "")["did"] is False
    with db.session_scope() as session:
        kept = session.scalar(select(Channel).where(Channel.channel_id == "r/mine"))
    assert kept.tags == "keep"


def test_with_it_granted_it_can_tag_a_source(db, two_accounts):
    found, plugin = a_plugin(
        probing('return { did = dealgo.tag("r/mine", "loud, useful") }'),
        frozenset({"manage"}),
    )

    with site.acting_for(1):
        assert ask(plugin, found, "")["did"] is True
    with db.session_scope() as session:
        changed = session.scalar(select(Channel).where(Channel.channel_id == "r/mine"))
    assert changed.tag_list == ["loud", "useful"]


def test_it_cannot_change_another_accounts_source(db, two_accounts):
    """The same guard as reading, and the one that matters more."""
    found, plugin = a_plugin(
        probing('return { did = dealgo.tag("r/theirs", "meddled") }'),
        frozenset({"manage"}),
    )

    with site.acting_for(1):
        assert ask(plugin, found, "")["did"] is False
    with db.session_scope() as session:
        theirs = session.scalar(select(Channel).where(Channel.channel_id == "r/theirs"))
    assert theirs.tags is None


def test_it_can_switch_a_source_off(db, two_accounts):
    found, plugin = a_plugin(
        probing('return { did = dealgo.pause("r/mine", false) }'), frozenset({"manage"})
    )

    with site.acting_for(1):
        assert ask(plugin, found, "")["did"] is True
    with db.session_scope() as session:
        changed = session.scalar(select(Channel).where(Channel.channel_id == "r/mine"))
    assert changed.enabled is False


def test_something_that_is_not_there_is_a_no_rather_than_a_crash(db, two_accounts):
    found, plugin = a_plugin(
        probing('return { did = dealgo.tag("r/nowhere", "x") }'), frozenset({"manage"})
    )

    with site.acting_for(1):
        assert ask(plugin, found, "")["did"] is False


def test_what_it_adds_arrives_paused(db, two_accounts, monkeypatch):
    """A plugin may decide something is worth following. It does not get to
    decide it is worth fetching."""
    from dealgo.sources import syndication

    monkeypatch.setattr(
        syndication, "fetch", lambda _url, _http: syndication.Feed(title="r/added", items=[])
    )
    found, plugin = a_plugin(
        probing('return { key = dealgo.watch("r/added") }'), frozenset({"manage"})
    )

    with site.acting_for(1):
        assert ask(plugin, found, "")["key"] == "r/added"
    with db.session_scope() as session:
        added = session.scalar(select(Channel).where(Channel.channel_id == "r/added"))
    assert added.owner_pk == 1
    assert added.enabled is False


def test_watching_nonsense_is_nothing_rather_than_a_crash(db, two_accounts):
    """Nothing comes back, and in Lua a table entry set to nothing is a table
    entry that is not there — which is what a plugin author testing
    `if key then` is relying on."""
    found, plugin = a_plugin(
        probing('return { key = dealgo.watch("what even is this"), asked = true }'),
        frozenset({"manage"}),
    )

    with site.acting_for(1):
        said = ask(plugin, found, "")
    assert said == {"asked": True}, "it ran, and there was simply no key"


# -- one plugin's object is its own ----------------------------------------


def test_two_plugins_each_get_their_own(db, two_accounts):
    """Built per plugin, so one cannot reach another's — and one granted
    nothing cannot borrow one granted everything."""
    reading = probing("return { n = #dealgo.sources() }")
    folder = pathlib.Path(tempfile.mkdtemp())
    (folder / "open.lua").write_text(reading, encoding="utf-8")
    (folder / "shut.lua").write_text(reading.replace('"probe"', '"probe2"'), encoding="utf-8")
    found = registry.read(folder, granted={"open": frozenset({"read"})})

    opened = next(p for p in found.plugins if p.id == "open")
    shut = next(p for p in found.plugins if p.id == "shut")
    with site.acting_for(1):
        saw = opened.box.call(found.node("open:probe")._keep, opened.box.table(), opened.box.table())
        blind = shut.box.call(found.node("shut:probe2")._keep, shut.box.table(), shut.box.table())

    assert saw["n"] == 1
    assert blind["n"] == 0
