// The palette: dragging a new box out, and where a piece would slot.
//
// Part of the Configuration canvas; see main.ts.

/** Open or close the palette; opening it closes the finder. */
function toggleGraphPalette(state: GraphState, open: boolean): void {
  const drawer = state.parts.drawer;
  if (drawer === null) return;
  // They share an edge, so only one of them is ever out.
  if (open) toggleGraphFinder(state, false);
  drawer.hidden = !open;
  state.parts.canvas
    .closest<HTMLElement>(".graph-panel")
    ?.querySelector<HTMLElement>("[data-graph-palette]")
    ?.setAttribute("aria-expanded", open ? "true" : "false");
}

/** Start dragging a kind of box out of the palette. */
function beginGraphDrop(
  state: GraphState,
  event: PointerEvent,
  kind: string,
  which = "",
  named = "",
  under = "",
): void {
  const ghost = graphElement("div", `graph-node kind-${graphPaletteKind(kind)} is-ghost`);
  // A plugin's row is named by its plugin, so the ghost carries that rather
  // than the word "plugin", which would tell the reader nothing.
  ghost.appendChild(
    graphElement("span", "graph-node-kind", named || graphPaletteName(kind)),
  );
  ghost.style.position = "fixed";
  ghost.style.pointerEvents = "none";
  moveGraphGhost(ghost, event);
  document.body.appendChild(ghost);

  state.dropping = { kind, which, under, pointerId: event.pointerId, ghost };
}

/** Keep the dragged palette row under the pointer. */
function moveGraphGhost(ghost: HTMLElement, event: PointerEvent): void {
  ghost.style.left = `${event.clientX - 40}px`;
  ghost.style.top = `${event.clientY - 18}px`;
}

/** A pulse and a schedule are both trigger boxes, and look like one. */
function graphPaletteKind(kind: string): string {
  if (kind === "pulse" || kind === "schedule") return "trigger";
  return kind;
}

/** The name a palette row's box gets on the canvas. */
function graphPaletteName(kind: string): string {
  if (kind === "source") return "Source";
  if (kind === "plugin") return "Plugin";
  if (kind === "feed") return "Feed";
  if (kind === "filter") return "Filter";
  if (kind === "sort") return "Sort";
  if (kind === "group") return "Group";
  return kind === "pulse" ? "Pulse" : "Schedule";
}

/** The box under the pointer, for a piece being dropped onto one.
 *
 *  Asked of the document rather than worked out from coordinates: the boxes
 *  are where the browser put them, and the ghost is not in the way because it
 *  takes no pointer events. */
/** How near the underside of a box a piece has to be dropped to go into it.
 *
 *  Generous on purpose. Nobody aims at a one-pixel seam, and the slot is
 *  shown while you drag so the distance is never a guess.
 *
 *  A function rather than a constant: htmx re-inserts this script on every
 *  swap, and only top-level function declarations survive being run twice. */
function graphSlotReach(): number {
  return 150;
}

/** Where a piece would go: the empty slot at the bottom of an assembly.
 *
 *  Named by the box it would attach to — the last piece of a chain, or the
 *  box itself when there is none — and carrying where that slot is drawn. */
interface GraphSlot {
  under: number;
  x: number;
  y: number;
  width: number;
}

/** Whether a piece belongs under this kind of box.
 *
 *  `under` is the list the server sent for this piece — on its palette row
 *  while it is being dragged out, on the piece itself once it is on the
 *  canvas. Read rather than worked out again here, because a second copy of
 *  the rule is how you end up able to drop something where it is never read.
 *
 *  An empty list is not "nowhere": it is a piece whose plugin is switched
 *  off, and refusing to move it as well would be twice the punishment for
 *  something that is not the canvas's fault. */
function graphPieceGoesUnder(box: GraphNodeKind, under: string): boolean {
  if (under === "") return graphTakesPieces(box);
  return under.split(",").indexOf(box) >= 0;
}

/** Every place a piece could be slotted, with where each one sits.
 *
 *  `held` false asks for every slot there is, which is what an ordinary drag
 *  wants before anything is known about what is being dragged. */
