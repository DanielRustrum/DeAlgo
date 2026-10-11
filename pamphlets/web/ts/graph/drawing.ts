// Drawing the boxes, the pieces slotted under them, and the wires between.
//
// Part of the Configuration canvas; see main.ts.

/** A new element with a class, and its text if given. */
function graphElement(tag: string, className: string, text?: string): HTMLElement {
  const made = document.createElement(tag);
  made.className = className;
  if (text !== undefined) made.textContent = text;
  return made;
}

/** A kind's name as the canvas shows it. */
function graphKindLabel(kind: GraphNodeKind): string {
  if (kind === "source") return "Source";
  if (kind === "deposit") return "Deposit";
  if (kind === "withdraw") return "Withdraw";
  if (kind === "timer") return "Timer";
  if (kind === "reset") return "Reset";
  if (kind === "alive") return "Alive";
  if (kind === "lock") return "Lock";
  if (kind === "after-watch") return "After watching";
  if (kind === "decay") return "Decay";
  if (kind === "expire") return "Expire";
  if (kind === "tag") return "Tag";
  if (kind === "feed") return "Feed";
  if (kind === "sort") return "Sort";
  if (kind === "group") return "Group";
  if (kind === "rule") return "Rule";
  if (kind === "has-words") return "Title has";
  if (kind === "lacks-words") return "Title lacks";
  if (kind === "longer-than") return "Longer than";
  if (kind === "shorter-than") return "Shorter than";
  if (kind === "pamphlet") return "Pamphlet";
  if (kind === "format") return "Format";
  if (kind === "transform") return "Transform";
  if (kind === "text") return "Text";
  if (kind === "count") return "Count";
  if (kind === "aggregation") return "Aggregation";
  if (kind === "leaflet-feed") return "Feed leaflet";
  if (kind === "leaflet-bar") return "Bar chart";
  if (kind === "leaflet-line") return "Line chart";
  if (kind === "leaflet-pie") return "Pie chart";
  if (kind === "leaflet-radar") return "Radar chart";
  if (kind === "leaflet-polar") return "Polar area chart";
  if (kind === "leaflet-scatter") return "Scatter chart";
  if (kind === "leaflet-bubble") return "Bubble chart";
  if (kind === "leaflet-number") return "Number leaflet";
  if (kind === "leaflet-table") return "Table leaflet";
  if (kind === "leaflet-text") return "Text leaflet";
  if (kind === "leaflet-link") return "Link leaflet";
  if (kind === "carrying") return "Has tag";
  if (kind === "lacks-tag") return "Lacks tag";
  if (kind === "at-most") return "At most";
  if (kind === "order") return "Order";
  return kind === "trigger" ? "Trigger" : "Filter";
}

/** What an empty source box is waiting to be told. */
interface GraphAsks {
  /** The kind it was dragged out as. "" for a box made before kinds. */
  kind: string;
  /** What that kind's box is called: "Subreddit". */
  label: string;
  /** The short name of the kind — "Reddit" — for the word above the title. */
  source: string;
  /** What to type, said the way somebody would say it. */
  example: string;
  /** Whether anything still provides this kind. False when its plugin is
   *  switched off, which is worth saying rather than silently refusing
   *  everything typed into it. */
  known: boolean;
  /** The colour its plugin chose for its boxes; "" for the default. */
  colour: string;
}

/** An augmentation: what it is slotted under, and what it carries. */
interface GraphPiece {
  /** The box or piece it sits under. Null while it is loose on the canvas. */
  under: number | null;
  /** Which edge of that it hangs from. Only a leaflet ever hangs beside. */
  side: "below" | "beside";
  /** Timer: how long the sitting lasts. */
  minutes: number;
  /** Reset: the cron that gives you another. */
  cron: string;
  /** Alive: the two ends of the stretch of day it allows, as "HH:MM". */
  from: string;
  to: string;
  /** Timer: its amount and unit, and the units it could be said in. */
  every: GraphEvery;
  /** Which boxes it may be slotted under, comma-separated. Empty where
   *  nothing is known — a piece whose plugin is switched off. */
  hosts: string;
}

