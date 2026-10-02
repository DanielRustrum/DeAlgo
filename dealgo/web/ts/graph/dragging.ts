// Picking things up: panning, wiring, moving, marquee selection and resizing.
//
// Part of the Configuration canvas; see main.ts.

/** The node a pointer is on, whatever shape that node is drawn as.
 *
 *  A group is a rectangle rather than a box, so it carries its own class —
 *  and looking only for the box's meant a group could not be pressed at all:
 *  not moved, not resized, not opened, and so not removed either. */
function graphNodeIdFrom(target: EventTarget | null): number | null {
  if (!(target instanceof Element)) return null;
  const box = target.closest<HTMLElement>(".graph-node, .graph-group-box");
  const raw = box?.dataset["node"];
  return raw === undefined ? null : Number(raw);
}

/** The wire under the pointer, if the pointer is on one. */
function graphWireIdFrom(target: EventTarget | null): string | null {
  if (!(target instanceof Element)) return null;
  return target.closest<Element>("[data-wire]")?.getAttribute("data-wire") ?? null;
}

/** Where a pointer is in the drawing, whatever the canvas is panned to. */
function pointInGraph(state: GraphState, event: { clientX: number; clientY: number }): {
  x: number;
  y: number;
} {
  const frame = state.parts.canvas.getBoundingClientRect();
  return {
    x: (event.clientX - frame.left - state.panX) / state.zoom,
    y: (event.clientY - frame.top - state.panY) / state.zoom,
  };
}

/** The fields every drag shares, whatever kind it turns out to be. */
function graphGrab(state: GraphState, event: PointerEvent): GraphDrag {
  return {
    kind: "pan",
    nodeId: 0,
    pressed: 0,
    pointerId: event.pointerId,
    grabX: 0,
    grabY: 0,
    fromX: event.clientX,
    fromY: event.clientY,
    scrollX: state.panX,
    scrollY: state.panY,
    moved: false,
    startX: 0,
    startY: 0,
    carried: [],
  };
}

/** Whether the pointer has gone far enough that this is a drag and not a click.
 *
 *  A few pixels of travel while pressing is normal, and without this a box
 *  could not be picked with a mouse that is not perfectly still. */
function graphMovedFar(drag: GraphDrag, event: PointerEvent): boolean {
  return Math.abs(event.clientX - drag.fromX) > 3 || Math.abs(event.clientY - drag.fromY) > 3;
}

/** Start panning the canvas from where the pointer went down. */
function beginGraphPan(state: GraphState, event: PointerEvent): void {
  state.drag = graphGrab(state, event);
  state.parts.canvas.classList.add("is-panning");
}

/** Start drawing a wire from a box's out port, with a ghost following the pointer. */
function beginGraphWire(state: GraphState, event: PointerEvent, nodeId: number): void {
  state.drag = { ...graphGrab(state, event), kind: "wire", nodeId };
  const from = graphPortPoint(state, nodeId, "out");
  if (from === null) return;
  state.ghost = graphSvgPath("graph-wire wire-ghost", graphCurve(from.x, from.y, from.x, from.y));
  state.parts.wires.appendChild(state.ghost);
}

/** Start moving a box, remembering where on it the pointer grabbed. */
function beginGraphMove(
  state: GraphState,
  event: PointerEvent,
  node: GraphNodeView,
  pressed?: number,
): void {
  const at = pointInGraph(state, event);
  state.drag = {
    ...graphGrab(state, event),
    kind: "move",
    nodeId: node.id,
    pressed: pressed ?? node.id,
    grabX: at.x - node.x,
    grabY: at.y - node.y,
    startX: node.x,
    startY: node.y,
    // What travels with it: what a group surrounds, or the rest of what is
    // picked. Their starting positions are noted here so each can be moved by
    // the same amount without asking again half-way through the drag.
    carried: graphTravelsWith(state, node).map(
      (held): { node: GraphNodeView; x: number; y: number } => ({
        node: held,
        x: held.x,
        y: held.y,
      }),
    ),
  };
  state.boxes.get(node.id)?.classList.add("is-held");
}