function graphSlots(
  state: GraphState, held = false, under = ""
): GraphSlot[] {
  const below = new Map<number, GraphNodeView[]>();
  for (const node of state.nodes) {
    const host = node.piece?.under;
    if (host === undefined || host === null) continue;
    const kept = below.get(host);
    if (kept === undefined) below.set(host, [node]);
    else kept.push(node);
  }

  const found: GraphSlot[] = [];
  for (const node of state.nodes) {
    // A group is a background, and a piece belongs to the box at the top of
    // its own chain rather than starting a second one.
    if (node.kind === "group" || node.piece !== null) continue;
    // A box that ignores what is slotted into it is not somewhere a piece
    // goes: offering a slot under a source box would be an invitation to
    // nothing. The same list the notch is drawn from.
    if (!graphTakesPieces(node.kind)) continue;
    if (held && !graphPieceGoesUnder(node.kind, under)) continue;

    // Walk to the end of whatever is already slotted in, so a second piece
    // lands under the first rather than beside it.
    let last = node;
    for (let depth = 0; depth < 12; depth += 1) {
      const next = below.get(last.id)?.[0];
      if (next === undefined) break;
      last = next;
    }
    const box = state.boxes.get(last.id);
    if (box === undefined) continue;
    found.push({
      under: last.id,
      x: last.x,
      y: last.y + box.offsetHeight,
      width: box.offsetWidth,
    });
  }
  return found;
}

/** The slot a piece being dragged would drop into, if any. */
function graphSlotFor(
  state: GraphState, event: PointerEvent, held = false, under = ""
): GraphSlot | null {
  const at = pointInGraph(state, event);
  let nearest: GraphSlot | null = null;
  let best = graphSlotReach();
  for (const slot of graphSlots(state, held, under)) {
    // Measured to the slot's middle, so a box is easiest to hit from
    // directly below it and hardest from off to one side.
    const dx = at.x - (slot.x + slot.width / 2);
    const dy = at.y - slot.y;
    const away = Math.sqrt(dx * dx + dy * dy);
    if (away < best) {
      best = away;
      nearest = slot;
    }
  }
  return nearest;
}

/** Show where a piece would land, while one is dragged out of the palette. */
function markGraphSlot(state: GraphState, event: PointerEvent): void {
  const dropping = state.dropping;
  const wanted =
    dropping !== null && graphIsPiece(dropping.kind as GraphNodeKind)
      ? graphSlotFor(state, event, true, dropping.under)
      : null;
  showGraphSlot(state, wanted);
}

/** The same, for a piece already on the canvas being dragged onto one. */
function markGraphSlotFor(
  state: GraphState, event: PointerEvent, moving: number, under: string
): void {
  const slot = graphSlotFor(state, event, true, under);
  showGraphSlot(state, slot !== null && slot.under !== moving ? slot : null);
}

/** Show where a dragged piece would slot in, or hide the marker with null. */
function showGraphSlot(state: GraphState, wanted: GraphSlot | null): void {
  const marker = graphSlotMarker(state);
  if (marker === null) return;
  if (wanted === null) {
    marker.hidden = true;
    return;
  }
  marker.hidden = false;
  marker.style.left = `${wanted.x}px`;
  marker.style.top = `${wanted.y}px`;
  marker.style.width = `${wanted.width}px`;
}

/** The outline drawn where a piece would land. Made once and kept. */
function graphSlotMarker(state: GraphState): HTMLElement | null {
  const layer = state.parts.layer;
  let marker = layer.querySelector<HTMLElement>(".graph-slot");
  if (marker === null) {
    marker = graphElement("div", "graph-slot");
    marker.hidden = true;
    layer.appendChild(marker);
  }
  return marker;
}

/** Hide the slot marker. */
function hideGraphSlot(state: GraphState): void {
  const marker = state.parts.layer.querySelector<HTMLElement>(".graph-slot");
  if (marker !== null) marker.hidden = true;
}

