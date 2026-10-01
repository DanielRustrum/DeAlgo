# Frontend

Server-rendered HTML, one stylesheet, a handful of small scripts, and one rich client: the canvas.
No framework, no bundler, no Node at runtime.

## Files

| Source | Compiled to (committed) | Does |
| --- | --- | --- |
| `web/scss/app.scss` + partials | `web/static/app.css` | All styles; `_tokens.scss` holds colours, spacing, dark mode |
| `web/ts/graph.ts` | `static/graph.js` | The Configuration canvas |
| `web/ts/focus.ts` | `static/focus.js` | Focus mode: one item at a time, timers |
| `web/ts/sections.ts` | `static/sections.js` | Collapsible sections |
| `web/ts/menu.ts` | `static/menu.js` | Menus |
| `web/ts/toast.ts` | `static/toast.js` | Flash messages as toasts |
| `web/ts/pwa.ts` | `static/pwa.js` | Service-worker registration, install prompt, offline banner |
| `web/ts/sw.ts` | `static/sw.js` | Service worker (separate `tsconfig.sw.json`, WebWorker lib) |
| — | `static/htmx.min.js` | htmx, vendored |

Build: `make css` (libsass via `python -m dealgo.web.styles`), `make js` (`tsc` twice), `make assets`
(both). Tests fail if committed output differs from sources (`test_styles.py`, `test_scripts.py`).

## Script rules (enforced by `tests/test_scripts.py`)

The scripts are **plain scripts, not modules**, and htmx re-executes them when it swaps a page in
with `hx-boost`. So:

- **Top-level `function` declarations only.** A top-level `const`/`let`/`class` throws
  "already declared" on the second run.
- **No IIFEs.** Logic lives in named functions that can be found and tested.
- **One entry call at the bottom** (`initGraph();`, `initFocusMode();`, …), and nothing else at the
  top level.
- **No `!` non-null assertions.** The one permitted cast is server JSON.
- Strict TypeScript: `noUncheckedIndexedAccess`, `exactOptionalPropertyTypes`, and the rest.
- Every CSS class a script queries must exist in the stylesheet.

## The canvas — `graph.ts`

**The server owns the graph.** Every change is a POST that answers with the whole graph; the
drawing is thrown away and rebuilt from that answer. A refused wire simply never appears.

The only local state is in-flight interaction:

- **Dragging** moves a box locally and saves on release (one POST, not one per pixel).
- **Wiring** draws a provisional wire from a port to the pointer until dropped.
- **Slotting** a piece previews where it would land; the server's `attach` decides.

Main parts (184 top-level functions, named by verb + `Graph`):

| Area | Representative functions |
| --- | --- |
| Validating server JSON | `asGraph`, `asGraphNode`, `asGraphWire`, … (the only casts) |
| Fetch and apply | `askGraph`, `applyGraph`, `renderGraph` |
| Drawing | `drawGraphNodes`, `drawGraphWires`, `placeGraphPieces`, `drawGraphGroup` |
| Pointer | `onGraphPointerDown/Move/Up`, `beginGraphPan/Wire/Move/Resize/Pick` |
| Side panel | `renderGraphPopover`, `graphNodeForm`, `graph…Fields` per kind |
| Palette and slotting | `toggleGraphPalette`, `beginGraphDrop`, `markGraphSlot`, `finishGraphDrop` |
| Runs | `fireGraphPulse`, `followGraphRun`, `paintGraphRun` (polls `/api/graph/run`) |
| Test and filtered | `tryGraph`, `showGraphVerdict`, `showGraphFiltered` |
| Undo | `rememberGraphUndo`, `undoGraph` |
| Entry | `initGraph` → `findGraphs` → `startGraph` |

The palette lists host boxes and pieces, plus each loaded plugin's augmentations with the boxes
they fit under (as pills).

## Focus mode — `focus.ts`

Shows one item at a time. A Decay timer counts down per item (`view_seconds`); the reader can pause
it unless a Lock piece set `view_locked`. When it runs out, or the reader moves on, it POSTs
`/focus/{id}/finished`.

## Service worker — `sw.ts`

Offline means **reading what was already loaded**: the shell, styles, visited pages and their
thumbnails. Writes need the server and fail visibly offline. The cache name includes the version
query the worker was registered with, so a deploy refreshes everything.

## Harnesses

`tests/graph_harness.js`, `toast_harness.js`, `sw_harness.js` load the compiled scripts into Node's
`vm` with a stub DOM and print decisions as JSON for pytest to assert on. See [Testing](Testing.md).

**Related:** [Web Layer](Web%20Layer.md) · [Building and Releasing](Building%20and%20Releasing.md)
