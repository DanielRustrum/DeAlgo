"""A plugin split across files: plugin.lua first, the rest by `require`."""

from __future__ import annotations

from pathlib import Path

from dealgo.plugins import registry


def a_folder(tmp_path: Path, files: dict[str, str], name: str = "split") -> Path:
    """A plugins folder holding one plugin in a folder of its own."""
    home = tmp_path / name
    for relative, body in files.items():
        path = home / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
    return tmp_path


ENTRY = """
local parse = require("parse")
local dates = require("lib.dates")
return { api = 1, name = "Split", sources = { {
  kind = "split",
  recognise = function(r)
    local key = parse.key(r)
    if key then return { key = key, feed = "https://x/" .. key, title = dates.stamp() } end
  end } } }
"""


def test_a_plugin_requires_its_other_files_by_name(tmp_path):
    found = registry.read(a_folder(tmp_path, {
        "plugin.lua": ENTRY,
        "parse.lua": 'local M = {} function M.key(r) return string.match(r, "^split/(%w+)$") end return M',
        "lib/dates.lua": 'return { stamp = function() return "today" end }',
    }))

    assert found.broken == []
    said = found.recognise("split/abc")
    assert said is not None and said.key == "abc" and said.title == "today"


def test_a_module_runs_once_however_many_files_ask_for_it(tmp_path):
    found = registry.read(a_folder(tmp_path, {
        "plugin.lua": """
            local a = require("counter")
            local b = require("counter")
            local again = require("other")
            return { api = 1, name = "Count:" .. a.n .. b.n .. again }
        """,
        "counter.lua": "count = (count or 0) + 1 return { n = count }",
        "other.lua": 'return require("counter").n',
    }))
    assert found.working[0].name == "Count:111"


def test_a_module_shares_the_plugins_world(tmp_path):
    """Its globals and capabilities, not a fresh world of its own."""
    found = registry.read(a_folder(tmp_path, {
        "plugin.lua": 'shared = "from entry" return { api = 1, name = require("reader") }',
        "reader.lua": "return shared .. (settings and ' with settings' or '')",
    }))
    assert found.working[0].name == "from entry with settings"


def broken_by(tmp_path, entry: str, files: dict[str, str] | None = None) -> str:
    found = registry.read(a_folder(tmp_path, {"plugin.lua": entry, **(files or {})}))
    assert found.working == []
    return found.broken[0].trouble


def test_nothing_outside_the_folder_can_be_required(tmp_path):
    # Beside the plugins folder, not in it, where it would load as a plugin.
    (tmp_path / "secret.lua").write_text("return 'leaked'")
    plugins = tmp_path / "plugins"
    for asked in ("../secret", "..secret", "/etc/passwd", "a/b"):
        trouble = broken_by(plugins, f'require("{asked}") return {{ api = 1 }}')
        assert "is not a module name" in trouble, asked


def test_a_missing_module_says_which(tmp_path):
    trouble = broken_by(tmp_path, 'require("nowhere") return { api = 1 }')
    assert "there is no nowhere.lua in the plugin's folder" in trouble


def test_the_entry_file_cannot_be_required(tmp_path):
    trouble = broken_by(tmp_path, 'require("plugin") return { api = 1 }')
    assert "entry file" in trouble


def test_a_module_that_requires_itself_is_an_error_not_a_hang(tmp_path):
    trouble = broken_by(tmp_path, 'require("loop") return { api = 1 }', {
        "loop.lua": 'return require("round")',
        "round.lua": 'return require("loop")',
    })
    assert "requires itself" in trouble


def test_a_module_with_a_mistake_is_reported_with_its_own_name(tmp_path):
    trouble = broken_by(tmp_path, 'require("typo") return { api = 1 }', {"typo.lua": "return {"})
    assert "typo.lua" in trouble


def test_a_single_file_plugin_has_nothing_to_require(tmp_path):
    (tmp_path / "alone.lua").write_text('require("parse") return { api = 1 }')
    found = registry.read(tmp_path)
    assert "only a plugin in a folder of its own" in found.broken[0].trouble