/** One condition piece: what it narrows by, and how to ask for it. */
interface GraphCondition {
  label: string;
  blurb: string;
  /** How the panel asks: a line of text, a list of tags, a number, a
   *  length, or the two selects that say what to order a batch by. */
  field: "text" | "tags" | "number" | "duration" | "order";
  asks: string;
  /** Which box it belongs under, for saying so when it is loose. */
  under: "filter" | "sort";
  /** What it is set to. A length arrives already split into this and a unit. */
  value: string;
  unit: string;
  units: string[];
  /** What it says on the canvas, for the panel to repeat back. */
  says: string;
  /** A tag condition: every tag there is, to pick from. */
  choices: string[];
}

/** What a marking box carries. */
interface GraphStamp {
  /** Tag boxes: what it marks whatever passes with. */
  marks: string;
  /** Tag boxes: choosing its tags by item, and how. Null on other boxes. */
  choosing: GraphTagChoosing | null;
}

/** A Tag box's choosing: which tags, how many, and with what. */
interface GraphTagChoosing {
  mode: string;
  modes: GraphChoice[];
  /** One per line: `name — what it means`. */
  tags: string;
  least: number;
  most: number;
  engine: string;
  engines: GraphChoice[];
  /** What it chooses with, in a sentence. */
  how: string;
}

/** What a Deposit or Withdraw box is about. */
interface GraphStore {
  /** The repository it names, as it is filed: trimmed and lowercased. */
  name: string;
  /** How many items are waiting in it right now. */
  waiting: number;
  /** Withdraw boxes: how many to take each pull. 0 means everything. */
  takes: number;
  /** True for a Withdraw box, false for a Deposit. */
  pulls: boolean;
}

/** What travels down a wire: a nudge to run, or the things being collected. */
type GraphCarries = "signal" | "content" | "page" | "data";

/** A port dot on a box's edge: where wires leave or arrive. */
function graphPort(where: "in" | "out", carries: GraphCarries, says: string): HTMLElement {
  const dot = graphElement("span", `graph-port port-${where} carries-${carries}`);
  dot.dataset["port"] = where;
  dot.title = says;
  dot.appendChild(graphPortIcon(carries));
  return dot;
}

/** The mark inside a port. Drawn rather than written: at this size a letter
 *  is a smudge, and a shape is still a shape. */
function graphPortIcon(carries: GraphCarries): SVGSVGElement {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("class", "graph-port-icon");
  svg.setAttribute("viewBox", "0 0 10 10");
  svg.setAttribute("aria-hidden", "true");

  const mark = document.createElementNS("http://www.w3.org/2000/svg", "path");
  mark.setAttribute(
    "d",
    carries === "signal"
      // A bolt: something setting the channel off.
      ? "M6.2 0.6 L2.2 5.6 H4.5 L3.8 9.4 L7.8 4.4 H5.5 Z"
      : carries === "page"
        // A folded sheet with lines of print: a feed going onto a page.
        ? "M1.4 0.8 H8.6 V9.2 H1.4 Z M2.8 2.4 V3.4 H7.2 V2.4 Z M2.8 4.5 V5.5 H7.2 V4.5 Z M2.8 6.6 V7.6 H5.6 V6.6 Z"
        // A play mark: the videos and posts being carried along.
        : "M2.6 1.2 L8.2 5 L2.6 8.8 Z",
  );
  if (carries === "page") mark.setAttribute("fill-rule", "evenodd");
  if (carries === "data") {
    // Braces: raw JSON, before it is anything to look at.
    mark.setAttribute(
      "d",
      "M3.6 1.2 C2.2 1.2 2.6 3.6 2.4 4.3 C2.2 4.9 1.6 5 1.6 5 C1.6 5 2.2 5.1 2.4 5.7 C2.6 6.4 2.2 8.8 3.6 8.8 " +
        "M6.4 1.2 C7.8 1.2 7.4 3.6 7.6 4.3 C7.8 4.9 8.4 5 8.4 5 C8.4 5 7.8 5.1 7.6 5.7 C7.4 6.4 7.8 8.8 6.4 8.8",
    );
    mark.setAttribute("fill", "none");
    mark.setAttribute("stroke", "currentColor");
    mark.setAttribute("stroke-width", "1.3");
    mark.setAttribute("stroke-linecap", "round");
  }
  svg.appendChild(mark);
  return svg;
}

