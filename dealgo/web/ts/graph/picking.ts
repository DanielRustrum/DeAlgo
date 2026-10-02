// Picking boxes and wires, and what follows from it: keys, clicks and removing.
//
// Part of the Configuration canvas; see main.ts.

function pickGraphNode(state: GraphState, nodeId: number | null): void {
  if (nodeId !== state.selectedNode) state.tab = "settings";
  state.selectedNode = nodeId;
  state.picked = nodeId === null ? new Set<number>() : new Set<number>([nodeId]);
  state.selectedWire = null;
  renderGraph(state);
}

/** Add or drop one node from the picked set, leaving the rest alone.
 *
 *  More than one picked means no panel: a panel is about a node, and there is
 *  no such thing as the settings of three of them. */
function alsoPickGraphNode(state: GraphState, nodeId: number): void {
  if (state.picked.has(nodeId)) state.picked.delete(nodeId);
  else state.picked.add(nodeId);

  const only = state.picked.size === 1 ? [...state.picked][0] ?? null : null;
  state.selectedNode = only;
  state.selectedWire = null;
  renderGraph(state);
}

function pickGraphWire(state: GraphState, wireId: string): void {
  state.selectedWire = wireId;
  state.selectedNode = null;
  renderGraph(state);
}

function clearGraphPick(state: GraphState): void {
  if (state.selectedNode === null && state.selectedWire === null && state.picked.size === 0) {
    return;
  }
  state.selectedNode = null;
  state.picked = new Set<number>();
  state.selectedWire = null;
  renderGraph(state);
}

function onGraphClick(state: GraphState, event: MouseEvent): void {
  const target = event.target;
  if (!(target instanceof Element)) return;

  const cut = target.closest<HTMLElement>("[data-cut]");
  const cutId = cut?.dataset["cut"];
  if (cutId !== undefined) {
    event.preventDefault();
    const wire = state.wires.find((entry): boolean => entry.id === cutId);
    state.selectedWire = null;
    if (wire !== undefined) {
      const ends = { from: String(wire.from), to: String(wire.to) };
      rememberGraphUndo(state, "the wire you took out", async (): Promise<void> => {
        await applyGraph(state, "/graph/connect", new URLSearchParams({
          source: ends.from, target: ends.to,
        }));
      });
    }
    void applyGraph(state, "/graph/disconnect", new URLSearchParams({ wire: cutId }));
    return;
  }

  if (target.closest<HTMLElement>("[data-remove-picked]") !== null) {
    event.preventDefault();
    void removeGraphPicked(state);
    return;
  }

  const fire = target.closest<HTMLElement>("[data-fire]");
  const fireId = fire?.dataset["fire"];
  if (fireId !== undefined) {
    event.preventDefault();
    void fireGraphPulse(state, fireId, null);
    return;
  }

  const back = target.closest<HTMLElement>("[data-backfill]");
  const backId = back?.dataset["backfill"];
  if (backId !== undefined) {
    event.preventDefault();
    askHowFarBack(state, backId);
    return;
  }

  const test = target.closest<HTMLElement>("[data-test]");
  const testId = test?.dataset["test"];
  if (testId !== undefined) {
    event.preventDefault();
    void tryGraph(state, testId);
    return;
  }

  const filtered = target.closest<HTMLElement>("[data-filtered]");
  const filteredId = filtered?.dataset["filtered"];
  if (filteredId !== undefined) {
    event.preventDefault();
    void showGraphFiltered(state, filteredId);
    return;
  }

  const unslot = target.closest<HTMLElement>("[data-unslot]");
  const unslotId = unslot?.dataset["unslot"];
  if (unslotId !== undefined) {
    event.preventDefault();
    void applyGraph(
      state,
      `/graph/nodes/${unslotId}/attach`,
      new URLSearchParams({ under: "" }),
    );
    return;
  }

  const remove = target.closest<HTMLElement>("[data-remove]");
  const removeId = remove?.dataset["remove"];
  if (removeId !== undefined) {
    event.preventDefault();
    // A filter or a trigger stands for nothing else and just goes. A channel
    // or a feed takes its history with it, so that is said out loud first.
    const warning = remove?.dataset["what"] ?? "";
    void removeGraphNode(state, removeId, warning);
    return;
  }

  const tab = target.closest<HTMLElement>("[data-tab]");
  const wanted = tab?.dataset["tab"];
  if (wanted !== undefined) {
    event.preventDefault();
    const whose = Number(tab?.dataset["for"] ?? "");
    const box = state.nodes.find((entry): boolean => entry.id === whose);
    state.tab = wanted === "test" ? "test" : "settings";

    if (graphTabNeedsRun(box, state.trial, wanted)) {
      void tryGraph(state, String(whose));
      return;
    }
    renderGraph(state);
    return;
  }

  if (target.closest<HTMLElement>("[data-close]") !== null) {
    event.preventDefault();
    pickGraphNode(state, null);
  }
}

