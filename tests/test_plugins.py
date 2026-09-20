"""Running somebody else's code inside this process.

The question a plugin raises is not "what can it do" but "what is it handed".
It is handed a table, and that table is the whole of its world.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from dealgo.plugins import registry, runtime

SHIPPED = Path(__file__).resolve().parent.parent / "dealgo" / "plugins" / "builtin"


def a_plugin(tmp_path, name: str, body: str) -> Path:
    (tmp_path / f"{name}.lua").write_text(body, encoding="utf-8")
    return tmp_path


# -- the walls -------------------------------------------------------------


def test_a_plugin_is_handed_a_world_and_nothing_else():
    """No io, no os, no require, no load, and no debug to unpick the rest."""
    box, made = runtime.load("probe.lua", """
        return { peek = function()
            return { io = io == nil, os = os == nil, require = require == nil,
                     load = load == nil, debug = debug == nil, dofile = dofile == nil }
        end }
    """)

    assert box.call(made["peek"]) == {
        "io": True, "os": True, "require": True,
        "load": True, "debug": True, "dofile": True,
    }


def test_a_plugin_can_still_do_the_work_it_is_for():
    """The walls are not the point; parsing a reference is."""
    box, made = runtime.load("probe.lua", """
        return { go = function(s) return string.upper(string.match(s, "^r/(.+)$")) end }
    """)

    assert box.call(made["go"], "r/python") == "PYTHON"


# -- the walls around a capability -----------------------------------------
#
# A capability arrives as a Python object, and Lua can ask a Python object for
# any attribute it likes. These are the tests that stop "granted one
# permission" from meaning "granted everything".


class Offered:
    """Stands in for a capability: one thing offered, one thing held back."""

    LUA_OFFERS = frozenset({"go"})

    def __init__(self):
        self.token = "SECRET"

    def go(self):
        return "did it"


class Undeclared:
    """A capability somebody added without saying what it offers."""

    def __init__(self):
        self.token = "SECRET"


def reaching(body: str, *args):
    box, made = runtime.load("probe.lua", f"""
        return {{ try = function(thing)
          local ok, value = pcall(function() {body} end)
          return ok and tostring(value) or "blocked"
        end }}
    """)
    return box.call(made["try"], *args)


def test_what_a_capability_offers_can_be_called():
    assert reaching("return thing.go()", Offered()) == "did it"


@pytest.mark.parametrize(
    "reach",
    [
        "return thing.token",
        "return thing.__class__",
        "return thing.go.__globals__",
        "return thing.__init__.__globals__['__builtins__']",
        "return thing.__dict__",
        "return thing.__getattribute__",
    ],
)
def test_nothing_else_on_a_capability_can_be_reached(reach):
    """`__class__` leads to `__globals__`, which leads to `__builtins__`,
    which leads out of the sandbox entirely. Without this one filter,
    granting any permission at all would be granting everything."""
    assert reaching(reach, Offered()) == "blocked"


def test_a_capability_cannot_be_written_to():
    assert reaching("thing.go = 1 return 'wrote'", Offered()) == "blocked"


def test_a_capability_that_never_said_what_it_offers_offers_nothing():
    """The safe default. One added later without a declaration is inert
    rather than wide open."""
    assert reaching("return thing.token", Undeclared()) == "blocked"


def test_every_capability_says_what_it_offers():
    """Checked over the real ones, so a new capability cannot be added
    without deciding what a plugin may reach on it."""
    from dealgo.plugins import permissions
    from dealgo.plugins.account import Account
    from dealgo.plugins.site import Site

    handed = [Account, Site, permissions._Clock, permissions._Log, permissions._Net]
    for thing in handed:
        offers = getattr(thing, "LUA_OFFERS", None)
        assert offers, f"{thing.__name__} does not say what it offers"
        assert all(not name.startswith("_") for name in offers), thing.__name__


def test_a_loop_that_never_ends_is_stopped():
    box, made = runtime.load("greedy.lua", "return { go = function() while true do end end }")

    with pytest.raises(runtime.PluginStopped) as stopped:
        box.call(made["go"])
    assert "ran too long" in str(stopped.value)


def test_a_plugin_cannot_switch_off_the_thing_that_stops_it():
    """The hook is set before the plugin's code runs, from outside the table
    it is given — so there is no `debug` in there to reach it with."""
    box, made = runtime.load("sneaky.lua", """
        return { go = function()
            local ok = pcall(function() debug.sethook() end)
            while true do end
        end }
    """)

    with pytest.raises(runtime.PluginStopped):
        box.call(made["go"])


def test_a_plugin_that_eats_memory_is_stopped():
    box, made = runtime.load("hungry.lua", """
        return { go = function()
            local t, i = {}, 0
            while true do i = i + 1 t[i] = string.rep("x", 4096) end
        end }
    """)

    with pytest.raises(runtime.PluginStopped) as stopped:
        box.call(made["go"])
    assert "memory" in str(stopped.value)


def test_one_plugins_values_cannot_be_used_inside_another():
    """One runtime each, and Lua enforces it: a table made in one cannot be
    handed to a function from the other. Worth pinning, because it is the
    thing that makes "one runtime per plugin" more than a comment."""
    first, made = runtime.load("first.lua", "return { go = function(t) return t.x end }")
    second, _ = runtime.load("second.lua", "return {}")

    with pytest.raises(runtime.PluginError) as crossed:
        first.call(made["go"], second.table(x=1))
    assert "different Lua runtimes" in str(crossed.value)


def test_two_plugins_cannot_see_each_others_globals():
    """One runtime each, so a plugin that fills its memory or leaves a mess
    behind takes nobody else with it."""
    first, made = runtime.load("first.lua", "shared = 'mine' return { go = function() return shared end }")
    second, also = runtime.load("second.lua", "return { go = function() return shared end }")

    assert first.call(made["go"]) == "mine"
    assert second.call(also["go"]) is None


def test_an_error_is_reported_the_way_its_author_would_want_it():
    box, made = runtime.load("cross.lua", "return { go = function() error('no thanks') end }")

    with pytest.raises(runtime.PluginError) as broke:
        box.call(made["go"])
    said = str(broke.value)
    assert "no thanks" in said
    assert "stack traceback" not in said, "a traceback helps nobody reading the list"


# -- judging what a file returned ------------------------------------------


def test_a_file_that_is_not_lua_becomes_a_sentence(tmp_path):
    found = registry.read(a_plugin(tmp_path, "broken", "this is not lua {{{"))

    assert found.working == []
    assert len(found.broken) == 1
    assert found.broken[0].trouble


def test_a_file_that_returns_nothing_is_told_so(tmp_path):
    found = registry.read(a_plugin(tmp_path, "empty", "local x = 1"))

    assert found.broken[0].trouble == "did not end with `return { … }`"


def test_a_plugin_for_another_api_version_is_refused(tmp_path):
    found = registry.read(a_plugin(tmp_path, "future", "return { api = 99, name = 'Later' }"))

    assert "plugin API 99" in found.broken[0].trouble
    assert found.broken[0].name == "Later", "it still says what it is"


def test_a_source_with_no_way_to_recognise_anything_is_refused(tmp_path):
    found = registry.read(a_plugin(tmp_path, "lazy", """
        return { api = 1, sources = { { kind = "lazy" } } }
    """))

    assert "needs a `recognise` function" in found.broken[0].trouble


def test_two_plugins_cannot_both_own_a_source_kind(tmp_path):
    body = """
        return { api = 1, name = "%s", sources = {
            { kind = "shared", recognise = function() return nil end } } }
    """
    a_plugin(tmp_path, "aaa", body % "First")
    found = registry.read(a_plugin(tmp_path, "zzz", body % "Second"))

    assert [p.title for p in found.working] == ["First"]
    assert "already provided by First" in found.broken[0].trouble


def test_a_plugin_that_throws_while_recognising_does_not_stop_the_rest(tmp_path):
    a_plugin(tmp_path, "aaa", """
        return { api = 1, name = "Cross", sources = {
            { kind = "cross", recognise = function() error("nope") end } } }
    """)
    found = registry.read(a_plugin(tmp_path, "zzz", """
        return { api = 1, name = "Calm", sources = {
            { kind = "calm", recognise = function(r)
                if r == "yes" then return { key = "k", feed = "f" } end
            end } } }
    """))

    said = found.recognise("yes")
    assert said is not None and said.plugin == "Calm"


def test_a_plugin_folder_that_is_not_there_is_not_an_error(tmp_path):
    assert registry.read(tmp_path / "nothing-here").plugins == []


def test_a_persons_own_copy_replaces_the_shipped_one(tmp_path):
    """The only way to change a shipped plugin without editing the image."""
    mine = tmp_path / "mine"
    mine.mkdir()
    (mine / "reddit.lua").write_text("""
        return { api = 1, name = "My Reddit", sources = {
            { kind = "reddit", recognise = function() return { key = "k", feed = "f" } end } } }
    """, encoding="utf-8")

    found = registry.read(SHIPPED, mine)
    reddit = [p for p in found.plugins if p.id == "reddit"]

    assert len(reddit) == 1, "the shipped one is replaced, not fought with"
    assert reddit[0].title == "My Reddit"
    assert reddit[0].replaces is not None
    assert reddit[0].ok, "and it is not treated as a clash with the one it replaced"


# -- the plugins that ship -------------------------------------------------


def test_every_shipped_plugin_loads():
    found = registry.read(SHIPPED)

    assert [p.trouble for p in found.plugins] == [None] * len(found.plugins)
    assert {p.id for p in found.plugins} == {
        "youtube", "reddit", "bluesky", "substack", "shape",
    }


def test_only_youtube_may_fill_a_youtube_playlist():
    """The one thing that does not generalise, now declared by the plugin
    that is the exception rather than hardcoded in the host."""
    kinds = {k.kind: k for k in registry.read(SHIPPED).source_kinds()}

    assert kinds["youtube"].playlistable is True
    assert [k for k in kinds.values() if k.playlistable] == [kinds["youtube"]]


@pytest.mark.parametrize(
    "typed, kind",
    [
        ("r/python", "reddit"),
        ("/r/ElectricalEngineering/", "reddit"),
        ("https://old.reddit.com/r/ee/comments/x/", "reddit"),
        ("@jay.bsky.social", "bluesky"),
        ("https://bsky.app/profile/jay.bsky.social", "bluesky"),
        ("name.substack.com", "substack"),
        ("https://astralcodexten.substack.com/p/x", "substack"),
        ("UCzzzzzzzzzzzzzzzzzzzzzz", "youtube"),
        ("@mkbhd", "youtube"),
        ("https://www.youtube.com/@mkbhd", "youtube"),
    ],
)
def test_the_shipped_plugins_recognise_what_they_should(typed, kind):
    found = registry.read(SHIPPED).recognise(typed)

    assert found is not None, f"nobody claimed {typed}"
    assert found.kind == kind


def test_a_youtube_handle_is_handed_back_for_the_host_to_finish():
    """Turning one into a channel id needs the account's Google connection,
    which is not a plugin's to hold."""
    found = registry.read(SHIPPED).recognise("@mkbhd")

    assert found.needs_host is True
    assert found.feed_url == "", "it cannot know where the feed is yet"


def test_a_channel_id_needs_nobody(): 
    found = registry.read(SHIPPED).recognise("UCzzzzzzzzzzzzzzzzzzzzzz")

    assert found.needs_host is False
    assert found.feed_url.endswith("channel_id=UCzzzzzzzzzzzzzzzzzzzzzz")


def test_the_reddit_plugin_offers_a_mirror():
    """Knowledge about Open RSS belongs with the source that needs it, not in
    the host."""
    found = registry.read(SHIPPED)

    assert found.mirror("reddit", "r/python") == "https://openrss.org/reddit.com/r/python"
    assert found.mirror("youtube", "UCzzz") is None


def test_the_shipped_plugins_are_packaged_with_the_app():
    """`package-data` globs are not recursive, and a missing one here is not
    a missing icon: the image would start and understand nothing you typed."""
    import tomllib

    root = Path(__file__).resolve().parent.parent
    config = tomllib.loads((root / "pyproject.toml").read_text())
    globs = config["tool"]["setuptools"]["package-data"]["dealgo"]

    assert "plugins/builtin/*.lua" in globs