/** Whether a wheel was meant for a panel rather than for the canvas.
 *
 *  The palette, the finder, the run log and a box's own panel all sit inside
 *  the canvas, so that they travel with it and stay put over it. Which means
 *  a wheel over any of them bubbles to the canvas, and the canvas zooms —
 *  when what you meant was to get further down the list you were reading.
 *
 *  Asked of the elements themselves rather than of a list of which ones they
 *  are: anything laid over the canvas that scrolls wants its own wheel, and a
 *  list kept by hand is a list that goes stale the next time one is added. */
function graphWheelBelongsToAPanel(target: EventTarget | null, canvas: Element): boolean {
  let walk = target instanceof Element ? target : null;
  while (walk !== null && walk !== canvas) {
    const said = window.getComputedStyle(walk).overflowY;
    if (said === "auto" || said === "scroll") return true;
    walk = walk.parentElement;
  }
  return false;
}

/** What each side of a box takes in or gives out, in a sentence. */
function graphPortWords(kind: GraphNodeKind, where: "in" | "out"): string {
  if (kind === "trigger") return "Gives out a signal: wire it to a channel to say when to poll it.";
  if (kind === "source") {
    return where === "in"
      ? "Takes a signal: a trigger wired here says when this channel is polled."
      : "Gives out what it collects — videos and posts — to whatever is wired on.";
  }
  if (kind === "filter") {
    return where === "in"
      ? "Takes what arrives, and judges it."
      : "Gives out only what got through.";
  }
  if (kind === "format") {
    return "Takes JSON: wire a source box here — a REST API's answer, or any source's items.";
  }
  if (kind === "deposit") {
    return "Takes what is wired in and holds it. Nothing comes out until a Withdraw pulls.";
  }
  if (kind === "withdraw") {
    return where === "in"
      ? "Takes a signal: a trigger wired here says when to pull from the repository."
      : "Gives out what it pulled, to whatever is wired on.";
  }
  return "Takes what is wired in. This is where things end up.";
}

/** A group's background frame, with its name and resize handle. */
function drawGraphGroup(state: GraphState, node: GraphNodeView): HTMLElement {
  const frame = graphElement("div", "graph-group-box");
  frame.dataset["node"] = String(node.id);
  frame.style.left = `${node.x}px`;
  frame.style.top = `${node.y}px`;
  frame.style.width = `${node.size?.width ?? 520}px`;
  frame.style.height = `${node.size?.height ?? 300}px`;
  frame.tabIndex = 0;
  frame.setAttribute("role", "button");
  frame.setAttribute("aria-label", `Group: ${node.title}`);
  if (state.picked.has(node.id)) frame.classList.add("is-picked");
  if (!node.enabled) frame.classList.add("is-off");

  if (node.locked) frame.classList.add("is-locked");

  const name = graphElement("span", "graph-group-name", node.title);
  // A padlock beside the name: pressed, it holds the group where it is, so a
  // drag across it pans the canvas instead of carrying everything inside off.
  const lock = graphElement("button", "graph-group-lock") as HTMLButtonElement;
  lock.type = "button";
  lock.dataset["lock"] = String(node.id);
  lock.setAttribute("aria-pressed", String(node.locked));
  lock.title = node.locked ? "Locked in place — press to unlock" : "Lock in place";
  lock.setAttribute("aria-label", node.locked ? `Unlock group ${node.title}` : `Lock group ${node.title}`);
  lock.appendChild(graphPadlock(node.locked));
  name.appendChild(lock);
  frame.appendChild(name);

  // Bottom-right, where a resize handle is looked for. A locked group has
  // none: holding it in place holds its size too.
  if (!node.locked) {
    const grip = graphElement("span", "graph-group-grip");
    grip.dataset["grip"] = String(node.id);
    grip.title = "Drag to resize";
    frame.appendChild(grip);
  }
  return frame;
}