/** What moves when this node moves.
 *
 *  A group takes what it surrounds. Anything else takes the rest of what is
 *  picked, so several nodes dragged by one of them keep their arrangement. */
function graphTravelsWith(state: GraphState, node: GraphNodeView): GraphNodeView[] {
  if (node.kind === "group") return graphSurrounded(state, node);
  if (!state.picked.has(node.id) || state.picked.size < 2) return [];
  return state.nodes.filter(
    (entry): boolean => entry.id !== node.id && state.picked.has(entry.id),
  );
}

/** What a group surrounds, worked out the way the server works it out. */
function graphSurrounded(state: GraphState, group: GraphNodeView): GraphNodeView[] {
  if (group.kind !== "group") return [];
  const right = group.x + (group.size?.width ?? 520);
  const bottom = group.y + (group.size?.height ?? 300);
  return state.nodes.filter(
    (node): boolean =>
      node.id !== group.id &&
      node.kind !== "group" &&
      node.x >= group.x &&
      node.x <= right &&
      node.y >= group.y &&
      node.y <= bottom,
  );
}

/** Drag a box round the canvas; what it covers is what gets picked. */
function beginGraphPick(state: GraphState, event: PointerEvent): void {
  const at = pointInGraph(state, event);
  state.drag = { ...graphGrab(state, event), kind: "pick", startX: at.x, startY: at.y };

  const marquee = graphElement("div", "graph-marquee");
  marquee.style.left = `${at.x}px`;
  marquee.style.top = `${at.y}px`;
  state.parts.layer.appendChild(marquee);
}

/** The box being dragged, if one is. */
function graphMarquee(state: GraphState): HTMLElement | null {
  return state.parts.layer.querySelector<HTMLElement>(".graph-marquee");
}

/** Start resizing a group from its current size. */
function beginGraphResize(state: GraphState, event: PointerEvent, node: GraphNodeView): void {
  state.drag = {
    ...graphGrab(state, event),
    kind: "resize",
    nodeId: node.id,
    grabX: node.size?.width ?? 520,
    grabY: node.size?.height ?? 300,
  };
}

/** Decide what a press on the canvas starts: a wire, a move, a resize, a marquee or a pan. */
function onGraphPointerDown(state: GraphState, event: PointerEvent): void {
  if (event.button !== 0) return;
  const target = event.target;
  // The open box is a form: a click in it is meant for the field it landed
  // on, and must not reach the canvas, which would read it as a click on
  // empty space and close the very box being typed into.
  if (target instanceof Element && target.closest(".graph-pop")) return;
  // The palette sits over the canvas rather than on it. Pressing a fold, or
  // the space between rows, is not a press on the drawing underneath — and
  // taking it as one starts a pan and swallows the fold.
  if (target instanceof Element && target.closest(".graph-palette")) return;
  // Buttons and links inside the canvas do their own thing.
  if (target instanceof Element && target.closest("a, button")) return;

  const wire = graphWireIdFrom(target);
  if (wire !== null) {
    pickGraphWire(state, wire);
    return;
  }

  const nodeId = graphNodeIdFrom(target);
  if (nodeId === null) {
    // Empty canvas: drag it to move the whole drawing under the window. A
    // finger is left alone, because a touch screen already scrolls a box
    // that overflows and two things doing it at once fight each other.
    if (event.pointerType !== "mouse") {
      clearGraphPick(state);
      return;
    }
    if (event.shiftKey) beginGraphPick(state, event);
    else beginGraphPan(state, event);
    state.parts.canvas.setPointerCapture(event.pointerId);
    event.preventDefault();
    return;
  }
  let node = state.nodes.find((entry): boolean => entry.id === nodeId);
  if (node === undefined) return;

  // A slotted piece travels with whatever it is slotted into: dragging one
  // drags the assembly, the way picking up a puzzle by a piece picks up the
  // part it belongs to. Its own position is worked out from its host's.
  while (node !== undefined && node.piece !== null && node.piece.under !== null) {
    const above: number = node.piece.under;
    node = state.nodes.find((entry): boolean => entry.id === above);
  }
  if (node === undefined) return;
  const grabbed = node.id;

  // Shift on a node adds it to what is picked rather than replacing it — but
  // a group is a background, and shift over one means the same as shift over
  // the canvas: draw a box round what is inside it.
  if (event.shiftKey) {
    if (node.kind === "group") {
      beginGraphPick(state, event);
      state.parts.canvas.setPointerCapture(event.pointerId);
      event.preventDefault();
      return;
    }
    alsoPickGraphNode(state, grabbed);
    event.preventDefault();
    return;
  }

  const onGrip = target instanceof Element && target.closest<HTMLElement>("[data-grip]");
  const onPort = target instanceof Element && target.closest<HTMLElement>(".graph-port");
  if (onGrip) beginGraphResize(state, event, node);
  else if (onPort && onPort.dataset["port"] === "out") beginGraphWire(state, event, grabbed);
  else beginGraphMove(state, event, node, nodeId);

  state.parts.canvas.setPointerCapture(event.pointerId);
  event.preventDefault();
}

