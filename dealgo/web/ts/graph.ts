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
// Top-level `function` declarations only: see the note in dialog.ts.

type GraphNodeKind = "trigger" | "source" | "filter" | "feed";
type GraphWireKind = "link" | "edge";

/** A filter's answer for one rule. Absent means "leave it to the channel". */
type GraphOverride = string | number | boolean;

interface GraphNodeView {
  id: number;
  kind: GraphNodeKind;
  title: string;
  x: number;
  y: number;
  /** Where the thing behind the box lives, for source and feed boxes. */
  detail: string | null;
  note: string;
  /** Source boxes only: what decides when this channel is polled. */
  polled: string | null;
  /** Trigger boxes only. */
  trigger: GraphTrigger | null;
  overrides: Record<string, GraphOverride>;
}

interface GraphTrigger {
  kind: "schedule" | "pulse";
  /** A pulse's gap, in minutes. */
  everyMinutes: number | null;
  /** A schedule's cron expression, read in UTC. */
  cron: string | null;
  /** When that expression next comes round, as the server worked it out. */
  next: string | null;
  lastFired: string | null;
}

interface GraphWireView {
  id: string;
  from: number;
  to: number;
  kind: GraphWireKind;
}

interface GraphView {
  nodes: GraphNodeView[];
  wires: GraphWireView[];
}

/** One hop of a followed item: which boxes it passed and whether it got in. */
interface GraphTraceStep {
  nodes: number[];
  wires: string[];
  accepted: boolean;
  reason: string | null;
}

interface GraphTraceView {
  title: string;
  steps: GraphTraceStep[];
}

/** A drag in progress — moving a box, or pulling a new wire out of one. */
interface GraphDrag {
  kind: "move" | "wire" | "pan";
  /** Which box is being dragged. Zero while panning: a pan holds no box. */
  nodeId: number;
  pointerId: number;
  /** Where in the box the pointer took hold, so it does not jump on grab. */
  grabX: number;
  grabY: number;
  /** Where on screen it started, and where the canvas was panned to then. */
  fromX: number;
  fromY: number;
  scrollX: number;
  scrollY: number;
  moved: boolean;
}

interface GraphParts {
  canvas: HTMLElement;
  /** Everything drawn, moved as one when the canvas is panned. */
  scene: HTMLElement;
  layer: HTMLElement;
  wires: SVGSVGElement;
  drawer: HTMLElement | null;
  error: HTMLElement | null;
  verdict: HTMLElement | null;
  empty: HTMLElement | null;
}

interface GraphState {
  parts: GraphParts;
  nodes: GraphNodeView[];
  wires: GraphWireView[];
  boxes: Map<number, HTMLElement>;
  selectedNode: number | null;
  selectedWire: string | null;
  drag: GraphDrag | null;
  ghost: SVGPathElement | null;
  /** "node:3" or "wire:edge:7" — true where a followed item got through. */
  marks: Map<string, boolean>;
  busy: boolean;
  /** Where the canvas has been panned to. There are no edges to stop at. */
  panX: number;
  panY: number;
  /** A box being dragged out of the palette, before it exists. */
  dropping: GraphDropping | null;
}

/** A palette row on its way to the canvas. */
interface GraphDropping {
  kind: string;
  pointerId: number;
  ghost: HTMLElement;
}

// -- reading what the server said -----------------------------------------