/** A small padlock, shut or open, drawn in the text colour. */
function graphPadlock(shut: boolean): SVGSVGElement {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 16 16");
  svg.setAttribute("aria-hidden", "true");
  const shackle = document.createElementNS("http://www.w3.org/2000/svg", "path");
  // Shut, the shackle comes down into the body; open, it swings up and aside.
  shackle.setAttribute("d", shut ? "M5 7V5a3 3 0 0 1 6 0v2" : "M5 7V5a3 3 0 0 1 5.6-1.5");
  shackle.setAttribute("fill", "none");
  shackle.setAttribute("stroke", "currentColor");
  shackle.setAttribute("stroke-width", "1.6");
  shackle.setAttribute("stroke-linecap", "round");
  const body = document.createElementNS("http://www.w3.org/2000/svg", "rect");
  body.setAttribute("x", "3.5");
  body.setAttribute("y", "7");
  body.setAttribute("width", "9");
  body.setAttribute("height", "7");
  body.setAttribute("rx", "1.5");
  body.setAttribute("fill", "currentColor");
  svg.append(shackle, body);
  return svg;
}

/** One box or piece: its title, note, ports and buttons. */
function drawGraphNode(state: GraphState, node: GraphNodeView): HTMLElement {
  const box = graphElement("div", `graph-node kind-${node.kind}`);
  box.dataset["node"] = String(node.id);
  box.style.left = `${node.x}px`;
  box.style.top = `${node.y}px`;
  box.tabIndex = 0;
  box.setAttribute("role", "button");
  box.setAttribute("aria-label", `${graphTriggerLabel(node)}: ${node.title}`);
  if (state.picked.has(node.id)) box.classList.add("is-picked");
  if (!node.enabled) box.classList.add("is-off");
  // A source wears the colour its plugin chose (kinds.css reads it).
  const colour = node.channel?.colour ?? node.asks?.colour ?? "";
  if (colour !== "") box.dataset["colour"] = colour;

  if (node.piece !== null) {
    // A piece is slotted, not wired: nothing runs into or out of one, so it
    // has no ports at all.
    box.classList.add("is-piece");
    // A piece nobody has slotted in yet is the only one that shows its tab:
    // a joined edge has the tab inside the joint, not drawn on top of it.
    if (node.piece.under === null) box.classList.add("is-loose");
    box.appendChild(graphElement("span", "graph-node-kind", graphKindLabel(node.kind)));
    box.appendChild(graphElement("strong", "graph-node-title", node.note));
    if (graphIsLeaflet(node.kind)) drawGraphLeafletParts(box, node);
    return box;
  }
  const ports = graphPortKinds(node.kind, node.dataOnly);
  for (const takes of ports.in) {
    box.appendChild(graphPort("in", takes, graphPortSays(node.kind, "in", takes)));
  }
  box.appendChild(graphElement("span", "graph-node-kind", graphTriggerLabel(node)));
  box.appendChild(graphElement("strong", "graph-node-title", node.title));
  box.appendChild(graphElement("span", "graph-node-note", node.note));
  if (node.trigger !== null) box.appendChild(graphFireButton(node));
  for (const gives of ports.out) {
    box.appendChild(graphPort("out", gives, graphPortSays(node.kind, "out", gives)));
  }
  graphSpreadPorts(box);
  return box;
}

/** The boxes data runs through on its way to a Format box, changed by each
 *  the way items are: a Filter keeps rows, a Sort orders them. */
function graphDataOps(): GraphNodeKind[] {
  return ["filter", "sort", "tag", "decay", "expire"];
}

/** Which kinds of wire a box takes in, and gives out — a port for each.
 *  The same answer the server's wiring table gives, side by side: an
 *  operation box passes items and data, separately, at the same time. */
function graphPortKinds(
  kind: GraphNodeKind, dataOnly = false,
): { in: GraphCarries[]; out: GraphCarries[] } {
  if (kind === "trigger") return { in: [], out: ["signal"] };
  // A REST API answers with records and numbers: data, and no items.
  if (kind === "source" && dataOnly) return { in: ["signal"], out: ["data"] };
  // Items or data in; data out, as the piece under it says.
  if (kind === "transform") return { in: ["content", "data"], out: ["data"] };
  // Items or data in; words out, onto a page.
  if (kind === "text") return { in: ["content", "data"], out: ["page"] };
  if (kind === "source" || kind === "withdraw") return { in: ["signal"], out: ["content", "data"] };
  // A feed and a deposit are both ends of a path. What a feed holds can go
  // onto a page; what a repository holds can go on as data.
  if (kind === "feed") return { in: ["content"], out: ["page"] };
  if (kind === "deposit") return { in: ["content"], out: ["data"] };
  if (kind === "format") return { in: ["data"], out: ["data"] };
  if (graphDataOps().indexOf(kind) >= 0) return { in: ["content", "data"], out: ["content", "data"] };
  // A pamphlet is on no path: nothing runs into or out of one.
  return { in: [], out: [] };
}