/** Carry on whatever the press started, following the pointer. */
function onGraphPointerMove(state: GraphState, event: PointerEvent): void {
  const drag = state.drag;
  if (drag === null || drag.pointerId !== event.pointerId) return;
  if (graphMovedFar(drag, event)) drag.moved = true;

  if (drag.kind === "pan") {
    panGraph(state, drag.scrollX + (event.clientX - drag.fromX),
             drag.scrollY + (event.clientY - drag.fromY));
    return;
  }

  if (drag.kind === "move") {
    const held = state.nodes.find((one): boolean => one.id === drag.nodeId);
    if (held !== undefined && held.piece !== null && held.piece.under === null) {
      markGraphSlotFor(state, event, held.id, held.piece?.hosts ?? "");
    }
  }

  if (drag.kind === "pick") {
    const marquee = graphMarquee(state);
    if (marquee === null) return;
    const at = pointInGraph(state, event);
    marquee.style.left = `${Math.min(drag.startX, at.x)}px`;
    marquee.style.top = `${Math.min(drag.startY, at.y)}px`;
    marquee.style.width = `${Math.abs(at.x - drag.startX)}px`;
    marquee.style.height = `${Math.abs(at.y - drag.startY)}px`;
    return;
  }

  const at = pointInGraph(state, event);

  if (drag.kind === "resize") {
    const node = state.nodes.find((entry): boolean => entry.id === drag.nodeId);
    const frame = state.boxes.get(drag.nodeId);
    if (node === undefined || frame === undefined || node.size === null) return;
    node.size.width = Math.max(200, Math.round(drag.grabX + (event.clientX - drag.fromX) / state.zoom));
    node.size.height = Math.max(140, Math.round(drag.grabY + (event.clientY - drag.fromY) / state.zoom));
    frame.style.width = `${node.size.width}px`;
    frame.style.height = `${node.size.height}px`;
    return;
  }

  if (drag.kind === "move") {
    const node = state.nodes.find((entry): boolean => entry.id === drag.nodeId);
    const box = state.boxes.get(drag.nodeId);
    if (node === undefined || box === undefined) return;
    // No clamping: the canvas goes on in every direction, including back.
    node.x = Math.round(at.x - drag.grabX);
    node.y = Math.round(at.y - drag.grabY);
    box.style.left = `${node.x}px`;
    box.style.top = `${node.y}px`;

    // A group takes what it surrounds with it, by the same amount.
    const across = node.x - drag.startX;
    const down = node.y - drag.startY;
    for (const held of drag.carried) {
      held.node.x = held.x + across;
      held.node.y = held.y + down;
      const moved = state.boxes.get(held.node.id);
      if (moved !== undefined) {
        moved.style.left = `${held.node.x}px`;
        moved.style.top = `${held.node.y}px`;
      }
    }

    // Anything slotted under what moved travels with it. A piece has no
    // position of its own worth keeping — it is drawn from its host's — so
    // this works them all out again rather than shifting each by the delta,
    // and a chain three deep follows as readily as one piece.
    placeGraphPieces(state);

    // Whichever node is open, wherever it has just been moved to — by being
    // dragged itself, or by the group or selection that carried it.
    keepGraphPopoverWithItsNode(state);
    drawGraphWires(state);
    return;
  }

  const from = graphPortPoint(state, drag.nodeId, "out");
  if (from !== null && state.ghost !== null) {
    state.ghost.setAttribute("d", graphCurve(from.x, from.y, at.x, at.y));
  }
}

