// Watching a run go through.
//
// A sync takes a minute and used to look like nothing happening followed by
// everything changing. These ask the server where it has got to and light the
// boxes as the work reaches them.
//
// Part of the Configuration canvas; see main.ts.

/** What a run did at one box. */
interface GraphMark {
  state: string;
  count: number;
  /** Items this box turned away. Filters only. */
  stopped: number;
  /** The flow got here and went no further. */
  ends: boolean;
  /** Why it could not look at all — rate limited, refused, gone. A third
   *  thing from "nothing was there" and from "this is where it stopped". */
  trouble: string | null;
}

/** Where a run has got to: whether it is going, its stage, and each box's mark. */
interface GraphRunState {
  running: boolean;
  stage: string | null;
  nodes: Map<number, GraphMark>;
}

/** The run state from the server, checked. */
function asGraphRun(value: unknown): GraphRunState | null {
  const raw = asGraphRecord(value);
  if (raw === null) return null;

  const marks = new Map<number, GraphMark>();
  const nodes = asGraphRecord(raw["nodes"]);
  for (const key of Object.keys(nodes ?? {})) {
    const mark = asGraphRecord((nodes ?? {})[key]);
    if (mark === null) continue;
    marks.set(Number(key), {
      state: typeof mark["state"] === "string" ? mark["state"] : "done",
      count: typeof mark["count"] === "number" ? mark["count"] : 0,
      stopped: typeof mark["stopped"] === "number" ? mark["stopped"] : 0,
      ends: mark["ends"] === true,
      trouble: typeof mark["trouble"] === "string" ? mark["trouble"] : null,
    });
  }
  return {
    running: raw["running"] === true,
    stage: typeof raw["stage"] === "string" ? raw["stage"] : null,
    nodes: marks,
  };
}

/** Ask where the run is, until it is over. */
async function followGraphRun(state: GraphState): Promise<void> {
  if (state.watching) return;
  state.watching = true;
  try {
    for (;;) {
      const run = asGraphRun(await askGraph("/api/graph/run", null));
      if (run === null) return;

      state.run = run.nodes;
      paintGraphRun(state);
      showGraphVerdict(state, graphStageWords(run));
      if (!run.running) break;
      await graphPause(900);
    }
  } catch {
    // A run nobody can watch is still a run. Leave what is on screen.
  } finally {
    state.watching = false;
    // The boxes have changed underneath: counts, last-polled times, feeds.
    // What the run found stays on them, which is the point of having watched.
    await applyGraph(state, "/api/graph", null);
  }
}

/** A promise that resolves after `milliseconds`. */
function graphPause(milliseconds: number): Promise<void> {
  return new Promise((wake): void => {
    window.setTimeout(wake, milliseconds);
  });
}

/** What the run is doing, in words, above the canvas. */
function graphStageWords(run: GraphRunState): string | null {
  if (!run.running) return run.stage === null ? null : "Run finished.";
  if (run.stage === "polling") return "Checking channels for new items…";
  if (run.stage === "sorting") return "Looking at what came back…";
  if (run.stage === "filling") return "Filling the feeds…";
  return "Running…";
}

/** Mark the boxes the run has reached, and the wires between them. */
function paintGraphRun(state: GraphState): void {
  for (const [id, box] of state.boxes) {
    const mark = state.run.get(id);
    box.classList.toggle("is-busy", mark?.state === "busy");
    box.classList.toggle("is-visited", mark?.state === "done");

    graphTally(box, mark);
  }
  paintGraphRunWires(state);
}

/** What the run found here, said on the box.
 *
 *  A channel that was polled and brought back nothing says so. Leaving it
 *  blank would look the same as a channel the run never reached, and "there
 *  was nothing new" is an answer worth having — it is the usual one. */
function graphTally(box: HTMLElement, mark: GraphMark | undefined): void {
  const showing = box.querySelector<HTMLElement>(".graph-node-tally");
  if (mark === undefined || mark.state !== "done") {
    showing?.remove();
    box.classList.remove("is-dead-end");
    return;
  }

  const tally = showing ?? graphElement("span", "graph-node-tally");
  tally.textContent = graphTallyWords(mark);
  // Four readings, and they are not the same thing: something came through,
  // nothing was there to come through, something was there and this box is
  // where it stopped, and it went and could not get in.
  tally.classList.toggle("is-empty", mark.count === 0 && !mark.ends);
  const refused = typeof mark.trouble === "string" && mark.trouble !== "";
  tally.classList.toggle("is-end", mark.ends && !refused);
  tally.classList.toggle("is-trouble", refused);
  tally.title = refused ? (mark.trouble ?? "") : "";
  box.classList.toggle("is-dead-end", mark.ends);
  if (showing === null) box.appendChild(tally);
}

/** What a box's mark says: what it brought, held, or why it could not. */
function graphTallyWords(mark: GraphMark): string {
  // It went and could not get in. Said in its own words, because "stops here"
  // sent people looking for a wiring fault when the feed was simply refusing
  // them — which is the one reading of a run they cannot check by looking.
  //
  // Asked for a non-empty string rather than "not null": a mark from anywhere
  // that leaves the field out gives undefined, which is also not null.
  if (typeof mark.trouble === "string" && mark.trouble !== "") return mark.trouble;
  if (mark.count > 0) return `+${mark.count}`;
  // Held something and passed none of it on: this is where the flow stopped.
  if (mark.stopped > 0) return `stops here · ${mark.stopped} held`;
  // Nothing left it and it had nothing to hold — a trigger whose channels are
  // all switched off. It did not look and find nothing; it never looked.
  if (mark.ends) return "stops here";
  return "nothing new";
}

/** A wire out of a box the run has reached is carrying something. */
function paintGraphRunWires(state: GraphState): void {
  const busy = new Set<number>();
  for (const [id, mark] of state.run) {
    if (mark.state === "busy") busy.add(id);
  }
  state.parts.wires.querySelectorAll<SVGPathElement>(".graph-wire").forEach((path): void => {
    path.classList.remove("is-carrying");
  });
  if (busy.size === 0) return;
  for (const wire of state.wires) {
    if (!busy.has(wire.from)) continue;
    state.parts.wires
      .querySelectorAll<SVGPathElement>(`[data-line="${wire.id}"]`)
      .forEach((path): void => path.classList.add("is-carrying"));
  }
}

/** The pieces of the page this canvas is made of, or null if one is missing. */
function graphPartsIn(canvas: HTMLElement): GraphParts | null {
  const panel = canvas.closest<HTMLElement>(".graph-panel");
  const scene = canvas.querySelector<HTMLElement>("[data-graph-scene]");
  const groups = canvas.querySelector<HTMLElement>("[data-graph-groups]");
  const layer = canvas.querySelector<HTMLElement>("[data-graph-nodes]");
  const wires = canvas.querySelector<SVGSVGElement>("[data-graph-wires]");
  if (!panel || scene === null || groups === null || layer === null || wires === null) {
    return null;
  }
  return {
    canvas,
    scene,
    groups,
    layer,
    wires,
    drawer: canvas.querySelector<HTMLElement>("[data-graph-drawer]"),
    error: panel.querySelector<HTMLElement>("[data-graph-error]"),
    verdict: panel.querySelector<HTMLElement>("[data-graph-verdict]"),
    empty: panel.querySelector<HTMLElement>("[data-graph-empty]"),
  };
}
