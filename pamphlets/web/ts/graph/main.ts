// The Configuration canvas: channels, filters and feeds as boxes and wires.
//
// The server owns the graph. Every change here is a POST that answers with
// the whole graph again, and the drawing is thrown away and redone from that
// answer — so what is on screen is always something the database agreed to,
// and a refused wire simply never appears.
//
// The one exception is dragging: a box follows the pointer locally and its
// position is saved on release, because a round trip per pixel is absurd.
//
// Written as several files, one per part of the canvas, and joined into the
// one graph.js the page loads (`make js`, ops/join_scripts.py). They share
// one scope, as every plain script on a page does.
//
// Top-level `function` declarations only, and no statement but the one entry
// call at the end of main.ts: see tests/test_scripts.py.

/** Bring the whole canvas into the window, if any of it is out. A canvas
 *  taller than the window is lined up with its top. */
function scrollToGraph(canvas: HTMLElement): void {
  const box = canvas.getBoundingClientRect();
  const margin = 8;
  if (box.top >= 0 && box.bottom <= window.innerHeight) return;
  const still = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  window.scrollTo({
    top: window.scrollY + box.top - margin,
    behavior: still ? "auto" : "smooth",
  });
}

/** Wire up one canvas: pointer, clicks, keys, forms, and its drawers and dialogs. */
function listenToGraph(state: GraphState): void {
  const { canvas } = state.parts;
  const panel = canvas.closest<HTMLElement>(".graph-panel");

  canvas.addEventListener("pointerdown", (event: PointerEvent): void => onGraphPointerDown(state, event));
  canvas.addEventListener("pointerup", (event: PointerEvent): void => onGraphPointerUp(state, event));
  canvas.addEventListener("pointercancel", (event: PointerEvent): void => onGraphPointerUp(state, event));
  canvas.addEventListener("click", (event: MouseEvent): void => onGraphClick(state, event));
  // Two presses on a box, close together and without moving, open its
  // editor, as a flow tool's double-click does. Counted here rather than
  // left to the browser's dblclick: the first press opens the box's panel,
  // which draws every box afresh, so the second lands on a new element and
  // the browser never puts the two together.
  let pressed: { node: string; x: number; y: number } | null = null;
  let tapped: { node: string; at: number } | null = null;
  canvas.addEventListener("pointerdown", (event: PointerEvent): void => {
    const target = event.target;
    const node = target instanceof Element && target.closest(".graph-pop") === null
      ? target.closest<HTMLElement>("[data-node]")?.dataset["node"]
      : undefined;
    pressed = node === undefined || event.button !== 0 ? null : { node, x: event.clientX, y: event.clientY };
  });
  canvas.addEventListener("pointerup", (event: PointerEvent): void => {
    const was = pressed;
    pressed = null;
    if (was === null || Math.hypot(event.clientX - was.x, event.clientY - was.y) > 5) {
      tapped = null;
      return;
    }
    const now = performance.now();
    if (tapped !== null && tapped.node === was.node && now - tapped.at < 450) {
      tapped = null;
      openGraphEditor(state, Number(was.node));
      return;
    }
    tapped = { node: was.node, at: now };
  });
  // Clicking into the canvas means working on it, so the page scrolls to
  // show all of it rather than leaving it half under the fold. On the click,
  // not the press: scrolling under a drag that is starting moves the box
  // away from the pointer holding it.
  canvas.addEventListener("click", (): void => scrollToGraph(canvas));
  canvas.addEventListener("keydown", (event: KeyboardEvent): void => onGraphKeyDown(state, event));
  canvas.addEventListener("submit", (event: SubmitEvent): void => {
    void onGraphSubmit(state, event);
  });

  // On the document, not the canvas: after a drag the focus may be anywhere,
  // and an undo that only works while the canvas happens to be focused is an
  // undo nobody can rely on.
  document.addEventListener("keydown", (event: KeyboardEvent): void => {
    if (!(event.ctrlKey || event.metaKey) || event.key.toLowerCase() !== "z") return;
    if (!graphTakesTheKey(event.target)) return;
    event.preventDefault();
    void undoGraph(state);
  });

  // The wheel zooms while the pointer is over the canvas. The canvas fills
  // the page, so a wheel there can only have been meant for it — unless it
  // was over one of the panels laid on top of it, which scroll.
  canvas.addEventListener(
    "wheel",
    (event: WheelEvent): void => {
      if (graphWheelBelongsToAPanel(event.target, canvas)) return;
      event.preventDefault();
      // A line-by-line wheel reports small deltas and a trackpad reports
      // large ones, so the step is taken from the direction, not the size.
      zoomGraph(state, event.deltaY < 0 ? 1.12 : 1 / 1.12, event.clientX, event.clientY);
    },
    { passive: false },
  );

  // On the window, not the canvas: a palette box is dragged from outside it,
  // and a box dragged past its edge should keep following the pointer.
  window.addEventListener("pointermove", (event: PointerEvent): void => {
    if (state.dropping !== null && state.dropping.pointerId === event.pointerId) {
      moveGraphGhost(state.dropping.ghost, event);
      markGraphSlot(state, event);
      return;
    }
    onGraphPointerMove(state, event);
  });
  window.addEventListener("pointerup", (event: PointerEvent): void => {
    finishGraphDrop(state, event);
  });

  if (panel !== null) listenToPalette(state, panel);

  panel?.querySelector<HTMLElement>("[data-graph-undo]")?.addEventListener("click", (): void => {
    void undoGraph(state);
  });

  if (panel !== null) listenForGraphLoad(state, panel);
  if (panel !== null) listenForGraphReach(state, panel);
  if (panel !== null) listenForGraphLog(state, panel);
  if (panel !== null) listenForGraphFinder(state, panel);

  const catching = graphCatchDialog(state);
  catching?.querySelector<HTMLElement>("[data-graph-catch-close]")?.addEventListener(
    "click",
    (): void => catching.close(),
  );
  // A click on the backdrop lands on the dialog itself, not on its contents.
  catching?.addEventListener("click", (event: MouseEvent): void => {
    if (event.target === catching) catching.close();
  });
  // Every way of shutting it ends here — the button, the backdrop, Esc — so
  // this is the one place that has to give the page back.
  catching?.addEventListener("close", (): void => holdPageForGraph(false));

  // Boxes are measured to place the wires, so a resize moves them.
  window.addEventListener("resize", (): void => drawGraphWires(state));
}