function asGraphRecord(value: unknown): Record<string, unknown> | null {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function asGraphNodeKind(value: unknown): GraphNodeKind | null {
  if (value === "trigger" || value === "source" || value === "filter" || value === "feed") {
    return value;
  }
  return null;
}

function asGraphOverrides(value: unknown): Record<string, GraphOverride> {
  const raw = asGraphRecord(value);
  const out: Record<string, GraphOverride> = {};
  if (raw === null) return out;
  for (const key of Object.keys(raw)) {
    const found = raw[key];
    if (typeof found === "string" || typeof found === "number" || typeof found === "boolean") {
      out[key] = found;
    }
  }
  return out;
}

function asGraphNode(value: unknown): GraphNodeView | null {
  const raw = asGraphRecord(value);
  if (raw === null) return null;
  const kind = asGraphNodeKind(raw["kind"]);
  const id = raw["id"];
  if (kind === null || typeof id !== "number") return null;
  const detail = raw["detail"];
  const polled = raw["polled"];
  return {
    id,
    kind,
    title: typeof raw["title"] === "string" ? raw["title"] : "",
    x: typeof raw["x"] === "number" ? raw["x"] : 0,
    y: typeof raw["y"] === "number" ? raw["y"] : 0,
    detail: typeof detail === "string" ? detail : null,
    note: typeof raw["note"] === "string" ? raw["note"] : "",
    polled: typeof polled === "string" ? polled : null,
    trigger: asGraphTrigger(raw["trigger"]),
    overrides: asGraphOverrides(raw["overrides"]),
  };
}

function asGraphTrigger(value: unknown): GraphTrigger | null {
  const raw = asGraphRecord(value);
  if (raw === null) return null;
  const every = raw["every_minutes"];
  const cron = raw["cron"];
  const next = raw["next"];
  const fired = raw["last_fired"];
  return {
    kind: raw["kind"] === "schedule" ? "schedule" : "pulse",
    everyMinutes: typeof every === "number" ? every : null,
    cron: typeof cron === "string" ? cron : null,
    next: typeof next === "string" ? next : null,
    lastFired: typeof fired === "string" ? fired : null,
  };
}

// -- clocks ----------------------------------------------------------------
//
// A schedule is stored in UTC, because every other instant in this app is and
// a stored local time would mean something else after a clock change. The
// person setting it means their own clock, so the conversion happens here,
// where the browser knows the offset.

/** Minutes past midnight UTC as "HH:MM" on the viewer's own clock. */
function graphLocalTime(atMinute: number | null): string {
  const minute = atMinute ?? 9 * 60;
  const when = new Date();
  when.setUTCHours(Math.floor(minute / 60), minute % 60, 0, 0);
  return `${String(when.getHours()).padStart(2, "0")}:${String(when.getMinutes()).padStart(2, "0")}`;
}

/** "HH:MM" on the viewer's clock back to minutes past midnight UTC. */
function graphUtcMinute(local: string): number {
  const [hours, minutes] = local.split(":");
  const when = new Date();
  when.setHours(Number(hours ?? 0), Number(minutes ?? 0), 0, 0);
  return (when.getUTCHours() * 60 + when.getUTCMinutes()) % (24 * 60);
}

function asGraphWire(value: unknown): GraphWireView | null {
  const raw = asGraphRecord(value);
  if (raw === null) return null;
  const id = raw["id"];
  const from = raw["from"];
  const to = raw["to"];
  if (typeof id !== "string" || typeof from !== "number" || typeof to !== "number") return null;
  return { id, from, to, kind: raw["kind"] === "link" ? "link" : "edge" };
}

/** The graph, or null if this is not one — an error body, say. */
function asGraph(value: unknown): GraphView | null {
  const raw = asGraphRecord(value);
  if (raw === null) return null;
  const nodes = raw["nodes"];
  const wires = raw["wires"];
  if (!Array.isArray(nodes) || !Array.isArray(wires)) return null;

  const readNodes: GraphNodeView[] = [];
  for (const entry of nodes) {
    const node = asGraphNode(entry);
    if (node !== null) readNodes.push(node);
  }
  const readWires: GraphWireView[] = [];
  for (const entry of wires) {
    const wire = asGraphWire(entry);
    if (wire !== null) readWires.push(wire);
  }
  return { nodes: readNodes, wires: readWires };
}

function asGraphError(value: unknown): string | null {
  const raw = asGraphRecord(value);
  const message = raw === null ? null : raw["error"];
  return typeof message === "string" ? message : null;
}

function asGraphTrace(value: unknown): GraphTraceView | null {
  const raw = asGraphRecord(value);
  if (raw === null) return null;
  const steps = raw["steps"];
  if (!Array.isArray(steps)) return null;

  const item = asGraphRecord(raw["item"]);
  const title = item === null || typeof item["title"] !== "string" ? "That item" : item["title"];

  const read: GraphTraceStep[] = [];
  for (const entry of steps) {
    const step = asGraphRecord(entry);
    if (step === null) continue;
    const nodes = step["nodes"];
    const wires = step["wires"];
    const reason = step["reason"];
    read.push({
      nodes: Array.isArray(nodes) ? nodes.filter((id): id is number => typeof id === "number") : [],
      wires: Array.isArray(wires) ? wires.filter((id): id is string => typeof id === "string") : [],
      accepted: step["accepted"] === true,
      reason: typeof reason === "string" ? reason : null,
    });
  }
  return { title, steps: read };
}

// -- talking to the server -------------------------------------------------

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
  if (state.busy) return false;
  state.busy = true;
  try {
    const answer = await askGraph(url, body);
    const view = asGraph(answer);
    if (view === null) {
      showGraphError(state, asGraphError(answer) ?? "That change did not go through.");
      return false;
    }
    state.nodes = view.nodes;
    state.wires = view.wires;
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

// -- drawing ---------------------------------------------------------------

function graphElement(tag: string, className: string, text?: string): HTMLElement {
  const made = document.createElement(tag);
  made.className = className;
  if (text !== undefined) made.textContent = text;
  return made;
}

function graphKindLabel(kind: GraphNodeKind): string {
  if (kind === "source") return "Channel";
  if (kind === "feed") return "Feed";
  return kind === "trigger" ? "Trigger" : "Filter";
}

function graphPort(where: "in" | "out"): HTMLElement {
  const dot = graphElement("span", `graph-port port-${where}`);
  dot.dataset["port"] = where;
  dot.title = where === "out" ? "GraphDrag from here to wire this up" : "Drop a wire here";
  return dot;
}

function drawGraphNode(state: GraphState, node: GraphNodeView): HTMLElement {
  const box = graphElement("div", `graph-node kind-${node.kind}`);
  box.dataset["node"] = String(node.id);
  box.style.left = `${node.x}px`;
  box.style.top = `${node.y}px`;
  box.tabIndex = 0;
  box.setAttribute("role", "button");
  box.setAttribute("aria-label", `${graphKindLabel(node.kind)}: ${node.title}`);
  if (node.id === state.selectedNode) box.classList.add("is-picked");

  const mark = state.marks.get(`node:${node.id}`);
  if (mark !== undefined) box.classList.add(mark ? "is-through" : "is-stopped");

  if (node.kind !== "trigger") box.appendChild(graphPort("in"));
  box.appendChild(graphElement("span", "graph-node-kind", graphTriggerLabel(node)));
  box.appendChild(graphElement("strong", "graph-node-title", node.title));
  box.appendChild(graphElement("span", "graph-node-note", node.note));
  if (node.trigger !== null) box.appendChild(graphFireButton(node));
  if (node.kind !== "feed") box.appendChild(graphPort("out"));
  return box;
}

/** A trigger says which of the two it is, since they behave nothing alike. */
function graphTriggerLabel(node: GraphNodeView): string {
  if (node.trigger === null) return graphKindLabel(node.kind);
  return node.trigger.kind === "pulse" ? "Pulse" : "Schedule";
}

function graphFireButton(node: GraphNodeView): HTMLElement {
  const button = graphElement("button", "btn btn-quiet graph-fire", "Run now");
  button.setAttribute("type", "button");
  button.dataset["fire"] = String(node.id);
  return button;
}

function drawGraphNodes(state: GraphState): void {
  state.parts.layer.textContent = "";
  state.boxes.clear();
  for (const node of state.nodes) {
    const box = drawGraphNode(state, node);
    state.boxes.set(node.id, box);
    state.parts.layer.appendChild(box);
  }
}

/** Where a wire leaves a box, and where it arrives — measured, not guessed. */
function graphPortPoint(state: GraphState, nodeId: number, where: "in" | "out"): { x: number; y: number } | null {
  const box = state.boxes.get(nodeId);
  const node = state.nodes.find((entry): boolean => entry.id === nodeId);
  if (box === undefined || node === undefined) return null;
  return {
    x: where === "out" ? node.x + box.offsetWidth : node.x,
    y: node.y + box.offsetHeight / 2,
  };
}

function graphCurve(x1: number, y1: number, x2: number, y2: number): string {
  const reach = Math.max(40, Math.abs(x2 - x1) * 0.5);
  return `M ${x1} ${y1} C ${x1 + reach} ${y1}, ${x2 - reach} ${y2}, ${x2} ${y2}`;
}

function graphSvgPath(className: string, d: string): SVGPathElement {
  const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
  path.setAttribute("class", className);
  path.setAttribute("d", d);
  return path;
}

function drawGraphWires(state: GraphState): void {
  state.parts.wires.textContent = "";
  // The ✕ belongs to a wire but lives among the boxes, so it is cleared here
  // rather than with them — a drag redraws the wires many times over.
  state.parts.layer.querySelectorAll(".graph-cut").forEach((button): void => button.remove());
  for (const wire of state.wires) {
    const from = graphPortPoint(state, wire.from, "out");
    const to = graphPortPoint(state, wire.to, "in");
    if (from === null || to === null) continue;

    const d = graphCurve(from.x, from.y, to.x, to.y);
    let classes = `graph-wire wire-${wire.kind}`;
    if (wire.id === state.selectedWire) classes += " is-picked";
    const mark = state.marks.get(`wire:${wire.id}`);
    if (mark !== undefined) classes += mark ? " is-through" : " is-stopped";

    // A two-pixel line is impossible to click. The fat one is invisible and
    // takes the pointer; the thin one is what is actually seen.
    const hit = graphSvgPath("graph-wire-hit", d);
    hit.setAttribute("data-wire", wire.id);
    state.parts.wires.appendChild(hit);
    state.parts.wires.appendChild(graphSvgPath(classes, d));

    if (wire.id === state.selectedWire) {
      state.parts.layer.appendChild(graphCutButton(wire.id, (from.x + to.x) / 2, (from.y + to.y) / 2));
    }
  }
}

/** The ✕ on a picked wire. Two clicks to remove a wire, never one by accident. */
function graphCutButton(wireId: string, x: number, y: number): HTMLElement {
  const button = graphElement("button", "graph-cut", "✕");
  button.setAttribute("type", "button");
  button.setAttribute("aria-label", "Take out this wire");
  button.dataset["cut"] = wireId;
  button.style.left = `${x}px`;
  button.style.top = `${y}px`;
  return button;
}

/** Grow the drawing area to hold the boxes, so the canvas can be scrolled. */
/** Move the whole drawing under the window. The canvas has no edges. */
function panGraph(state: GraphState, x: number, y: number): void {
  state.panX = x;
  state.panY = y;
  state.parts.scene.style.transform = `translate(${Math.round(x)}px, ${Math.round(y)}px)`;
  // The grid behind it moves too, or the drawing looks like it is sliding
  // over a pattern that is nailed down.
  state.parts.canvas.style.backgroundPosition = `${Math.round(x)}px ${Math.round(y)}px`;
}

function renderGraph(state: GraphState): void {
  drawGraphNodes(state);
  drawGraphWires(state);
  renderGraphPopover(state);
  // The canvas itself is never hidden: the palette lives inside it, so an
  // account with nothing on it would have nothing to add anything with.
  if (state.parts.empty !== null) state.parts.empty.hidden = state.nodes.length > 0;
}

function showGraphError(state: GraphState, message: string | null): void {
  const box = state.parts.error;
  if (box === null) return;
  box.textContent = message ?? "";
  box.hidden = message === null;
}

function showGraphVerdict(state: GraphState, message: string | null): void {
  const box = state.parts.verdict;
  if (box === null) return;
  box.textContent = message ?? "";
  box.hidden = message === null;
}

// -- the panel beside it ---------------------------------------------------

function graphLabelled(name: string, control: HTMLElement): HTMLElement {
  const row = graphElement("label", "graph-field");
  row.appendChild(graphElement("span", "graph-field-name", name));
  row.appendChild(control);
  return row;
}

function graphTextField(name: string, value: GraphOverride | undefined, placeholder: string): HTMLElement {
  const input = document.createElement("input");
  input.type = "text";
  input.name = name;
  input.value = value === undefined ? "" : String(value);
  input.placeholder = placeholder;
  return input;
}

/** Three-valued, because "leave it to the channel" is a real answer. */
function graphSwitchField(name: string, value: GraphOverride | undefined): HTMLElement {
  const select = document.createElement("select");
  select.name = name;
  for (const [text, option] of [
    ["as the channel says", ""],
    ["let through", "0"],
    ["block", "1"],
  ] as const) {
    const choice = document.createElement("option");
    choice.value = option;
    choice.textContent = text;
    choice.selected = value === undefined ? option === "" : String(value === true ? "1" : "0") === option;
    select.appendChild(choice);
  }
  return select;
}

function graphFilterForm(state: GraphState, node: GraphNodeView): HTMLElement {
  const form = document.createElement("form");
  form.className = "graph-form";
  form.dataset["save"] = String(node.id);

  const name = document.createElement("input");
  name.type = "text";
  name.name = "label";
  name.value = node.title;
  form.appendChild(graphLabelled("Name", name));

  for (const [text, key] of [
    ["Videos", "skip_videos"],
    ["Shorts", "skip_shorts"],
    ["Live", "skip_live"],
    ["Posts", "skip_posts"],
  ] as const) {
    form.appendChild(graphLabelled(text, graphSwitchField(key, node.overrides[key])));
  }

  form.appendChild(
    graphLabelled("Title must contain", graphTextField("title_include", node.overrides["title_include"], "any")),
  );
  form.appendChild(
    graphLabelled("Title must not contain", graphTextField("title_exclude", node.overrides["title_exclude"], "nothing")),
  );
  form.appendChild(
    graphLabelled("Shortest, in seconds", graphTextField("min_duration_sec", node.overrides["min_duration_sec"], "no limit")),
  );
  form.appendChild(
    graphLabelled("Longest, in seconds", graphTextField("max_duration_sec", node.overrides["max_duration_sec"], "no limit")),
  );
  form.appendChild(
    graphLabelled("Most per sync", graphTextField("max_per_run", node.overrides["max_per_run"], "no limit")),
  );

  const buttons = graphElement("div", "graph-form-buttons");
  const save = graphElement("button", "btn btn-primary", "Save");
  save.setAttribute("type", "submit");
  buttons.appendChild(save);

  const remove = graphElement("button", "btn btn-danger", "Remove");
  remove.setAttribute("type", "button");
  remove.dataset["remove"] = String(node.id);
  buttons.appendChild(remove);
  form.appendChild(buttons);

  if (state.busy) form.setAttribute("aria-busy", "true");
  return form;
}

/** The open box's detail, drawn on the canvas beside the box it belongs to.
 *
 *  In the scene rather than beside it, so it pans with the box and stays
 *  plainly attached to it — a panel off to one side makes the reader hold
 *  "which box was this about?" in their head. */
function renderGraphPopover(state: GraphState): void {
  state.parts.layer.querySelectorAll(".graph-pop").forEach((old): void => old.remove());

  const node = state.nodes.find((entry): boolean => entry.id === state.selectedNode);
  if (node === undefined) return;
  const box = state.boxes.get(node.id);
  if (box === undefined) return;

  const pop = graphElement("div", "graph-pop");
  pop.style.left = `${node.x + box.offsetWidth + 18}px`;
  pop.style.top = `${node.y}px`;

  const head = graphElement("div", "graph-pop-head");
  head.appendChild(graphElement("span", "graph-pop-kind", graphTriggerLabel(node)));
  const close = graphElement("button", "graph-pop-close", "✕");
  close.setAttribute("type", "button");
  close.setAttribute("aria-label", "Close");
  close.dataset["close"] = "1";
  head.appendChild(close);
  pop.appendChild(head);

  pop.appendChild(graphNodeForm(state, node));
  state.parts.layer.appendChild(pop);
}

/** One form per box. Every kind has a name; what else it has depends. */
function graphNodeForm(state: GraphState, node: GraphNodeView): HTMLElement {
  const form = document.createElement("form");
  form.className = "graph-form";
  form.dataset["save"] = String(node.id);

  const name = document.createElement("input");
  name.type = "text";
  name.name = "label";
  name.value = node.title;
  form.appendChild(graphLabelled("Name", name));

  if (node.kind === "source") graphChannelFields(form, node);
  else if (node.kind === "feed") graphFeedFields(form, node);
  else if (node.trigger !== null) graphTriggerFields(form, node);
  else graphFilterFields(form, node);

  const buttons = graphElement("div", "graph-form-buttons");
  const save = graphElement("button", "btn btn-primary", "Save");
  save.setAttribute("type", "submit");
  buttons.appendChild(save);

  if (node.trigger !== null) {
    const fire = graphElement("button", "btn btn-quiet", "Run now");
    fire.setAttribute("type", "button");
    fire.dataset["fire"] = String(node.id);
    buttons.appendChild(fire);
  }
  if (node.detail !== null) {
    const open = document.createElement("a");
    open.className = "btn btn-quiet";
    open.href = node.detail;
    open.textContent = "Open";
    buttons.appendChild(open);
  }

  const remove = graphElement("button", "btn btn-danger", "Remove");
  remove.setAttribute("type", "button");
  remove.dataset["remove"] = String(node.id);
  remove.dataset["what"] = graphRemovalWarning(node);
  buttons.appendChild(remove);
  form.appendChild(buttons);

  if (state.busy) form.setAttribute("aria-busy", "true");
  return form;
}

/** What taking this box away costs, said before it is taken away. */
function graphRemovalWarning(node: GraphNodeView): string {
  if (node.kind === "source") {
    return `Stop watching ${node.title}? Its history goes too; anything already in a feed stays put.`;
  }
  if (node.kind === "feed") {
    return `Remove the feed ${node.title}? What it collected inside De-Algo goes with it.`;
  }
  return "";
}

function graphChannelFields(form: HTMLElement, node: GraphNodeView): void {
  if (node.detail === null) {
    // An empty box: this is the field that decides what it stands for.
    const handle = document.createElement("input");
    handle.type = "text";
    handle.name = "handle";
    handle.placeholder = "@handle, a URL, or a UC… id";
    form.appendChild(graphLabelled("Which channel", handle));

    const backfill = document.createElement("input");
    backfill.type = "number";
    backfill.name = "backfill";
    backfill.min = "0";
    backfill.placeholder = "the newest few";
    form.appendChild(graphLabelled("How far back, in days", backfill));

    form.appendChild(
      graphElement(
        "p",
        "hint",
        "A handle needs Google or an API key; a UC… id needs neither. The channel stays paused until it is wired to a feed.",
      ),
    );
    return;
  }
  if (node.polled !== null) form.appendChild(graphElement("p", "hint", node.polled));
  form.appendChild(
    graphElement(
      "p",
      "hint",
      "What this box lets out is set on the channel's own page. Put a filter after it to narrow one path without touching the others.",
    ),
  );
}

function graphFeedFields(form: HTMLElement, node: GraphNodeView): void {
  form.appendChild(graphElement("p", "hint", `${node.note}. Everything wired in ends up here.`));
}

function graphTriggerFields(form: HTMLElement, node: GraphNodeView): void {
  if (node.trigger?.kind === "schedule") {
    const cron = document.createElement("input");
    cron.type = "text";
    cron.name = "cron";
    cron.value = node.trigger.cron ?? "0 9 * * *";
    cron.placeholder = "0 9 * * *";
    cron.spellcheck = false;
    form.appendChild(graphLabelled("Cron, in UTC", cron));
    form.appendChild(
      graphElement("p", "hint", `minute hour day month weekday — ${graphNextFiring(node)}`),
    );
    return;
  }
  const every = document.createElement("input");
  every.type = "number";
  every.name = "every_minutes";
  every.min = "1";
  every.value = node.trigger?.everyMinutes === null ? "" : String(node.trigger?.everyMinutes);
  form.appendChild(graphLabelled("Poll every, in minutes", every));
}

/** When a schedule next comes round, on the reader's own clock. */
function graphNextFiring(node: GraphNodeView): string {
  const next = node.trigger?.next ?? null;
  if (next === null) return "it does not come round at all";
  return `next ${new Date(next).toLocaleString()}`;
}

function graphFilterFields(form: HTMLElement, node: GraphNodeView): void {
  for (const [text, key] of [
    ["Videos", "skip_videos"],
    ["Shorts", "skip_shorts"],
    ["Live", "skip_live"],
    ["Posts", "skip_posts"],
  ] as const) {
    form.appendChild(graphLabelled(text, graphSwitchField(key, node.overrides[key])));
  }
  form.appendChild(
    graphLabelled("Title must contain", graphTextField("title_include", node.overrides["title_include"], "any")),
  );
  form.appendChild(
    graphLabelled("Title must not contain", graphTextField("title_exclude", node.overrides["title_exclude"], "nothing")),
  );
  form.appendChild(
    graphLabelled("Shortest, in seconds", graphTextField("min_duration_sec", node.overrides["min_duration_sec"], "no limit")),
  );
  form.appendChild(
    graphLabelled("Longest, in seconds", graphTextField("max_duration_sec", node.overrides["max_duration_sec"], "no limit")),
  );
  form.appendChild(
    graphLabelled("Most per sync", graphTextField("max_per_run", node.overrides["max_per_run"], "no limit")),
  );
}

// -- picking things up -----------------------------------------------------

function graphNodeIdFrom(target: EventTarget | null): number | null {
  if (!(target instanceof Element)) return null;
  const box = target.closest<HTMLElement>(".graph-node");
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
    x: event.clientX - frame.left - state.panX,
    y: event.clientY - frame.top - state.panY,
  };
}

/** The fields every drag shares, whatever kind it turns out to be. */
function graphGrab(state: GraphState, event: PointerEvent): GraphDrag {
  return {
    kind: "pan",
    nodeId: 0,
    pointerId: event.pointerId,
    grabX: 0,
    grabY: 0,
    fromX: event.clientX,
    fromY: event.clientY,
    scrollX: state.panX,
    scrollY: state.panY,
    moved: false,
  };
}

/** Whether the pointer has gone far enough that this is a drag and not a click.
 *
 *  A few pixels of travel while pressing is normal, and without this a box
 *  could not be picked with a mouse that is not perfectly still. */
function graphMovedFar(drag: GraphDrag, event: PointerEvent): boolean {
  return Math.abs(event.clientX - drag.fromX) > 3 || Math.abs(event.clientY - drag.fromY) > 3;
}

function beginGraphPan(state: GraphState, event: PointerEvent): void {
  state.drag = graphGrab(state, event);
  state.parts.canvas.classList.add("is-panning");
}

function beginGraphWire(state: GraphState, event: PointerEvent, nodeId: number): void {
  state.drag = { ...graphGrab(state, event), kind: "wire", nodeId };
  const from = graphPortPoint(state, nodeId, "out");
  if (from === null) return;
  state.ghost = graphSvgPath("graph-wire wire-ghost", graphCurve(from.x, from.y, from.x, from.y));
  state.parts.wires.appendChild(state.ghost);
}

function beginGraphMove(state: GraphState, event: PointerEvent, node: GraphNodeView): void {
  const at = pointInGraph(state, event);
  state.drag = {
    ...graphGrab(state, event),
    kind: "move",
    nodeId: node.id,
    grabX: at.x - node.x,
    grabY: at.y - node.y,
  };
  state.boxes.get(node.id)?.classList.add("is-held");
}

function onGraphPointerDown(state: GraphState, event: PointerEvent): void {
  if (event.button !== 0) return;
  const target = event.target;
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
    beginGraphPan(state, event);
    state.parts.canvas.setPointerCapture(event.pointerId);
    event.preventDefault();
    return;
  }
  const node = state.nodes.find((entry): boolean => entry.id === nodeId);
  if (node === undefined) return;

  const onPort = target instanceof Element && target.closest<HTMLElement>(".graph-port");
  if (onPort && onPort.dataset["port"] === "out") beginGraphWire(state, event, nodeId);
  else beginGraphMove(state, event, node);

  state.parts.canvas.setPointerCapture(event.pointerId);
  event.preventDefault();
}