/** The box under the pointer, if any. */
function graphDropTarget(event: PointerEvent): number | null {
  const under = document.elementFromPoint(event.clientX, event.clientY);
  return graphNodeIdFrom(under);
}

/** Finish what the press started: save a move, draw a wire, or pick. */
function onGraphPointerUp(state: GraphState, event: PointerEvent): void {
  const drag = state.drag;
  if (drag === null || drag.pointerId !== event.pointerId) return;
  state.drag = null;
  if (state.parts.canvas.hasPointerCapture(event.pointerId)) {
    state.parts.canvas.releasePointerCapture(event.pointerId);
  }

  if (drag.kind === "pan") {
    state.parts.canvas.classList.remove("is-panning");
    // A press on empty canvas that went nowhere is a click, and a click on
    // nothing is how a selection is put down.
    if (!drag.moved) clearGraphPick(state);
    return;
  }

  if (drag.kind === "pick") {
    const at = pointInGraph(state, event);
    graphMarquee(state)?.remove();
    pickGraphInside(state, drag.startX, drag.startY, at.x, at.y);
    return;
  }

  if (drag.kind === "resize") {
    // grabX and grabY held the size it started at.
    const wasSize = { width: drag.grabX, height: drag.grabY };
    const nodeId = drag.nodeId;
    rememberGraphUndo(state, "the resize", async (): Promise<void> => {
      const node = state.nodes.find((entry): boolean => entry.id === nodeId);
      if (node === undefined || node.size === null) return;
      node.size.width = wasSize.width;
      node.size.height = wasSize.height;
      renderGraph(state);
      await saveGraphSize(state, nodeId);
    });
    void saveGraphSize(state, nodeId);
    return;
  }

  if (drag.kind === "move") {
    state.boxes.get(drag.nodeId)?.classList.remove("is-held");
    hideGraphSlot(state);
    // A loose piece dragged onto a slot goes into it. The other way a piece
    // gets slotted in: one already lying on the canvas could otherwise only
    // be deleted and dragged out of the palette again.
    const loose = state.nodes.find((one): boolean => one.id === drag.nodeId);
    if (drag.moved && loose !== undefined && loose.piece !== null && loose.piece.under === null) {
      const slot = graphSlotFor(state, event, true, loose.piece?.hosts ?? "");
      if (slot !== null && slot.under !== loose.id) {
        void applyGraph(
          state,
          `/graph/nodes/${loose.id}/attach`,
          new URLSearchParams({ under: String(slot.under) }),
        );
        return;
      }
    }
    if (!drag.moved) {
      // The box that was pressed, not the one that was dragged: pressing a
      // augmentation opens that augmentation, even though dragging it moves
      // assembly it is part of.
      pickGraphNode(state, drag.pressed);
      return;
    }
    const nodeId = drag.nodeId;
    const wasAt = [
      { id: nodeId, x: drag.startX, y: drag.startY },
      ...drag.carried.map((held): { id: number; x: number; y: number } => ({
        id: held.node.id,
        x: held.x,
        y: held.y,
      })),
    ];
    rememberGraphUndo(state, "the move", async (): Promise<void> => {
      for (const was of wasAt) {
        const node = state.nodes.find((entry): boolean => entry.id === was.id);
        if (node === undefined) continue;
        node.x = was.x;
        node.y = was.y;
      }
      renderGraph(state);
      await Promise.all(wasAt.map((was): Promise<void> => saveGraphMove(state, was.id)));
    });

    // A group moves its contents server-side, in one call. Anything else that
    // travelled moved on its own, and has to say so on its own.
    void saveGraphMove(state, nodeId);
    if (!graphIsGroup(state, nodeId)) {
      for (const held of drag.carried) void saveGraphMove(state, held.node.id);
    }
    return;
  }

  if (state.ghost !== null) {
    state.ghost.remove();
    state.ghost = null;
  }
  const target = graphDropTarget(event);
  if (target === null || target === drag.nodeId) return;
  void wireGraphNodes(state, drag.nodeId, target);
}