/** What one port takes in or gives out, in a sentence. */
function graphPortSays(kind: GraphNodeKind, where: "in" | "out", carries: GraphCarries): string {
  if (carries === "page" && kind === "text") return "Gives out what it wrote, onto a page: wire it to a Text leaflet.";
  if (carries === "page") return "Gives out what it holds, onto a page: wire it to a Feed or Link leaflet.";
  if (kind === "text") {
    return carries === "content"
      ? "Takes items: what comes down a path, for the model to read."
      : "Takes data: JSON, for the model to read.";
  }
  if (carries === "content" && kind === "transform") {
    return "Takes items: what comes down a path, to be counted or changed into data.";
  }
  if (carries !== "data") return graphPortWords(kind, where);
  if (kind === "transform") {
    return where === "in"
      ? "Takes data: JSON, or what a box before it passed on."
      : "Gives out what the piece under it makes — a count — as data.";
  }
  if (kind === "format") {
    return where === "in"
      ? "Takes JSON: a source's, or what an operation passed on."
      : "Gives out bars to draw: wire it to a Chart leaflet.";
  }
  if (kind === "source") return "Gives out its JSON — an API's answer, or its items — to an operation or a Format box.";
  if (kind === "deposit" || kind === "withdraw") return "Gives out what is waiting in the repository, as JSON.";
  return where === "in"
    ? "Takes JSON, and changes it the way this box changes items."
    : "Gives out the JSON as this box left it, for another operation or a Format box.";
}

/** Ports on one side, spaced evenly down it: one in the middle, two at a
 *  third and two thirds, so each kind of wire has a place of its own. */
function graphSpreadPorts(box: HTMLElement): void {
  for (const where of ["in", "out"]) {
    const ports = Array.from(box.querySelectorAll<HTMLElement>(`:scope > .graph-port.port-${where}`));
    if (ports.length < 2) continue;
    ports.forEach((port, index): void => {
      port.style.top = `${Math.round((100 * (index + 1)) / (ports.length + 1))}%`;
    });
  }
}

/** What a wire carries, read off its kind and the box it starts from: which
 *  port at either end it belongs to. */
function graphWireCarries(state: GraphState, wire: GraphWireView): GraphCarries {
  if (wire.kind === "page" || wire.kind === "data") return wire.kind;
  const start = state.nodes.find((one): boolean => one.id === wire.from);
  return start?.kind === "trigger" ? "signal" : "content";
}

/** Fade a port with no wire, on a side where another port has one: the
 *  connection in use stands out, and the one not taken still works. */
function graphMarkIdlePorts(state: GraphState): void {
  const used = new Set<string>();
  for (const wire of state.wires) {
    const carries = graphWireCarries(state, wire);
    used.add(`${wire.from}:out:${carries}`);
    used.add(`${wire.to}:in:${carries}`);
  }
  for (const [nodeId, box] of state.boxes) {
    for (const where of ["in", "out"]) {
      const ports = Array.from(box.querySelectorAll<HTMLElement>(`:scope > .graph-port.port-${where}`));
      if (ports.length < 2) continue;
      const taken = ports.map((port): boolean =>
        Array.from(port.classList).some(
          (name): boolean => name.startsWith("carries-") && used.has(`${nodeId}:${where}:${name.slice(8)}`),
        ),
      );
      const any = taken.some((one): boolean => one);
      ports.forEach((port, index): void => {
        port.classList.toggle("is-idle", any && !taken[index]);
      });
    }
  }
}

/** A trigger says which of the two it is, since they behave nothing alike. */
function graphTriggerLabel(node: GraphNodeView): string {
  if (node.trigger !== null) return node.trigger.kind === "pulse" ? "Pulse" : "Schedule";
  // A source box says where it watches rather than that it is a source box.
  // Which of the two it is, is the thing somebody chose when they dragged it
  // out; "Channel" said the same for a subreddit and a YouTube channel and
  // so said nothing at all.
  if (node.kind === "source") return graphSourceLabel(node);
  // A plugin's augmentation is its plugin's, and saying so is more use than the word
  // "plugin" over a name that is already the box's own.
  if (node.plugin !== null && node.plugin.plugin !== "") return node.plugin.plugin;
  return graphKindLabel(node.kind);
}

