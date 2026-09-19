"""The browser scripts are generated from TypeScript. These keep the copies in
the repo honest.

The container ships the compiled JavaScript and never runs a compiler, so a
.ts file edited without rebuilding would pass every other test here and be
wrong in the browser.
"""

from __future__ import annotations

import pathlib
import re
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
TS_DIR = ROOT / "dealgo" / "web" / "ts"
STATIC = ROOT / "dealgo" / "web" / "static"

# tsc lives in node_modules, which is a developer's tool and not part of the
# app. Where it is absent — a container, a fresh clone — these skip rather
# than fail, exactly as the SCSS check does without libsass.
TSC = ROOT / "node_modules" / ".bin" / "tsc"
needs_tsc = pytest.mark.skipif(not TSC.exists(), reason="TypeScript is not installed")


def sources() -> list[pathlib.Path]:
    return sorted(p for p in TS_DIR.glob("*.ts") if not p.name.endswith(".d.ts"))


def test_every_script_has_a_typescript_source():
    """A .js in static/ with no .ts behind it is one nobody can safely edit."""
    generated = {p.stem for p in sources()}
    shipped = {p.stem for p in STATIC.glob("*.js")} - {"htmx.min"}
    assert shipped == generated


@needs_tsc
@pytest.mark.parametrize("config", ["tsconfig.json", "tsconfig.sw.json"])
def test_the_committed_javascript_matches_its_sources(tmp_path, config):
    """Compile afresh and compare: `make js` has been run, or it has not.

    Two configs, because the service worker has no DOM and the page scripts
    have no worker globals; one program cannot hold both.
    """
    subprocess.run(
        [str(TSC), "-p", config, "--outDir", str(tmp_path)],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    for built in sorted(tmp_path.glob("*.js")):
        committed = STATIC / built.name
        assert committed.exists(), f"{built.name} has never been built — run `make js`."
        assert committed.read_text() == built.read_text(), (
            f"static/{built.name} is out of date with web/ts/ — run `make js`."
        )


@needs_tsc
@pytest.mark.parametrize("config", ["tsconfig.json", "tsconfig.sw.json"])
def test_the_sources_typecheck_strictly(config):
    """The point of the exercise, enforced rather than assumed."""
    result = subprocess.run(
        [str(TSC), "-p", config, "--noEmit"], cwd=ROOT, capture_output=True, text=True
    )
    assert result.returncode == 0, result.stdout or result.stderr


def test_the_scripts_carry_no_type_assertions():
    """`!` and `as` put the types back where they started. The one cast that
    earns its place is the JSON the server sent, which nothing can check."""
    for source in sources():
        text = source.read_text()
        assert "!." not in text, f"{source.name} asserts non-null instead of proving it"


def test_the_typescript_config_is_valid_json():
    """tsc reads JSON with comments, and nothing else does. A `//` in here
    parses fine when compiling and fails in every editor, linter or script
    that opens the file as plain JSON."""
    import json

    config = json.loads((ROOT / "tsconfig.json").read_text())
    assert config["compilerOptions"]["strict"] is True


def test_typescript_is_not_needed_to_run_the_app():
    """The compiled scripts are committed, which is what keeps Node out of the
    container and out of a plain `pip install`."""
    for source in sources():
        assert (STATIC / f"{source.stem}.js").exists()


# -- how the sources are put together --------------------------------------

def top_level_lines(source: pathlib.Path) -> list[str]:
    """Statements at column zero: the file's own shape, ignoring bodies."""
    return [line for line in source.read_text().splitlines() if line and not line[0].isspace()]


def test_nothing_is_wrapped_in_a_self_calling_function():
    """The logic lives in named functions that can be read, found and called
    on their own, rather than inside an anonymous block."""
    for source in sources():
        text = source.read_text()
        assert "(function" not in text, f"{source.name} still wraps itself in an IIFE"
        assert "})();" not in text, f"{source.name} still wraps itself in an IIFE"


def test_no_state_sits_at_the_top_level():
    """These are plain scripts, and htmx re-runs one when it swaps the page in.
    A top-level `const`, `let` or `class` throws "already declared" the second
    time round — only function declarations survive being executed twice."""
    for source in sources():
        for line in top_level_lines(source):
            assert not line.startswith(("const ", "let ", "var ", "class ")), (
                f"{source.name}: `{line.strip()}` would break when the script runs twice"
            )


def test_every_file_ends_with_one_named_entry_point():
    """One call, at the bottom, by name: the only statement that is not a
    declaration."""
    entries = {
        "sections": "initSections();",
        "focus": "initFocusMode();",
        "menu": "initMenu();",
        "pwa": "initPwa();",
        "toast": "initToasts();",
        "graph": "initGraph();",
        # A worker has no page to start on: registering its handlers is the
        # equivalent, and it is a named function like every other entry.
        "sw": "listenForWorkerEvents();",
    }
    for source in sources():
        calls = [line for line in top_level_lines(source) if line.rstrip().endswith(");")]
        assert calls == [entries[source.stem]], f"{source.name} has stray top-level statements"


def test_the_logic_is_all_in_functions():
    """Every top-level line is a declaration, a comment, a closing brace, or
    the entry call."""
    allowed = (
        "function ", "async function ", "interface ", "type ", "declare ",
        "//", "/**", " *", "*/", "}", "/// <reference",
        # The closing line of a signature whose parameters were wrapped. Not a
        # statement — and a loose call that ended this way would still be
        # caught by the entry-point test, which looks for lines ending in ");".
        ")",
        "init", "listenForWorkerEvents",
    )
    for source in sources():
        for line in top_level_lines(source):
            assert line.startswith(allowed), f"{source.name}: loose statement `{line.strip()}`"


# -- the classes they name --------------------------------------------------


def queried_classes(source: pathlib.Path) -> set[str]:
    """Class names a script looks for in the page.

    Only the ones inside a selector — `closest(".graph-port")` and friends —
    because those are the ones that quietly match nothing when the markup and
    the selector drift apart.
    """
    text = source.read_text()
    found: set[str] = set()
    # The generic in `closest<HTMLElement>(...)` sits between the name and the
    # bracket, so it has to be allowed for or nothing matches at all.
    calls = re.finditer(
        r'(?:closest|querySelector|querySelectorAll)(?:<[^>()]*>)?\(\s*"([^"]+)"', text
    )
    for call in calls:
        found.update(re.findall(r"\.([a-z][a-z0-9-]*)", call.group(1)))
    return found


def test_every_class_a_script_looks_for_is_one_the_stylesheet_defines():
    """A script that queries a class nothing is ever given finds nothing, and
    says nothing about it. The stylesheet is the list of classes that exist,
    so a name that has drifted — a rename that caught a string, a typo — shows
    up here rather than as a control that silently stopped working."""
    styles = (STATIC / "app.css").read_text()
    for source in sources():
        for name in queried_classes(source):
            assert f".{name}" in styles, f"{source.name} looks for .{name}, which no rule defines"


def test_everything_that_covers_the_page_holds_it_still():
    """A modal makes the page inert, which stops it being clicked but not
    necessarily scrolled — and where showModal is missing, neither. Anything
    that opens over the page has to say so."""
    holders = [
        source for source in sources() if 'classList.toggle("page-held"' in source.read_text()
    ]
    assert {source.stem for source in holders} == {"menu", "graph"}


def defined_functions(source: pathlib.Path) -> list[str]:
    return re.findall(r"^(?:async )?function (\w+)\(", source.read_text(), re.M)


def test_no_script_carries_a_function_nobody_calls():
    """A function written but never wired up is a feature that silently does
    not exist. It compiles, it typechecks, and the button it was meant to be
    behind does nothing — which is exactly how it is found: by pressing it.

    Every name here appears at least twice: once where it is declared, and
    once where something uses it. An entry point counts, since it is called
    at the bottom of its own file.
    """
    for source in sources():
        text = source.read_text()
        for name in defined_functions(source):
            uses = len(re.findall(rf"\b{name}\b", text))
            assert uses > 1, f"{source.name}: {name}() is defined and never called"