/** Wire one node to another, and remember how to take it out again. */
async function wireGraphNodes(state: GraphState, from: number, to: number): Promise<void> {
  const before = state.wires;
  const made = await applyGraph(
    state,
    "/graph/connect",
    new URLSearchParams({ source: String(from), target: String(to) }),
  );
  if (!made) return;

  const fresh = graphWireAdded(before, state.wires);
  if (fresh === null) return;
  rememberGraphUndo(state, "the wire you drew", async (): Promise<void> => {
    await applyGraph(state, "/graph/disconnect", new URLSearchParams({ wire: fresh }));
  });
}

/** Pick everything the dragged box covered. */
function pickGraphInside(
  state: GraphState,
  fromX: number,
  fromY: number,
  toX: number,
  toY: number,
): void {
  const left = Math.min(fromX, toX);
  const right = Math.max(fromX, toX);
  const top = Math.min(fromY, toY);
  const bottom = Math.max(fromY, toY);

  // Every box whose corner falls inside the marquee; one picked opens its panel.
  state.picked = new Set<number>(
    state.nodes
      .filter(
        (node): boolean =>
          node.x >= left && node.x <= right && node.y >= top && node.y <= bottom,
      )
      .map((node): number => node.id),
  );
  state.selectedNode = state.picked.size === 1 ? [...state.picked][0] ?? null : null;
  renderGraph(state);
}

/** Save a box's new position; a group moves with everything in it. */
async function saveGraphMove(state: GraphState, nodeId: number): Promise<void> {
  const node = state.nodes.find((entry): boolean => entry.id === nodeId);
  if (node === undefined) return;
  try {
    await askGraph(
      `/graph/nodes/${nodeId}/move`,
      new URLSearchParams({
        x: String(node.x),
        y: String(node.y),
        // One call for a group and everything in it, so a group of ten
        // cannot half-move if the second call never lands.
        carries: node.kind === "group" ? "1" : "",
      }),
    );
  } catch {
    showGraphError(state, "That node moved on screen, but the position was not saved.");
  }
}

/** Whether this node is a group. */
function graphIsGroup(state: GraphState, nodeId: number): boolean {
  return state.nodes.find((entry): boolean => entry.id === nodeId)?.kind === "group";
}

/** Save a group's new size. */
async function saveGraphSize(state: GraphState, nodeId: number): Promise<void> {
  const node = state.nodes.find((entry): boolean => entry.id === nodeId);
  if (node === undefined || node.size === null) return;
  try {
    await askGraph(
      `/graph/nodes/${nodeId}/resize`,
      new URLSearchParams({
        width: String(node.size.width),
        height: String(node.size.height),
      }),
    );
  } catch {
    showGraphError(state, "That group changed size on screen, but it was not saved.");
  }
}