/** Where a source box watches: "Reddit", "YouTube". Filled boxes read it off
 *  the channel behind them, empty ones off the kind they were dragged out as,
 *  and a box whose plugin has gone falls back to the plain word. */
function graphSourceLabel(node: GraphNodeView): string {
  if (node.channel !== null && node.channel.source !== "") return node.channel.source;
  if (node.asks !== null && node.asks.source !== "") return node.asks.source;
  return "Source";
}

/** A trigger's Run now and Backfill buttons. */
function graphFireButton(node: GraphNodeView): HTMLElement {
  const buttons = graphElement("div", "graph-fire");

  const run = graphElement("button", "btn btn-quiet", "Run now");
  run.setAttribute("type", "button");
  run.title = "Poll what this is wired to, now, whatever its gap says";
  // Both reach the server, so both go quiet when the connection does.
  run.dataset["needsNetwork"] = "";
  run.dataset["fire"] = String(node.id);
  buttons.appendChild(run);

  // The same poll, reaching as far back as the feeds still go.
  const back = graphElement("button", "btn btn-quiet", "Backfill");
  back.setAttribute("type", "button");
  back.title = "Take everything these feeds still list, not only what is new";
  back.dataset["needsNetwork"] = "";
  back.dataset["backfill"] = String(node.id);
  buttons.appendChild(back);

  // Beside it, because it is the same act with the consequences taken out.
  const test = graphElement("button", "btn btn-quiet", "Test");
  test.setAttribute("type", "button");
  test.title = "Say where everything would land, without landing it anywhere";
  test.dataset["test"] = String(node.id);
  buttons.appendChild(test);

  return buttons;
}

/** Every box and piece, drawn afresh; groups first, under everything else. */
function drawGraphNodes(state: GraphState): void {
  state.parts.layer.textContent = "";
  state.parts.groups.textContent = "";
  state.boxes.clear();
  // Groups into their own layer, under the wires: a group is a background,
  // and a rectangle over what it surrounds would be in the way of all of it —
  // including the wires crossing it, which would stop being clickable.
  for (const node of state.nodes) {
    if (node.kind !== "group") continue;
    const frame = drawGraphGroup(state, node);
    state.boxes.set(node.id, frame);
    state.parts.groups.appendChild(frame);
  }
  for (const node of state.nodes) {
    if (node.kind === "group") continue;
    const box = drawGraphNode(state, node);
    state.boxes.set(node.id, box);
    state.parts.layer.appendChild(box);
  }
  placeGraphPieces(state);
}

/** Stack each slotted piece under whatever it is slotted into.
 *
 *  Measured rather than guessed: a box is as tall as its own contents, and a
 *  piece has to sit against the bottom of it however tall that turned out.
 *  Done after everything is in the document, which is the first moment there
 *  is a height to read. */
function placeGraphPieces(state: GraphState): void {
  const under = new Map<number, GraphNodeView[]>();
  for (const node of state.nodes) {
    const host = node.piece?.under;
    if (host === undefined || host === null) continue;
    // Leaflets hang beside as well as below: they are laid out as a page.
    if (graphIsLeaflet(node.kind)) continue;
    const kept = under.get(host);
    if (kept === undefined) under.set(host, [node]);
    else kept.push(node);
  }
  placeGraphLeaflets(state);
  if (under.size === 0) return;

  // From the model's own coordinates, which is what every other box is drawn
  // from. `offsetTop` is measured against whichever ancestor happens to be
  // positioned, so a piece placed from it lands wherever that ancestor is
  // rather than under its host.
  // `kind` is the box at the top of the stack: every piece in it is part of
  // that box, and wears its colour (kinds.css reads data-host).
  const place = (hostId: number, kind: string, left: number, top: number, depth: number): void => {
    if (depth > 12) return;  // a ring built before they were refused
    for (const piece of under.get(hostId) ?? []) {
      const box = state.boxes.get(piece.id);
      if (box === undefined) continue;
      box.dataset["host"] = kind;
      box.style.left = `${left}px`;
      box.style.top = `${top}px`;
      // Kept on the node as well, so anything that reads a position — a
      // group working out what it surrounds, a drag starting from here —
      // sees where the piece actually is.
      piece.x = left;
      piece.y = top;
      const next = top + box.offsetHeight;
      place(piece.id, kind, left, next, depth + 1);
      top = next;
    }
  };

  // A box with something slotted into it gets the notch the tab sits in.
  for (const [hostId] of under) {
    state.boxes.get(hostId)?.classList.add("has-piece");
  }

  for (const node of state.nodes) {
    if (node.piece !== null) continue;  // a chain belongs to the box at its top
    const box = state.boxes.get(node.id);
    if (box === undefined || !under.has(node.id)) continue;
    place(node.id, node.kind, node.x, node.y + box.offsetHeight, 0);
  }
}

