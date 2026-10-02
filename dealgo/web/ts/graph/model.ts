// What the canvas draws: the kinds of box, and what each kind may do.
//
// Part of the Configuration canvas; see main.ts.

/** Every kind of box and piece the canvas draws. */
type GraphNodeKind =
  | "trigger" | "source" | "filter" | "sort" | "feed" | "group"
  // The two ends of a named repository. A deposit ends a path the way a feed
  // does; a withdraw starts one the way a source does.
  | "deposit"
  | "withdraw"
  // Augmentations. Not on any path and not wired to anything: each is
  // slotted under a box and changes what that box does.
  | "timer"
  | "reset"
  | "alive"
  | "lock"
  // Boxes that mark what passes through them rather than narrowing it.
  | "decay"
  | "expire"
  | "tag"
  // Conditions: one piece per thing a Filter narrows by, and one for what a
  // Sort orders by. A box saying "Filter" told you nothing; a piece saying
  // "Longer than" says what that box does without opening it.
  | "has-words"
  | "lacks-words"
  | "longer-than"
  | "shorter-than"
  | "carrying"
  | "at-most"
  | "order"
  // A condition a plugin declared, slotted under a Filter like any other.
  // One kind for all of them, because which ones exist depends on which
  // plugins are loaded — which one this is arrives in `plugin`.
  | "rule";

/** The conditions the host itself offers, as against a plugin's. */
function graphConditionKinds(): GraphNodeKind[] {
  return [
    "has-words", "lacks-words", "longer-than", "shorter-than",
    "carrying", "at-most", "order",
  ];
}

/** Which kinds are pieces rather than boxes. */
function graphIsPiece(kind: GraphNodeKind): boolean {
  return (
    kind === "timer" || kind === "reset" || kind === "alive" || kind === "lock" ||
    kind === "rule" || graphConditionKinds().indexOf(kind) >= 0
  );
}

/** Which boxes have somewhere for a piece to go. */
function graphTakesPieces(kind: GraphNodeKind): boolean {
  return (
    kind === "feed" || kind === "decay" || kind === "expire" ||
    kind === "filter" || kind === "sort"
  );
}

/** There used to be two: a source's wire was stored against its channel and
 *  drawn from that, which is why two boxes for one channel showed the same
 *  wires. Every wire is an edge now. */
type GraphWireKind = "edge";

/** One box or piece as the server sent it. */
interface GraphNodeView {
  id: number;
  kind: GraphNodeKind;
  title: string;
  x: number;
  y: number;
  /** Where the thing behind the box lives, for source and feed boxes. */
  detail: string | null;
  note: string;
  /** Whether this box is doing anything at all. */
  enabled: boolean;
  /** Source boxes only: what decides when this channel is polled. */
  polled: string | null;
  /** Trigger boxes only. */
  trigger: GraphTrigger | null;
  /** Sort boxes only. */
  sort: GraphSort | null;
  /** What a plugin's augmentation is, when this is one. Null otherwise. */
  plugin: GraphPlugin | null;
  /** Group nodes only: how big the rectangle is. */
  size: { width: number; height: number } | null;
  /** Channel boxes that stand for a channel: what it does. */
  channel: GraphChannel | null;
  /** Empty source boxes: which kind of somewhere this one is for, and what
   *  to type into it. Null once it has a channel. */
  asks: GraphAsks | null;
  /** Deposit and Withdraw boxes: which repository, and how full it is. */
  store: GraphStore | null;
  /** Decay, Expire and Tag boxes: what this one marks what passes with. */
  stamp: GraphStamp | null;
  /** Augmentations: what this one is slotted under, and what it says. */
  piece: GraphPiece | null;
  /** Condition pieces: what this one narrows by, and how to ask for it. */
  condition: GraphCondition | null;
  /** Feed boxes: how it fills. */
  feed: GraphFeed | null;
}

/** A feed box's reading windows and caps. */
interface GraphFeed {
  /** When it may be read. Empty means always. */
  windows: string[];
  open: boolean;
  maxItems: number;
  maxPerRun: number;
  generic: boolean;
}

/** What a source box knows about its source. */
interface GraphChannel {
  /** What kind of somewhere it is, said the way a person would: "Reddit". */
  source: string;
  /** Only YouTube has Shorts, broadcasts and community posts to sort out. */
  youtube: boolean;
  /** Where it is actually polled. */
  feedUrl: string;
  /** Somewhere else the same feed can be read, when the first will not have
   *  us. Null when there is none, which is the usual case. */
  mirror: string | null;
  /** One worth trying, for the kinds where somebody is known to publish the
   *  same feed. Offered, never filled in: it is a service we do not run. */
  mirrorHint: string | null;
  takes: Record<string, boolean>;
  /** When it was last polled. When it next will be is the trigger's business. */
  checked: string | null;
  placed: number;
  pending: number;
}

/** One setting a plugin piece asks for. */
interface GraphPluginField {
  name: string;
  label: string;
  type: string;
  value: string;
  placeholder: string;
}

/** A plugin piece: the plugin, where it slots, and its settings. */
interface GraphPlugin {
  ref: string;
  /** The plugin this box needs, when it is not loaded. Null while it is. */
  missing: string | null;
  /** Which plugin it came from — "YouTube" — for the word above the title. */
  plugin: string;
  blurb: string;
  /** Which of the app's boxes it slots under: "filter" or "sort". */
  under: string;
  fields: GraphPluginField[];
}