/** Set a trigger off by hand.
 *
 *  `reachBack` is how many of the latest posts to run through: null for an
 *  ordinary poll, which takes only what is new, and a count for a backfill.
 *  Zero means as far as the feeds go. The answer carries the graph and a line
 *  about what it did. */
async function fireGraphPulse(
  state: GraphState,
  nodeId: string,
  reachBack: number | null,
): Promise<void> {
  if (state.busy) return;
  state.busy = true;
  try {
    const asking = new URLSearchParams();
    const where = reachBack === null ? "fire" : "backfill";
    if (reachBack !== null && reachBack > 0) asking.set("count", String(reachBack));
    const answer = await askGraph(`/graph/nodes/${nodeId}/${where}`, asking);
    const view = asGraph(answer);
    if (view === null) {
      showGraphError(state, asGraphError(answer) ?? "That trigger did not fire.");
      return;
    }
    state.nodes = view.nodes;
    state.wires = view.wires;
    forgetMissingGraph(state);
    showGraphError(state, null);
    showGraphVerdict(state, graphSaid(answer));
    renderGraph(state);
    void followGraphRun(state);
  } catch {
    showGraphError(state, "No connection, so nothing was polled.");
  } finally {
    state.busy = false;
  }
}

/** What the server said it did, if it said anything. */
function graphSaid(value: unknown): string | null {
  const raw = asGraphRecord(value);
  const said = raw === null ? null : raw["said"];
  return typeof said === "string" ? said : null;
}

/** Take one box away, once the question about it has been answered. */
async function removeGraphNode(
  state: GraphState,
  nodeId: string,
  warning: string,
): Promise<void> {
  if (warning !== "" && !(await askGraphSure(state, warning))) return;
  state.selectedNode = null;
  await applyGraph(state, `/graph/nodes/${nodeId}/delete`, new URLSearchParams());
}

function onGraphKeyDown(state: GraphState, event: KeyboardEvent): void {
  if (event.key === "Escape") {
    clearGraphPick(state);
    return;
  }
  if (event.key === "Delete" || event.key === "Backspace") {
    if (state.picked.size === 0 || !graphTakesTheKey(event.target)) return;
    event.preventDefault();
    void removeGraphPicked(state);
    return;
  }
  if (event.key !== "Enter" && event.key !== " ") return;
  const nodeId = graphNodeIdFrom(event.target);
  if (nodeId === null) return;
  event.preventDefault();
  pickGraphNode(state, nodeId);
}

async function onGraphSubmit(state: GraphState, event: SubmitEvent): Promise<void> {
  const form = event.target;
  if (!(form instanceof HTMLFormElement)) return;
  const nodeId = form.dataset["save"];
  if (nodeId === undefined) return;
  event.preventDefault();

  const was = form.dataset["was"];
  if (was !== undefined && was !== "") {
    rememberGraphUndo(state, "the change to that node", async (): Promise<void> => {
      await applyGraph(state, `/graph/nodes/${nodeId}`, new URLSearchParams(was));
    });
  }
  await applyGraph(state, `/graph/nodes/${nodeId}`, graphFormValues(form));
}

/** A form's fields as a body. FormData can hold files; this one never does. */
function graphFormValues(form: HTMLFormElement): URLSearchParams {
  const params = new URLSearchParams();
  new FormData(form).forEach((value: FormDataEntryValue, key: string): void => {
    if (typeof value === "string") params.append(key, value);
  });
  return params;
}