function onGraphPointerMove(state: GraphState, event: PointerEvent): void {
  const drag = state.drag;
  if (drag === null || drag.pointerId !== event.pointerId) return;
  if (graphMovedFar(drag, event)) drag.moved = true;

  if (drag.kind === "pan") {
    panGraph(state, drag.scrollX + (event.clientX - drag.fromX),
             drag.scrollY + (event.clientY - drag.fromY));
    return;
  }

  const at = pointInGraph(state, event);
  if (drag.kind === "move") {
    const node = state.nodes.find((entry): boolean => entry.id === drag.nodeId);
    const box = state.boxes.get(drag.nodeId);
    if (node === undefined || box === undefined) return;
    // No clamping: the canvas goes on in every direction, including back.
    node.x = Math.round(at.x - drag.grabX);
    node.y = Math.round(at.y - drag.grabY);
    box.style.left = `${node.x}px`;
    box.style.top = `${node.y}px`;
    drawGraphWires(state);
    return;
  }

  const from = graphPortPoint(state, drag.nodeId, "out");
  if (from !== null && state.ghost !== null) {
    state.ghost.setAttribute("d", graphCurve(from.x, from.y, at.x, at.y));
  }
}

function graphDropTarget(event: PointerEvent): number | null {
  const under = document.elementFromPoint(event.clientX, event.clientY);
  return graphNodeIdFrom(under);
}

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

  if (drag.kind === "move") {
    state.boxes.get(drag.nodeId)?.classList.remove("is-held");
    if (!drag.moved) {
      pickGraphNode(state, drag.nodeId);
      return;
    }
    void saveGraphMove(state, drag.nodeId);
    return;
  }

  if (state.ghost !== null) {
    state.ghost.remove();
    state.ghost = null;
  }
  const target = graphDropTarget(event);
  if (target === null || target === drag.nodeId) return;
  void applyGraph(
    state,
    "/graph/connect",
    new URLSearchParams({ source: String(drag.nodeId), target: String(target) }),
  );
}