/** A Sort box's key and direction, and the keys it could use. */
interface GraphSort {
  by: string;
  /** Biggest, longest or newest first. */
  desc: boolean;
  keys: GraphSortKey[];
}

/** One thing a batch can be ordered by, and what its two ends are called. */
interface GraphSortKey {
  name: string;
  label: string;
  first: string;
  last: string;
}

/** A pulse's gap as a person says it: a number and what it counts. */
interface GraphEvery {
  amount: number;
  unit: string;
  units: { name: string; label: string }[];
}

/** A trigger box's schedule, window and last firing. */
interface GraphTrigger {
  kind: "schedule" | "pulse";
  /** A pulse's gap, in minutes, and the same gap said in a larger unit. */
  everyMinutes: number | null;
  every: GraphEvery;
  /** A schedule's cron expression, read in UTC. */
  cron: string | null;
  /** How long a window it opens, when it is wired to a feed. */
  duration: number | null;
  /** Whether it is wired to a feed, and so opens one rather than setting one off. */
  opens: boolean;
  /** When that expression next comes round, as the server worked it out. */
  next: string | null;
  lastFired: string | null;
}

/** One wire between two boxes. */
interface GraphWireView {
  id: string;
  from: number;
  to: number;
  kind: GraphWireKind;
}

/** The whole canvas as the server sent it. */
interface GraphView {
  nodes: GraphNodeView[];
  wires: GraphWireView[];
  /** What is already watched, for a channel node to be pointed at. */
  sources: { id: number; title: string; kind: string }[];
}

/** A drag in progress — moving a box, or pulling a new wire out of one. */
interface GraphDrag {
  kind: "move" | "wire" | "pan" | "resize" | "pick";
  /** Which box is being dragged. Zero while panning: a pan holds no box. */
  nodeId: number;
  /** Which box was actually pressed. Different from `nodeId` when an
   *  piece was pressed: the assembly is dragged by its host, but a press
   *  that went nowhere is a click on the piece itself. */
  pressed: number;
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
  /** Where the node itself started, so a group's carried nodes move with it. */
  startX: number;
  startY: number;
  /** Moving a group: what it surrounds, and where each of them started. */
  carried: { node: GraphNodeView; x: number; y: number }[];
}

/** The page elements the canvas draws into. */
interface GraphParts {
  canvas: HTMLElement;
  /** Everything drawn, moved as one when the canvas is panned. */
  scene: HTMLElement;
  /** The groups, drawn under the wires: a group is a background. */
  groups: HTMLElement;
  layer: HTMLElement;
  wires: SVGSVGElement;
  drawer: HTMLElement | null;
  error: HTMLElement | null;
  verdict: HTMLElement | null;
  empty: HTMLElement | null;
}

/** Everything one canvas remembers between redraws: the graph, the selection, any drag. */
interface GraphState {
  parts: GraphParts;
  nodes: GraphNodeView[];
  wires: GraphWireView[];
  boxes: Map<number, HTMLElement>;
  /** The node whose panel is open. Only ever one: a panel is about a node. */
  selectedNode: number | null;
  /** Everything picked out, which may be several. Moved and removed together. */
  picked: Set<number>;
  selectedWire: string | null;
  drag: GraphDrag | null;
  ghost: SVGPathElement | null;
  /** What is already watched, for a channel node to be pointed at. */
  sources: { id: number; title: string; kind: string }[];
  /** What the run in flight has done to each box, while one is running. */
  run: Map<number, GraphMark>;
  /** Whether something is already asking the server where the run has got to. */
  watching: boolean;
  busy: boolean;
  /** Where the canvas has been panned to. There are no edges to stop at. */
  panX: number;
  panY: number;
  /** How far in the canvas is zoomed. 1 is life size. */
  zoom: number;
  /** A box being dragged out of the palette, before it exists. */
  dropping: GraphDropping | null;
  /** Which side of the open box is showing: what it does, or what it would do. */
  tab: "settings" | "test";
  /** The last trial, kept so a redraw does not throw the answer away. */
  trial: GraphTrial | null;
  /** What to do to put things back, most recent last. */
  undo: GraphUndo[];
}

/** How to put one action back.
 *
 *  Every change on this canvas is a request the server already accepts, so an
 *  undo is another one of those rather than a second way of changing things:
 *  a move back, a wire cut, a node deleted. Nothing here can do anything a
 *  person could not do by hand. */
interface GraphUndo {
  /** What it puts back, said in the line above the canvas. */
  says: string;
  run: () => Promise<void>;
}

/** One box's share of a trial. */
interface GraphShare {
  through: GraphJudged[];
  held: GraphJudged[];
}

/** What a run would do, as the trigger that was asked reported it. */
interface GraphTrial {
  /** The trigger it was asked of. */
  node: number;
  /** Every box it touched, and what each did, by node id. */
  boxes: Map<number, GraphShare>;
  /** True while the answer is still being worked out. */
  asking: boolean;
}

/** A palette row on its way to the canvas. */
interface GraphDropping {
  kind: string;
  /** Which of a plugin's augmentations this is, as "<plugin>:<name>". Empty
   *  for every kind the host knows by name. */
  which: string;
  /** Which box a plugin's augmentation slots under. Empty for the host's
   *  own kinds, which answer that from their kind alone. */
  under: string;
  pointerId: number;
  ghost: HTMLElement;
}
