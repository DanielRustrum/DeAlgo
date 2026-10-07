// Trying a flow without running it.
//
// Part of the Configuration canvas; see main.ts.

/** Ask what a run would do, mark the boxes with it, and list where it lands. */
async function tryGraph(state: GraphState, nodeId: string): Promise<void> {
  // Shown in the box that was asked, so open its test side first and say it
  // is working: the answer takes a moment and a blank panel reads as broken.
  state.selectedNode = Number(nodeId);
  state.tab = "test";
  state.trial = { node: Number(nodeId), boxes: new Map<number, GraphShare>(), asking: true };
  renderGraph(state);

  try {
    const answer = await askGraph(`/graph/nodes/${nodeId}/test`, null);
    const run = asGraphRun(answer);
    const raw = asGraphRecord(answer);
    if (run === null || raw === null) {
      state.trial = null;
      state.tab = "settings";
      showGraphError(state, asGraphError(answer) ?? "That could not be tried.");
      renderGraph(state);
      return;
    }
    showGraphError(state, null);
    state.trial = {
      node: Number(nodeId),
      boxes: asGraphShares(raw["items"]),
      asking: false,
    };
    // The same marks a real run leaves, so the drawing reads the same either
    // way: what differs is that nothing was written.
    state.run = run.nodes;
    renderGraph(state);
  } catch {
    state.trial = null;
    state.tab = "settings";
    showGraphError(state, "No connection, so nothing could be tried.");
    renderGraph(state);
  }
}

/** Every box the trial touched, and what each of them did. */
function asGraphShares(value: unknown): Map<number, GraphShare> {
  const shares = new Map<number, GraphShare>();
  const raw = asGraphRecord(value);
  if (raw === null) return shares;
  for (const key of Object.keys(raw)) {
    const share = asGraphRecord(raw[key]);
    if (share === null) continue;
    shares.set(Number(key), {
      through: asGraphJudged(share["through"]),
      held: asGraphHeld(share["held"]),
    });
  }
  return shares;
}

/** Held items, each naming the box that stopped it as part of its reason. */
function asGraphHeld(value: unknown): GraphJudged[] {
  if (!Array.isArray(value)) return [];
  const read: GraphJudged[] = [];
  for (const entry of value) {
    const raw = asGraphRecord(entry);
    if (raw === null || typeof raw["id"] !== "number") continue;
    const box = typeof raw["box"] === "string" ? raw["box"] : "";
    const why = typeof raw["reason"] === "string" ? raw["reason"] : "held back";
    read.push({
      id: raw["id"],
      title: typeof raw["title"] === "string" ? raw["title"] : "",
      reason: box === "" ? why : `${box}: ${why}`,
      // Nothing happens to something that was turned away.
      marks: [],
    });
  }
  return read;
}