async function saveGraphMove(state: GraphState, nodeId: number): Promise<void> {
  const node = state.nodes.find((entry): boolean => entry.id === nodeId);
  if (node === undefined) return;
  try {
    await askGraph(
      `/graph/nodes/${nodeId}/move`,
      new URLSearchParams({ x: String(node.x), y: String(node.y) }),
    );
  } catch {
    showGraphError(state, "That box moved on screen, but the position was not saved.");
  }
}

// -- picking, and what follows ---------------------------------------------

function pickGraphNode(state: GraphState, nodeId: number | null): void {
  state.selectedNode = nodeId;
  state.selectedWire = null;
  renderGraph(state);
}

function pickGraphWire(state: GraphState, wireId: string): void {
  state.selectedWire = wireId;
  state.selectedNode = null;
  renderGraph(state);
}

function clearGraphPick(state: GraphState): void {
  if (state.selectedNode === null && state.selectedWire === null) return;
  state.selectedNode = null;
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
    state.selectedWire = null;
    void applyGraph(state, "/graph/disconnect", new URLSearchParams({ wire: cutId }));
    return;
  }

  const fire = target.closest<HTMLElement>("[data-fire]");
  const fireId = fire?.dataset["fire"];
  if (fireId !== undefined) {
    event.preventDefault();
    void fireGraphPulse(state, fireId);
    return;
  }

  const remove = target.closest<HTMLElement>("[data-remove]");
  const removeId = remove?.dataset["remove"];
  if (removeId !== undefined) {
    event.preventDefault();
    // A filter or a trigger stands for nothing else and just goes. A channel
    // or a feed takes its history with it, so that is said out loud first.
    const warning = remove?.dataset["what"] ?? "";
    if (warning !== "" && !window.confirm(warning)) return;
    state.selectedNode = null;
    void applyGraph(state, `/graph/nodes/${removeId}/delete`, new URLSearchParams());
    return;
  }

  if (target.closest<HTMLElement>("[data-close]") !== null) {
    event.preventDefault();
    pickGraphNode(state, null);
  }
}