/** Where a wire leaves a box, and where it arrives — measured, not guessed. */
function graphPortPoint(
  state: GraphState,
  nodeId: number,
  where: "in" | "out",
  carries?: GraphCarries,
): { x: number; y: number } | null {
  const box = state.boxes.get(nodeId);
  const node = state.nodes.find((entry): boolean => entry.id === nodeId);
  if (box === undefined || node === undefined) return null;

  // At its own port, where a box has more than one on that side.
  const port = carries === undefined
    ? null
    : box.querySelector<HTMLElement>(`:scope > .graph-port.port-${where}.carries-${carries}`);
  const y = port !== null && port.offsetHeight > 0
    ? node.y + port.offsetTop + port.offsetHeight / 2
    : node.y + box.offsetHeight / 2;
  return { x: where === "out" ? node.x + box.offsetWidth : node.x, y };
}

/** The SVG path of a wire: a gentle S from one port to another. */
function graphCurve(x1: number, y1: number, x2: number, y2: number): string {
  const reach = Math.max(40, Math.abs(x2 - x1) * 0.5);
  return `M ${x1} ${y1} C ${x1 + reach} ${y1}, ${x2 - reach} ${y2}, ${x2} ${y2}`;
}

/** An SVG path element with a class. */
function graphSvgPath(className: string, d: string): SVGPathElement {
  const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
  path.setAttribute("class", className);
  path.setAttribute("d", d);
  return path;
}