/** Drop a palette row: a new box where it landed, or a piece into its slot. */
function finishGraphDrop(state: GraphState, event: PointerEvent): void {
  const dropping = state.dropping;
  if (dropping === null || dropping.pointerId !== event.pointerId) return;
  state.dropping = null;
  dropping.ghost.remove();
  hideGraphSlot(state);

  const frame = state.parts.canvas.getBoundingClientRect();
  const inside =
    event.clientX >= frame.left && event.clientX <= frame.right &&
    event.clientY >= frame.top && event.clientY <= frame.bottom;
  if (!inside) return;

  const at = pointInGraph(state, event);
  // A piece goes into the slot it was nearest, rather than lying where it
  // landed. Dropped nowhere near one it is simply a piece on the canvas,
  // which can be picked up and put somewhere.
  const onto = graphIsPiece(dropping.kind as GraphNodeKind)
    ? (graphSlotFor(state, event, true, dropping.under)?.under ?? null)
    : null;
  void dropGraphNode(
    state, dropping.kind, Math.round(at.x - 100), Math.round(at.y - 30),
    dropping.which, onto,
  );
}

/** Make a box of this kind, at this spot in the drawing. */
async function dropGraphNode(
  state: GraphState,
  kind: string,
  x: number,
  y: number,
  which = "",
  onto: number | null = null,
): Promise<void> {
  toggleGraphPalette(state, false);
  const before = state.nodes;
  const asking = new URLSearchParams({ kind, x: String(x), y: String(y) });
  if (onto !== null) asking.set("attach_to", String(onto));
  // The same word off the palette row, sent under whichever name the kind
  // being made reads it by.
  if (which !== "") asking.set(kind === "source" ? "source_kind" : "plugin_node", which);
  const made = await applyGraph(state, "/graph/nodes", asking);
  if (!made) return;

  // Whatever appeared is what an undo takes away. A node just added is empty,
  // so removing it costs nothing — unlike removing one that has been wired up
  // and filled, which undo deliberately does not offer.
  const fresh = graphNodeAdded(before, state.nodes);
  if (fresh === null) return;
  rememberGraphUndo(state, `the ${kind} you added`, async (): Promise<void> => {
    await applyGraph(state, `/graph/nodes/${fresh}/delete`, new URLSearchParams());
  });
}

/** Wire up the palette: its toggle, its close button, and dragging each row out. */
function listenToPalette(state: GraphState, panel: HTMLElement): void {
  panel.querySelector<HTMLElement>("[data-graph-palette]")?.addEventListener("click", (): void => {
    toggleGraphPalette(state, state.parts.drawer?.hidden === true);
  });
  panel
    .querySelector<HTMLElement>("[data-graph-palette-close]")
    ?.addEventListener("click", (): void => toggleGraphPalette(state, false));

  panel.querySelectorAll<HTMLElement>("[data-palette]").forEach((item): void => {
    const kind = item.dataset["palette"];
    if (kind === undefined) return;
    // A plugin's row says which of its boxes it is, and a source row says
    // which kind of somewhere it watches. Every other kind is the whole
    // answer by itself.
    const which = item.dataset["pluginNode"] ?? item.dataset["sourceKind"] ?? "";
    const named = item.querySelector(".palette-text strong")?.textContent ?? "";
    // A plugin's augmentation says which of the app's boxes it goes under,
    // so the drag lights up only those before anything has been asked of the
    // server about what this one is.
    const under = item.dataset["under"] ?? "";

    item.addEventListener("pointerdown", (event: PointerEvent): void => {
      event.preventDefault();
      beginGraphDrop(state, event, kind, which, named, under);
    });
    // Pressed rather than dragged: it goes in the middle of the view, which
    // is the only spot the reader is certainly looking at.
    item.addEventListener("keydown", (event: KeyboardEvent): void => {
      if (event.key !== "Enter" && event.key !== " ") return;
      event.preventDefault();
      const centre = graphViewCentre(state);
      void dropGraphNode(
        state, kind, Math.round(centre.x - 100), Math.round(centre.y - 30), which,
      );
    });
  });
}