/** Press a pulse. The answer carries the graph and a line about what it did. */
async function fireGraphPulse(state: GraphState, nodeId: string): Promise<void> {
  if (state.busy) return;
  state.busy = true;
  try {
    const answer = await askGraph(`/graph/nodes/${nodeId}/fire`, new URLSearchParams());
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

function onGraphKeyDown(state: GraphState, event: KeyboardEvent): void {
  if (event.key === "Escape") {
    clearGraphMarks(state);
    clearGraphPick(state);
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

// -- following one item through --------------------------------------------

function clearGraphMarks(state: GraphState): void {
  if (state.marks.size === 0) return;
  state.marks.clear();
  showGraphVerdict(state, null);
  renderGraph(state);
}

function markGraphTrace(state: GraphState, trace: GraphTraceView): void {
  state.marks.clear();
  // A box on two paths is drawn as having let the item through if any path
  // did: the interesting thing is where the item ended up, not every refusal.
  for (const step of trace.steps) {
    for (const id of step.nodes) {
      const key = `node:${id}`;
      if (step.accepted || !state.marks.has(key)) state.marks.set(key, step.accepted);
    }
    for (const id of step.wires) {
      const key = `wire:${id}`;
      if (step.accepted || !state.marks.has(key)) state.marks.set(key, step.accepted);
    }
  }
  renderGraph(state);
}

function graphVerdictFor(trace: GraphTraceView): string {
  const landed = trace.steps.filter((step): boolean => step.accepted).length;
  if (trace.steps.length === 0) {
    return `“${trace.title}” has nowhere to go — its channel is not wired to a feed.`;
  }
  const reasons: string[] = [];
  for (const step of trace.steps) {
    if (!step.accepted && step.reason !== null && !reasons.includes(step.reason)) {
      reasons.push(step.reason);
    }
  }
  const count = `“${trace.title}” got into ${landed} of ${trace.steps.length} path${
    trace.steps.length === 1 ? "" : "s"
  }.`;
  return reasons.length === 0 ? count : `${count} Held back by: ${reasons.join("; ")}.`;
}

async function runGraphTrace(state: GraphState, videoPk: string): Promise<void> {
  try {
    const answer = await askGraph(`/graph/trace/${videoPk}`, null);
    const trace = asGraphTrace(answer);
    if (trace === null) {
      showGraphError(state, asGraphError(answer) ?? "That item could not be followed.");
      return;
    }
    showGraphError(state, null);
    markGraphTrace(state, trace);
    showGraphVerdict(state, graphVerdictFor(trace));
  } catch {
    showGraphError(state, "No connection, so nothing was followed.");
  }
}

// -- setting up ------------------------------------------------------------

function graphPartsIn(canvas: HTMLElement): GraphParts | null {
  const panel = canvas.closest<HTMLElement>(".graph-panel");
  const scene = canvas.querySelector<HTMLElement>("[data-graph-scene]");
  const layer = canvas.querySelector<HTMLElement>("[data-graph-nodes]");
  const wires = canvas.querySelector<SVGSVGElement>("[data-graph-wires]");
  if (!panel || scene === null || layer === null || wires === null) return null;
  return {
    canvas,
    scene,
    layer,
    wires,
    drawer: canvas.querySelector<HTMLElement>("[data-graph-drawer]"),
    error: panel.querySelector<HTMLElement>("[data-graph-error]"),
    verdict: panel.querySelector<HTMLElement>("[data-graph-verdict]"),
    empty: panel.querySelector<HTMLElement>("[data-graph-empty]"),
  };
}

// -- the palette -----------------------------------------------------------

function toggleGraphPalette(state: GraphState, open: boolean): void {
  const drawer = state.parts.drawer;
  if (drawer === null) return;
  drawer.hidden = !open;
  state.parts.canvas
    .closest<HTMLElement>(".graph-panel")
    ?.querySelector<HTMLElement>("[data-graph-palette]")
    ?.setAttribute("aria-expanded", open ? "true" : "false");
}

/** Start dragging a kind of box out of the palette. */
function beginGraphDrop(state: GraphState, event: PointerEvent, kind: string): void {
  const ghost = graphElement("div", `graph-node kind-${graphPaletteKind(kind)} is-ghost`);
  ghost.appendChild(graphElement("span", "graph-node-kind", graphPaletteName(kind)));
  ghost.style.position = "fixed";
  ghost.style.pointerEvents = "none";
  moveGraphGhost(ghost, event);
  document.body.appendChild(ghost);

  state.dropping = { kind, pointerId: event.pointerId, ghost };
}

function moveGraphGhost(ghost: HTMLElement, event: PointerEvent): void {
  ghost.style.left = `${event.clientX - 40}px`;
  ghost.style.top = `${event.clientY - 18}px`;
}

/** A pulse and a schedule are both trigger boxes, and look like one. */
function graphPaletteKind(kind: string): string {
  return kind === "pulse" || kind === "schedule" ? "trigger" : kind;
}

function graphPaletteName(kind: string): string {
  if (kind === "source") return "Channel";
  if (kind === "feed") return "Feed";
  if (kind === "filter") return "Filter";
  return kind === "pulse" ? "Pulse" : "Schedule";
}

function finishGraphDrop(state: GraphState, event: PointerEvent): void {
  const dropping = state.dropping;
  if (dropping === null || dropping.pointerId !== event.pointerId) return;
  state.dropping = null;
  dropping.ghost.remove();

  const frame = state.parts.canvas.getBoundingClientRect();
  const inside =
    event.clientX >= frame.left && event.clientX <= frame.right &&
    event.clientY >= frame.top && event.clientY <= frame.bottom;
  if (!inside) return;

  const at = pointInGraph(state, event);
  dropGraphNode(state, dropping.kind, Math.round(at.x - 100), Math.round(at.y - 30));
}

/** Make a box of this kind, at this spot in the drawing. */
function dropGraphNode(state: GraphState, kind: string, x: number, y: number): void {
  toggleGraphPalette(state, false);
  void applyGraph(
    state,
    "/graph/nodes",
    new URLSearchParams({ kind, x: String(x), y: String(y) }),
  );
}

/** Where the middle of the view is, for a box added without being dragged. */
function graphViewCentre(state: GraphState): { x: number; y: number } {
  const frame = state.parts.canvas.getBoundingClientRect();
  return pointInGraph(state, {
    clientX: frame.left + frame.width / 2,
    clientY: frame.top + frame.height / 2,
  });
}

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

    item.addEventListener("pointerdown", (event: PointerEvent): void => {
      event.preventDefault();
      beginGraphDrop(state, event, kind);
    });
    // Pressed rather than dragged: it goes in the middle of the view, which
    // is the only spot the reader is certainly looking at.
    item.addEventListener("keydown", (event: KeyboardEvent): void => {
      if (event.key !== "Enter" && event.key !== " ") return;
      event.preventDefault();
      const centre = graphViewCentre(state);
      dropGraphNode(state, kind, Math.round(centre.x - 100), Math.round(centre.y - 30));
    });
  });
}

// -- setting up ------------------------------------------------------------

function listenToGraph(state: GraphState): void {
  const { canvas } = state.parts;
  const panel = canvas.closest<HTMLElement>(".graph-panel");

  canvas.addEventListener("pointerdown", (event: PointerEvent): void => onGraphPointerDown(state, event));
  canvas.addEventListener("pointerup", (event: PointerEvent): void => onGraphPointerUp(state, event));
  canvas.addEventListener("pointercancel", (event: PointerEvent): void => onGraphPointerUp(state, event));
  canvas.addEventListener("click", (event: MouseEvent): void => onGraphClick(state, event));
  canvas.addEventListener("keydown", (event: KeyboardEvent): void => onGraphKeyDown(state, event));
  canvas.addEventListener("submit", (event: SubmitEvent): void => {
    void onGraphSubmit(state, event);
  });

  // The wheel pans rather than scrolling the page under it: the canvas fills
  // the page, so a wheel over it can only be meant for it.
  canvas.addEventListener(
    "wheel",
    (event: WheelEvent): void => {
      event.preventDefault();
      panGraph(state, state.panX - event.deltaX, state.panY - event.deltaY);
    },
    { passive: false },
  );

  // On the window, not the canvas: a palette box is dragged from outside it,
  // and a box dragged past its edge should keep following the pointer.
  window.addEventListener("pointermove", (event: PointerEvent): void => {
    if (state.dropping !== null && state.dropping.pointerId === event.pointerId) {
      moveGraphGhost(state.dropping.ghost, event);
      return;
    }
    onGraphPointerMove(state, event);
  });
  window.addEventListener("pointerup", (event: PointerEvent): void => {
    finishGraphDrop(state, event);
  });

  if (panel !== null) listenToPalette(state, panel);

  const trace = panel?.querySelector<HTMLFormElement>("[data-graph-trace]");
  trace?.addEventListener("submit", (event: SubmitEvent): void => {
    event.preventDefault();
    const picked = trace.querySelector<HTMLSelectElement>("select");
    if (picked !== null) void runGraphTrace(state, picked.value);
  });

  // Boxes are measured to place the wires, so a resize moves them.
  window.addEventListener("resize", (): void => drawGraphWires(state));
}

function startGraph(canvas: HTMLElement): void {
  if (canvas.dataset["ready"] === "1") return;
  const parts = graphPartsIn(canvas);
  if (parts === null) return;
  canvas.dataset["ready"] = "1";

  const state: GraphState = {
    parts,
    nodes: [],
    wires: [],
    boxes: new Map<number, HTMLElement>(),
    selectedNode: null,
    selectedWire: null,
    drag: null,
    ghost: null,
    marks: new Map<string, boolean>(),
    busy: false,
    panX: 0,
    panY: 0,
    dropping: null,
  };
  listenToGraph(state);
  panGraph(state, 0, 0);
  void applyGraph(state, "/api/graph", null);
}

function findGraphs(root: ParentNode): void {
  root.querySelectorAll<HTMLElement>("[data-graph]").forEach(startGraph);
}

function initGraph(): void {
  document.addEventListener("DOMContentLoaded", (): void => findGraphs(document));
  document.body.addEventListener("htmx:afterSwap", (): void => findGraphs(document));
  findGraphs(document);
}

initGraph();