/** Every wire, drawn afresh, each with an invisible fat path for the pointer. */
function drawGraphWires(state: GraphState): void {
  state.parts.wires.textContent = "";
  // The ✕ belongs to a wire but lives among the boxes, so it is cleared here
  // rather than with them — a drag redraws the wires many times over.
  state.parts.layer.querySelectorAll(".graph-cut").forEach((button): void => button.remove());
  const over = graphPageWireLayer(state);
  over.textContent = "";
  for (const wire of state.wires) {
    const carries = graphWireCarries(state, wire);
    const from = graphPortPoint(state, wire.from, "out", carries);
    const to = graphPortPoint(state, wire.to, "in", carries);
    if (from === null || to === null) continue;

    const d = graphCurve(from.x, from.y, to.x, to.y);
    let classes = `graph-wire wire-${wire.kind}`;
    if (wire.id === state.selectedWire) classes += " is-picked";

    // A two-pixel line is impossible to click. The fat one is invisible and
    // takes the pointer; the thin one is what is actually seen.
    const hit = graphSvgPath("graph-wire-hit", d);
    hit.setAttribute("data-wire", wire.id);
    state.parts.wires.appendChild(hit);

    const line = graphSvgPath(classes, d);
    // Named rather than found by where it sits: the run lights these, and a
    // lookup that depended on the order they were appended in would stop
    // working the day something else is appended between them.
    line.setAttribute("data-line", wire.id);
    state.parts.wires.appendChild(line);
    if (wire.kind !== "edge") drawGraphWireIntoPage(state, over, wire, d, classes);

    if (wire.id === state.selectedWire) {
      state.parts.layer.appendChild(graphCutButton(wire.id, (from.x + to.x) / 2, (from.y + to.y) / 2));
    }
  }
  graphMarkIdlePorts(state);
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
/** How far in and out the canvas will go. Past these it stops being useful. */
function graphZoomLimits(): { least: number; most: number } {
  return { least: 0.3, most: 2.5 };
}

/** Move the whole drawing under the window. The canvas has no edges. */
function panGraph(state: GraphState, x: number, y: number): void {
  state.panX = x;
  state.panY = y;
  showGraphView(state);
}

/** Where the view is kept between visits: this browser's, as a convenience. */
function graphViewKey(): string {
  return "pamphlets-canvas-view";
}

/** Note where the canvas is looked at, so leaving the tab and coming back
 *  — or reloading — finds it where it was rather than back at the start. */
function keepGraphView(state: GraphState): void {
  try {
    window.localStorage.setItem(graphViewKey(), JSON.stringify({ x: state.panX, y: state.panY, zoom: state.zoom }));
  } catch {
    // Storage refused (a private window, say): the canvas still works.
  }
}

/** Put the view back where it was last left, or at the start if it never
 *  was — or if what was kept is not a view this canvas can show. */
function restoreGraphView(state: GraphState): void {
  let kept: unknown = null;
  try {
    kept = JSON.parse(window.localStorage.getItem(graphViewKey()) ?? "null");
  } catch {
    kept = null;
  }
  const view = asGraphRecord(kept);
  const x = view?.["x"];
  const y = view?.["y"];
  const zoom = view?.["zoom"];
  const limits = graphZoomLimits();
  if (typeof x === "number" && typeof y === "number" && typeof zoom === "number"
      && Number.isFinite(x) && Number.isFinite(y) && zoom >= limits.least && zoom <= limits.most) {
    state.zoom = zoom;
    panGraph(state, x, y);
    return;
  }
  panGraph(state, 0, 0);
}

/** Apply the pan and zoom to the drawing and its grid. */
function showGraphView(state: GraphState): void {
  const { panX, panY, zoom } = state;
  state.parts.scene.style.transform = `translate(${panX}px, ${panY}px) scale(${zoom})`;
  state.parts.scene.style.transformOrigin = "0 0";
  // The grid moves and scales with it, or the drawing looks like it is
  // sliding over a pattern that is nailed down.
  const grid = 26 * zoom;
  state.parts.canvas.style.backgroundSize = `${grid}px ${grid}px`;
  state.parts.canvas.style.backgroundPosition = `${panX}px ${panY}px`;
  keepGraphView(state);

  const reading = state.parts.canvas.querySelector<HTMLElement>("[data-graph-zoom]");
  if (reading !== null) reading.textContent = `${Math.round(zoom * 100)}%`;
}

/** Zoom about a point on screen, so whatever is under the pointer stays put.
 *
 *  Zooming about the corner instead would send the thing being looked at off
 *  the edge, which is the difference between a zoom and a surprise. */
function zoomGraph(state: GraphState, factor: number, clientX: number, clientY: number): void {
  const limits = graphZoomLimits();
  const next = Math.min(limits.most, Math.max(limits.least, state.zoom * factor));
  if (next === state.zoom) return;

  const at = pointInGraph(state, { clientX, clientY });
  const frame = state.parts.canvas.getBoundingClientRect();
  state.zoom = next;
  state.panX = clientX - frame.left - at.x * next;
  state.panY = clientY - frame.top - at.y * next;
  showGraphView(state);
}

/** Redraw everything from the state: boxes, wires, panel, finder, run marks. */
function renderGraph(state: GraphState): void {
  drawGraphNodes(state);
  drawGraphWires(state);
  renderGraphPopover(state);
  renderGraphFinder(state);
  // The boxes were just rebuilt from scratch, so whatever the run had marked
  // on them has to go back on.
  paintGraphRun(state);
  // The canvas itself is never hidden: the palette lives inside it, so an
  // account with nothing on it would have nothing to add anything with.
  if (state.parts.empty !== null) state.parts.empty.hidden = state.nodes.length > 0;
}

/** Show a refusal over the canvas, or clear it with null. */
function showGraphError(state: GraphState, message: string | null): void {
  const box = state.parts.error;
  if (box === null) return;
  box.textContent = message ?? "";
  box.hidden = message === null;
}

/** Show a test's verdict over the canvas, or clear it with null. */
function showGraphVerdict(state: GraphState, message: string | null): void {
  const box = state.parts.verdict;
  if (box === null) return;
  box.textContent = message ?? "";
  box.hidden = message === null;
}
