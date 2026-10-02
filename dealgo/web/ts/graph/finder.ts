// Finding a group on a large canvas.
//
// Part of the Configuration canvas; see main.ts.

/** The list of groups, and the way back to each of them.
 *
 *  The canvas goes on for ever in every direction, so a group dragged far
 *  enough out is a group nobody can find by panning. */
function renderGraphFinder(state: GraphState): void {
  const list = graphFinderPart(state, "[data-graph-finder-list]");
  if (list === null) return;

  list.textContent = "";
  const groups = state.nodes.filter((node): boolean => node.kind === "group");
  if (groups.length === 0) {
    list.appendChild(graphElement("li", "finder-empty", "No groups yet. Add one from +."));
    return;
  }

  for (const group of groups) {
    const row = graphElement("li", "finder-item");
    const go = graphElement("button", "finder-go", group.title);
    go.setAttribute("type", "button");
    go.dataset["goto"] = String(group.id);
    row.appendChild(go);
    list.appendChild(row);
  }
}

/** One part of the finder, by selector. */
function graphFinderPart(state: GraphState, selector: string): HTMLElement | null {
  return (
    state.parts.canvas
      .closest<HTMLElement>(".graph-panel")
      ?.querySelector<HTMLElement>(selector) ?? null
  );
}

/** Open or close the finder; opening it closes the palette. */
function toggleGraphFinder(state: GraphState, open: boolean): void {
  const drawer = graphFinderPart(state, "[data-graph-finder]");
  if (drawer === null) return;
  if (open) {
    renderGraphFinder(state);
    toggleGraphPalette(state, false);
  }
  drawer.hidden = !open;
  graphFinderPart(state, "[data-graph-find]")?.setAttribute(
    "aria-expanded",
    open ? "true" : "false",
  );
}

/** Pan so that node sits in the middle of the view, and pick it out. */
function centreGraphOn(state: GraphState, node: GraphNodeView): void {
  const frame = state.parts.canvas.getBoundingClientRect();
  const middleX = node.x + (node.size?.width ?? 212) / 2;
  const middleY = node.y + (node.size?.height ?? 60) / 2;

  panGraph(
    state,
    frame.width / 2 - middleX * state.zoom,
    frame.height / 2 - middleY * state.zoom,
  );
  // Brought into view and marked, not opened: the answer to "where is it" is
  // seeing it, and a panel over it would be in the way of the answer.
  state.picked = new Set<number>([node.id]);
  state.selectedNode = null;
  renderGraph(state);
}

/** Wire up the finder's toggle and its list of groups. */
function listenForGraphFinder(state: GraphState, panel: HTMLElement): void {
  panel.querySelector<HTMLElement>("[data-graph-find]")?.addEventListener("click", (): void => {
    const drawer = graphFinderPart(state, "[data-graph-finder]");
    toggleGraphFinder(state, drawer?.hidden === true);
  });
  panel
    .querySelector<HTMLElement>("[data-graph-find-close]")
    ?.addEventListener("click", (): void => toggleGraphFinder(state, false));

  panel.querySelector<HTMLElement>("[data-graph-finder-list]")?.addEventListener(
    "click",
    (event: MouseEvent): void => {
      const target = event.target;
      if (!(target instanceof Element)) return;
      const wanted = target.closest<HTMLElement>("[data-goto]")?.dataset["goto"];
      if (wanted === undefined) return;
      const node = state.nodes.find((entry): boolean => entry.id === Number(wanted));
      if (node !== undefined) centreGraphOn(state, node);
    },
  );
}
