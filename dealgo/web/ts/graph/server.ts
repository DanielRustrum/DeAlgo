// Talking to the server: every change is a POST answered with the whole graph.
//
// Part of the Configuration canvas; see main.ts.

/** GET (no body) or POST a form to the server, and read the JSON it answers with. */
async function askGraph(url: string, body: URLSearchParams | null): Promise<unknown> {
  const init: RequestInit =
    body === null
      ? { headers: { Accept: "application/json" } }
      : { method: "POST", body, headers: { Accept: "application/json" } };
  const response = await fetch(url, init);
  return (await response.json()) as unknown;
}

/** Send a change, take the graph that comes back, redraw. */
async function applyGraph(state: GraphState, url: string, body: URLSearchParams | null): Promise<boolean> {
  // One change at a time: a second click while one is in flight is ignored.
  if (state.busy) return false;
  state.busy = true;
  try {
    const answer = await askGraph(url, body);
    const view = asGraph(answer);
    if (view === null) {
      showGraphError(state, asGraphError(answer) ?? "That change did not go through.");
      return false;
    }
    // The server's answer is the new truth; redraw from it.
    state.nodes = view.nodes;
    state.wires = view.wires;
    state.sources = view.sources;
    forgetMissingGraph(state);
    showGraphError(state, null);
    renderGraph(state);
    return true;
  } catch {
    showGraphError(state, "No connection, so nothing was changed.");
    return false;
  } finally {
    state.busy = false;
  }
}

/** A box or wire can vanish under a selection — the server had the last word. */
function forgetMissingGraph(state: GraphState): void {
  if (state.selectedNode !== null && !state.nodes.some((n): boolean => n.id === state.selectedNode)) {
    state.selectedNode = null;
  }
  if (state.selectedWire !== null && !state.wires.some((w): boolean => w.id === state.selectedWire)) {
    state.selectedWire = null;
  }
}
