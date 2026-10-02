# Frontend

Server-rendered HTML, one stylesheet, a handful of small scripts, and one rich client: the canvas.
No framework, no bundler, no Node at runtime.

## Files

| Source | Compiled to (committed) | Does |
| --- | --- | --- |
| `web/scss/app.scss` + partials | `web/static/app.css` | All styles; `_tokens.scss` holds colours, spacing, dark mode; `graph/` the canvas |
| `web/ts/graph/` (18 parts) | `static/graph.js` | The Configuration canvas |
| `web/ts/focus/` (8 parts) | `static/focus.js` | Focus mode: one item at a time, timers |
| `web/ts/sections.ts` | `static/sections.js` | Collapsible sections |
| `web/ts/menu.ts` | `static/menu.js` | Menus |
| `web/ts/toast.ts` | `static/toast.js` | Flash messages as toasts |
| `web/ts/pwa.ts` | `static/pwa.js` | Service-worker registration, install prompt, offline banner |
| `web/ts/sw.ts` | `static/sw.js` | Service worker (separate `tsconfig.sw.json`, WebWorker lib) |
| — | `static/htmx.min.js` | htmx, vendored |

Build: `make css` (libsass via `ops/build_css.py`), `make js`, `make assets` (both). Tests
fail if committed output differs from sources (`test_styles.py`, `test_scripts.py`).

`make js` runs three TypeScript programs: the single-file page scripts (`tsconfig.json`), the
service worker (`tsconfig.sw.json`), and the scripts written as a folder of parts
(`tsconfig.parts.json`, into `build/scripts/`). `ops/join_scripts.py` then joins each
folder's parts into the one file its page loads, `main.js` last.

## Scripts written as parts

A script too large to read as one file is a folder: `web/ts/graph/`, `web/ts/focus/`. Each part
holds one area (drawing, the panel, dragging, the timer, the player…) and only declares; `main.ts`
holds the one entry call. The parts share one global scope, as plain scripts on a page do, so a part
calls another's functions with no import.

They are **joined, not loaded separately**: htmx re-inserts a swapped page's scripts, and
re-inserted external scripts are not guaranteed to run in order. One file is the one order that
cannot be lost. To add a script written as parts, add its folder to `tsconfig.parts.json` and to
`JOINED` in `ops/join_scripts.py`.

## Script rules (enforced by `tests/test_scripts.py`)

The scripts are **plain scripts, not modules**, and htmx re-executes them when it swaps a page in
with `hx-boost`. So:

- **Top-level `function` declarations only.** A top-level `const`/`let`/`class` throws
  "already declared" on the second run.
- **No IIFEs.** Logic lives in named functions that can be found and tested.
- **One entry call at the bottom** (`initGraph();`, `initFocusMode();`, …), and nothing else at the
  top level. In a script written as parts, that call is in `main.ts`.
- **No `!` non-null assertions.** The one permitted cast is server JSON.
- Strict TypeScript: `noUncheckedIndexedAccess`, `exactOptionalPropertyTypes`, and the rest.
- Every CSS class a script queries must exist in the stylesheet.

## The canvas — `web/ts/graph/`

**The server owns the graph.** Every change is a POST that answers with the whole graph; the
drawing is thrown away and rebuilt from that answer. A refused wire simply never appears.

The only local state is in-flight interaction:

- **Dragging** moves a box locally and saves on release (one POST, not one per pixel).
- **Wiring** draws a provisional wire from a port to the pointer until dropped.
- **Slotting** a piece previews where it would land; the server's `attach` decides.

| Part | Holds |
| --- | --- |
| `model.ts` | The kinds of box and piece, and what each may do |
| `reading.ts` | Checked shapes for the server's JSON — `asGraph`, `asGraphNode`, … (the only casts) |
| `server.ts` | `askGraph`: every change is a POST answered with the whole graph |
| `drawing.ts` | `renderGraph`, `drawGraphNodes`, `drawGraphWires`, `placeGraphPieces` |
| `panel.ts` | The panel beside a picked box: tabs, `graphNodeForm`, removing |
| `piece-fields.ts`, `source-fields.ts`, `box-fields.ts` | The panel's fields, per kind |
| `dragging.ts` | Pointer: pan, wire, move, marquee, resize |
| `picking.ts` | Picking boxes and wires, keys, clicks |
| `filtered.ts`, `trying.ts` | What a Filter held; Test without running |
| `running.ts` | `followGraphRun`, `paintGraphRun` — polls `/api/graph/run` |
| `undo.ts` | `rememberGraphUndo`, `undoGraph` |
| `palette.ts`, `dialogs.ts` | The palette and slotting; the log, reach-back and load-group dialogs |
| `finder.ts` | Finding a group on a large canvas |
| `main.ts` | `initGraph` → `findGraphs` → `startGraph`, and the entry call |

The palette lists host boxes and pieces, plus each loaded plugin's augmentations with the boxes
they fit under (as pills).

## Focus mode — `web/ts/focus/`

Shows one item at a time. A Decay timer counts down per item (`view_seconds`); the reader can pause
it unless a Lock piece set `view_locked`. When it runs out, or the reader moves on, it POSTs
`/focus/{id}/finished`. Parts: `model`, `page`, `timer`, `showing`, `queue`, `advancing`, `player`,
`main`.

## Service worker — `sw.ts`

Offline means **reading what was already loaded**: the shell, styles, visited pages and their
thumbnails. Writes need the server and fail visibly offline. The cache name includes the version
query the worker was registered with, so a deploy refreshes everything.

## Harnesses

`tests/graph_harness.js`, `toast_harness.js`, `sw_harness.js` load the compiled scripts into Node's
`vm` with a stub DOM and print decisions as JSON for pytest to assert on. See [Testing](Testing.md).

**Related:** [Web Layer](Web%20Layer.md) · [Building and Releasing](Building%20and%20Releasing.md)