/** Start one canvas, once: build its state and load the graph from the server. */
function startGraph(canvas: HTMLElement): void {
  if (canvas.dataset["ready"] === "1") return;
  const parts = graphPartsIn(canvas);
  if (parts === null) return;
  canvas.dataset["ready"] = "1";

  const state: GraphState = {
    parts,
    nodes: [],
    wires: [],
    sources: [],
    boxes: new Map<number, HTMLElement>(),
    selectedNode: null,
    picked: new Set<number>(),
    selectedWire: null,
    drag: null,
    ghost: null,
    run: new Map<number, GraphMark>(),
    watching: false,
    busy: false,
    panX: 0,
    panY: 0,
    zoom: 1,
    dropping: null,
    tab: "settings",
    trial: null,
    undo: [],
  };
  listenToGraph(state);
  panGraph(state, 0, 0);
  void openGraph(state);
}

/** Draw the graph, then pick up any run already in flight. */
async function openGraph(state: GraphState): Promise<void> {
  await applyGraph(state, "/api/graph", null);
  const run = asGraphRun(await askGraph("/api/graph/run", null).catch((): null => null));
  if (run !== null && run.running) void followGraphRun(state);
}

/** Start every canvas under `root`. */
function findGraphs(root: ParentNode): void {
  root.querySelectorAll<HTMLElement>("[data-graph]").forEach(startGraph);
}

/** The canvas's entry point: start canvases now, on load, and after every htmx swap. */
function initGraph(): void {
  document.addEventListener("DOMContentLoaded", (): void => findGraphs(document));
  document.body.addEventListener("htmx:afterSwap", (): void => findGraphs(document));
  findGraphs(document);
}

initGraph();
