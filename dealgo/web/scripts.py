"""Join a script written as several files into the one file the page loads.

The canvas is too large to read as one file, so it is written as a folder of
parts (web/ts/graph/) and compiled on its own (tsconfig.graph.json). The page
still loads a single graph.js: plain scripts that htmx re-inserts are not
guaranteed to run in order, and one file is the only order that cannot be
lost. The parts share one scope either way, as every plain script does.

Every part only declares; main.ts holds the one call that starts it all, so
it goes last. Like the stylesheet, the result is committed — running De-Algo
needs no Node — and a test checks it is current.
"""

from __future__ import annotations

from pathlib import Path

WEB = Path(__file__).resolve().parent
ROOT = WEB.parent.parent

#: Each script written as a folder: where tsc puts its parts, and where the
#: joined script goes.
JOINED = {"graph": ROOT / "build" / "scripts" / "graph"}

#: The part holding the entry call, which has to run after every declaration.
LAST = "main.js"


def join(parts: Path) -> str:
    """The parts in one script: every declaration, then the entry call."""
    files = sorted(parts.glob("*.js"), key=lambda path: (path.name == LAST, path.name))
    if not files or files[-1].name != LAST:
        raise SystemExit(f"{parts} has no {LAST} — run tsc -p tsconfig.graph.json first")
    return "\n".join(path.read_text() for path in files)


def build() -> list[Path]:
    """Write each joined script into static/, and say where they went."""
    written = []
    for name, parts in JOINED.items():
        target = WEB / "static" / f"{name}.js"
        target.write_text(join(parts))
        written.append(target)
    return written


if __name__ == "__main__":  # `python -m dealgo.web.scripts`, after tsc
    for path in build():
        print(path)
