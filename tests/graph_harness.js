// Runs the compiled canvas script against a stub DOM and reports what its
// decisions were, as JSON, for test_graph.py to assert on.
//
// The drawing needs a browser, but the judgements do not: what counts as a
// graph, where a wire runs, and what the verdict says after following an item.
// Those are the parts worth pinning down, and this gives them somewhere to run.
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const SCRIPT = path.join(__dirname, "..", "dealgo", "web", "static", "graph.js");

/** Barely a DOM: enough for the script to load and find no canvas. */
function stubDocument() {
  const nothing = { forEach() {} };
  return {
    addEventListener() {},
    body: { addEventListener() {} },
    querySelectorAll() { return nothing; },
    // Enough of an element for the drawing functions to build one.
    createElement(tag) {
      const made = {
        tag,
        className: "",
        textContent: "",
        style: {},
        dataset: {},
        children: [],
        classList: {
          names: new Set(),
          add(name) { this.names.add(name); },
          remove(name) { this.names.delete(name); },
          toggle(name, on) { if (on) this.names.add(name); else this.names.delete(name); },
        },
        setAttribute() {},
        appendChild(child) { made.children.push(child); return child; },
        querySelector() { return null; },
      };
      return made;
    },
  };
}

function loadGraph(context) {
  vm.runInContext(fs.readFileSync(SCRIPT, "utf8"), context);
}

async function main() {
  // `instanceof Element` is how the script tells an element from anything
  // else, so the stub has to be one as far as the check can tell.
  class Element {
    constructor(fields) {
      Object.assign(this, fields);
    }
  }
  const context = vm.createContext({ document: stubDocument(), window: {}, console, Element });
  loadGraph(context);

  const report = {};

  // htmx re-inserts the script on every swap, so it has to survive running
  // again in the same window. A top-level const would throw here.
  try {
    loadGraph(context);
    report.runsTwice = true;
  } catch (error) {
    report.runsTwice = String(error);
  }

  const asGraph = context.asGraph;
  report.readsAGraph = asGraph({
    nodes: [{ id: 1, kind: "source", title: "A", x: 5, y: 6, detail: "/channels/1", note: "takes videos", overrides: {} }],
    wires: [{ id: "link:1:2", from: 1, to: 2, kind: "link" }],
  });
  report.refusesAnError = asGraph({ error: "A box cannot feed itself." });
  report.dropsARubbishNode = asGraph({ nodes: [{ id: "one", kind: "source" }, null], wires: [] });
  report.readsTheError = context.asGraphError({ error: "A box cannot feed itself." });

  // A condition piece: one thing to fill in, and a sensible answer for
  // whatever the payload left out.
  report.readsACondition = context.asGraphCondition({
    label: "Longer than", blurb: "Holds anything shorter.", field: "duration",
    asks: "How long", under: "filter", value: "2", unit: "minutes",
    units: ["seconds", "minutes", "hours", 7], says: "longer than 2 minutes",
  });
  report.mendsAHalfCondition = context.asGraphCondition({ field: "nonsense" });

  // Which boxes a piece may be slotted under. The same answer the server
  // gives, so a drag only lights up somewhere it can actually land.
  report.slotsFor = {
    orderUnderSort: context.graphPieceGoesUnder("order", "sort"),
    orderUnderFilter: context.graphPieceGoesUnder("order", "filter"),
    wordsUnderFilter: context.graphPieceGoesUnder("has-words", "filter"),
    wordsUnderFeed: context.graphPieceGoesUnder("has-words", "feed"),
    ruleUnderPlugin: context.graphPieceGoesUnder("rule", "plugin"),
    timerUnderFeed: context.graphPieceGoesUnder("timer", "feed"),
    timerUnderFilter: context.graphPieceGoesUnder("timer", "filter"),
  };

  const curve = context.graphCurve(0, 0, 200, 100);
  report.curve = { d: curve, starts: curve.startsWith("M 0 0"), ends: curve.endsWith("200 100") };

  report.labels = ["trigger", "source", "filter", "feed"].map(context.graphKindLabel);

  // Zooming keeps whatever is under the pointer under the pointer. The maths
  // is the part worth pinning down; the transform it writes is not.
  const limits = context.graphZoomLimits();
  report.zoomLimits = limits;

  const scene = { style: {} };
  const canvas = {
    style: {},
    getBoundingClientRect: () => ({ left: 0, top: 0, width: 800, height: 600 }),
    querySelector: () => null,
  };
  const state = { parts: { scene, canvas }, panX: 0, panY: 0, zoom: 1 };

  // A point 300,200 into the drawing, with the pointer on it.
  const before = context.pointInGraph(state, { clientX: 300, clientY: 200 });
  context.zoomGraph(state, 2, 300, 200);
  const after = context.pointInGraph(state, { clientX: 300, clientY: 200 });
  report.zoomHoldsThePointer = { before, after, zoom: state.zoom };

  // And it stops rather than going on for ever in either direction.
  for (let i = 0; i < 40; i += 1) context.zoomGraph(state, 2, 0, 0);
  report.zoomedRightIn = state.zoom;
  for (let i = 0; i < 60; i += 1) context.zoomGraph(state, 0.5, 0, 0);
  report.zoomedRightOut = state.zoom;

  // What the server says a run is doing, read into what the canvas draws.
  const run = context.asGraphRun({
    running: true,
    stage: "polling",
    nodes: { "3": { state: "busy", count: 0 }, "7": { state: "done", count: 2 }, "9": null },
  });
  report.run = {
    running: run.running,
    stage: run.stage,
    marks: [...run.nodes.entries()],
  };
  report.runRefusesRubbish = context.asGraphRun("no") === null;

  // What a box says after it was polled. A channel that brought back nothing
  // has to say so: blank would look the same as one the run never reached.
  const badge = (mark) => {
    const added = [];
    const box = {
      querySelector: () => null,
      appendChild: (child) => added.push(child),
      classList: { names: new Set(), toggle(name, on) { if (on) this.names.add(name); }, remove() {} },
    };
    context.graphTally(box, mark);
    if (added.length === 0) return null;
    const deadEnd = box.classList.names.has("is-dead-end");
    return {
      text: added[0].textContent,
      muted: added[0].classList.names.has("is-empty"),
      end: added[0].classList.names.has("is-end"),
      deadEnd,
    };
  };
  const mark = (fields) => ({
    state: "done", count: 0, stopped: 0, ends: false, trouble: null, ...fields,
  });
  report.tallies = {
    found: badge(mark({ count: 3 })),
    empty: badge(mark({})),
    // Nothing got past it, and things arrived: this is where the flow stops.
    blocked: badge(mark({ ends: true, stopped: 4 })),
    // Nothing arrived and nothing left — a channel with no new uploads. Not
    // a dead end to be alarmed about: it is the usual state of a channel.
    barren: badge(mark({})),
    // A trigger that set nothing off: it never looked, so it cannot report
    // having found nothing.
    idle: badge(mark({ ends: true })),
    // It went and could not get in. Not a wiring fault, and it must not be
    // drawn as one.
    refused: badge(mark({ ends: true, trouble: "asked too often — it is rate limiting us" })),
    // A mark from somewhere that leaves the field out: it must not print
    // "undefined" on the canvas.
    oldShape: badge({ state: "done", count: 0, stopped: 0, ends: true }),
    working: badge(mark({ state: "busy" })),
    untouched: badge(undefined),
  };

  // The open panel follows its node wherever it has just been moved to — by
  // being dragged itself, or by the group or selection that carried it.
  const panelFollows = (selectedNode) => {
    const placed = { style: {} };
    const box = { offsetWidth: 212 };
    const state = {
      nodes: [{ id: 5, x: 300, y: 200, kind: "source" }],
      boxes: new Map([[5, box]]),
      selectedNode,
      parts: { layer: { querySelector: () => placed } },
    };
    context.keepGraphPopoverWithItsNode(state);
    return { left: placed.style.left ?? null, top: placed.style.top ?? null };
  };
  report.panelFollows = { itsNode: panelFollows(5), anotherNode: panelFollows(9) };

  // The two drawers share an edge, so only one of them is ever out.
  const drawers = () => {
    const palette = { hidden: true };
    const finder = { hidden: true };
    const button = { setAttribute: () => {} };
    const panel = {
      querySelector: (selector) => {
        if (selector.includes("finder-list")) return { textContent: "", appendChild: () => {} };
        if (selector.includes("graph-finder")) return finder;
        return button;
      },
    };
    const state = {
      parts: { drawer: palette, canvas: { closest: () => panel } },
      nodes: [],
    };
    context.toggleGraphPalette(state, true);
    const afterPalette = { palette: !palette.hidden, finder: !finder.hidden };
    context.toggleGraphFinder(state, true);
    const afterFinder = { palette: !palette.hidden, finder: !finder.hidden };
    return { afterPalette, afterFinder };
  };
  report.drawers = drawers();

  // Jumping to a group puts it in the middle of the view, whatever the canvas
  // is panned or zoomed to.
  const jumped = (zoom) => {
    const scene = { style: {} };
    const canvas = {
      style: {},
      getBoundingClientRect: () => ({ left: 0, top: 0, width: 800, height: 600 }),
      querySelector: () => null,
      closest: () => null,
    };
    const state = {
      parts: { scene, canvas, layer: { querySelectorAll: () => [], querySelector: () => null } },
      nodes: [], wires: [], boxes: new Map(), run: new Map(),
      panX: 0, panY: 0, zoom, picked: new Set(), selectedNode: 1, trial: null,
      undo: [], tab: "settings", selectedWire: null,
    };
    // renderGraph needs a DOM; the panning is the part worth checking.
    try {
      context.centreGraphOn(state, {
        id: 3, kind: "group", x: 1000, y: 800, size: { width: 400, height: 200 },
      });
    } catch {
      // The redraw needs a real page. The pan happened before it.
    }
    return { panX: Math.round(state.panX), panY: Math.round(state.panY),
             picked: [...state.picked] };
  };
  report.jumpTo = { lifeSize: jumped(1), zoomedIn: jumped(2) };

  // What moves when a node moves: a group takes what it surrounds, anything
  // else takes the rest of what is picked.
  const travels = (kind, picked, nodeId) => {
    const nodes = [
      { id: 1, kind: "source", x: 100, y: 100, size: null },
      { id: 2, kind: "feed", x: 200, y: 100, size: null },
      { id: 3, kind: "group", x: 0, y: 0, size: { width: 400, height: 400 } },
    ];
    const node = nodes.find((n) => n.id === nodeId);
    return context
      .graphTravelsWith({ nodes, picked: new Set(picked) }, { ...node, kind })
      .map((n) => n.id);
  };
  report.travelsWith = {
    aloneNode: travels("source", [1], 1),
    pickedPair: travels("source", [1, 2], 1),
    group: travels("group", [], 3),
    unpickedNode: travels("source", [2], 1),
  };

  // Undo is a stack of requests the server already accepts, so an undo can do
  // nothing a person could not do by hand.
  const undoState = { undo: [] };
  const ran = [];
  for (const says of ["the move", "the wire you drew"]) {
    context.rememberGraphUndo(undoState, says, async () => ran.push(says));
  }
  report.undoDepth = context.graphUndoDepth();
  report.undoStacked = undoState.undo.map((step) => step.says);

  // It never grows past its depth, however long somebody works.
  const deep = { undo: [] };
  for (let i = 0; i < context.graphUndoDepth() + 20; i += 1) {
    context.rememberGraphUndo(deep, `step ${i}`, async () => {});
  }
  report.undoCapped = {
    held: deep.undo.length,
    oldest: deep.undo[0].says,  // the earliest ones fall off, not the latest
  };

  // Ctrl+Z inside a text field is that field's own undo.
  const inField = new context.Element({
    closest: (selector) => (selector.includes("input") ? {} : null),
  });
  const onCanvas = new context.Element({ closest: () => null });
  report.undoTakesTheKey = {
    canvas: context.graphTakesTheKey(onCanvas),
    field: context.graphTakesTheKey(inField),
  };

  // What appeared is what an undo takes away.
  report.undoFinds = {
    node: context.graphNodeAdded([{ id: 1 }], [{ id: 1 }, { id: 2 }]),
    wire: context.graphWireAdded([{ id: "edge:1" }], [{ id: "edge:1" }, { id: "edge:2" }]),
    // Two at once is nobody's single action, so nothing is assumed.
    ambiguous: context.graphNodeAdded([], [{ id: 1 }, { id: 2 }]),
  };

  // Searching a list of sources: every word, in any order, part of a word
  // counting — the same as searching anywhere else here.
  const matches = (name, query) => context.graphMatches(name, query);
  report.searching = {
    empty: matches("Channel 5 with Andrew Callaghan", ""),
    partial: matches("Channel 5 with Andrew Callaghan", "andr"),
    anyOrder: matches("Channel 5 with Andrew Callaghan", "callaghan channel"),
    caseBlind: matches("saveitforparts", "SAVEIT"),
    missingWord: matches("Daniel Greene", "daniel jones"),
    spacesOnly: matches("Aaron Parnas", "   "),
  };

  // Removing a node only asks a question where something is at stake. Asking
  // "its history goes too" of a node with no history is a frightening
  // question about nothing — and a question people say no to.
  const warns = (node) => context.graphRemovalWarning(node);
  report.removalAsks = {
    watchedChannel: warns({ kind: "source", detail: "/channels/1", title: "A" }),
    emptyChannel: warns({ kind: "source", detail: null, title: "New channel" }),
    feed: warns({ kind: "feed", detail: "/feeds/1", title: "News" }),
    filter: warns({ kind: "filter", detail: null, title: "Trim" }),
  };

  // A group is drawn as a rectangle rather than a box, so it carries its own
  // class. Looking only for the box's meant a group could not be pressed at
  // all: not moved, not resized, not opened, and so not removed either.
  const pressedOn = (className, id) =>
    context.graphNodeIdFrom(
      new context.Element({
        closest: (selector) =>
          selector.includes(className) ? { dataset: { node: String(id) } } : null,
      }),
    );
  report.pressTargets = {
    node: pressedOn("graph-node", 4),
    group: pressedOn("graph-group-box", 9),
    neither: pressedOn("something-else", 1),
  };

  // The palette sits over the canvas rather than on it: pressing a fold in it
  // is not a press on the drawing underneath.
  const pressed = (className) => {
    let panned = false;
    const inPalette = className === "graph-palette";
    const target = new context.Element({
      closest: (selector) => (selector.includes(className) ? { dataset: {} } : null),
    });
    const state = {
      nodes: [], wires: [], boxes: new Map(), run: new Map(),
      parts: {
        canvas: {
          setPointerCapture: () => { panned = true; },
          getBoundingClientRect: () => ({ left: 0, top: 0 }),
          classList: { add: () => {}, remove: () => {} },
        },
      },
      panX: 0, panY: 0, zoom: 1, drag: null, selectedNode: null, selectedWire: null,
    };
    context.onGraphPointerDown(state, {
      button: 0, target, pointerId: 1, pointerType: "mouse",
      clientX: 10, clientY: 10, preventDefault: () => {},
    });
    void inPalette;
    return panned;
  };
  report.pressing = {
    palette: pressed("graph-palette"),
    openNode: pressed("graph-pop"),
    canvas: pressed("nothing-matches"),
  };

  // Opening a Test tab either runs a trial or shows the one that came through
  // this box. Getting that backwards asked the server to test a filter, which
  // is refused — and the refusal took the whole trial down with it.
  const trigger = { id: 3, kind: "trigger", trigger: { kind: "pulse" } };
  const filter = { id: 9, kind: "filter", trigger: null };
  const trial = { node: 3, boxes: new Map(), asking: false };
  report.tabRuns = {
    triggerWithNoTrial: context.graphTabNeedsRun(trigger, null, "test"),
    triggerWithItsOwn: context.graphTabNeedsRun(trigger, trial, "test"),
    triggerWithAnothers: context.graphTabNeedsRun({ ...trigger, id: 4 }, trial, "test"),
    filterShowingItsShare: context.graphTabNeedsRun(filter, trial, "test"),
    goingBackToSettings: context.graphTabNeedsRun(trigger, null, "settings"),
    aBoxThatIsGone: context.graphTabNeedsRun(undefined, trial, "test"),
  };

  // A trial lists the batch in the order it would arrive, so it is numbered.
  // A filter's two piles are not an order, so they are not.
  const listed = (numbered) => {
    const part = context.graphJudgedList(
      "Gets through",
      [
        { id: 1, title: "One", reason: null, marks: [] },
        { id: 2, title: "Two", reason: null, marks: ["“news”", "3 min"] },
      ],
      "through",
      numbered,
    );
    const list = part.children[1];
    return { tag: list.tag, className: list.className };
  };
  report.lists = { trial: listed(true), report: listed(false) };

  // What the boxes on the path would leave on an item, shown beside it: a
  // trial says what would happen, and these are as much of that as which
  // feed it lands in.
  report.judgedMarks = (() => {
    const part = context.graphJudgedList(
      "Gets through",
      [
        { id: 1, title: "Plain", reason: null, marks: [] },
        { id: 2, title: "Marked", reason: null, marks: ["“news”", "3 min · no pause"] },
      ],
      "through",
      true,
    );
    const rows = part.children[1].children;
    const marksOf = (row) => {
      const holder = row.children.find(
        (child) => child.className === "graph-sheet-marks",
      );
      return holder === undefined ? [] : holder.children.map((one) => one.textContent);
    };
    return { plain: marksOf(rows[0]), marked: marksOf(rows[1]) };
  })();

  // A trigger's box has two sides; every other box has one.
  const tabs = (node) => {
    const strip = context.graphPopTabs(node, "settings");
    return strip.children.map((child) => child.textContent);
  };
  report.popoverTabs = tabs({ id: 1, kind: "trigger" });

  // "Most first" means one thing for a duration and another for a date, so
  // the two ends are named after whatever is being sorted by.
  const sortKeys = [
    { name: "published", label: "When it went up", first: "Newest first", last: "Oldest first" },
    { name: "duration", label: "How long it is", first: "Longest first", last: "Shortest first" },
  ];
  const ends = (by) => {
    const option = () => ({ textContent: "" });
    const way = { options: [option(), option()] };
    context.nameGraphSortEnds(way, { by: "published", desc: true, keys: sortKeys }, by);
    return way.options.map((o) => o.textContent);
  };
  report.sortEnds = { published: ends("published"), duration: ends("duration"),
                      unknown: ends("nothing") };

  // What each side of a box says it takes or gives. Two things travel these
  // wires — a signal to run, and the content being collected — and a port has
  // to say which.
  report.ports = {
    triggerOut: context.graphPortWords("trigger", "out"),
    channelIn: context.graphPortWords("source", "in"),
    channelOut: context.graphPortWords("source", "out"),
    filterOut: context.graphPortWords("filter", "out"),
    feedIn: context.graphPortWords("feed", "in"),
  };

  // Which wires the run lights. The trigger somebody pressed is marked busy,
  // and the wire out of it is what shows the run leaving it.
  const asked = [];
  const lit = new Set();
  const paths = (selector) => {
    asked.push(selector);
    const id = /data-line="([^"]+)"/.exec(selector);
    return [{ classList: { add: () => id && lit.add(id[1]), remove: () => {} } }];
  };
  const wireState = {
    parts: { wires: { querySelectorAll: paths } },
    wires: [
      { id: "edge:1", from: 10, to: 20, kind: "edge" },   // trigger -> channel
      { id: "link:20:30", from: 20, to: 30, kind: "link" }, // channel -> feed
      { id: "edge:9", from: 40, to: 50, kind: "edge" },   // nothing to do with it
    ],
    run: new Map([[10, { state: "busy", count: 0 }]]),
  };
  context.paintGraphRunWires(wireState);
  report.wiresLitByTheTrigger = [...lit];
  report.wireSelectors = asked;

  // The word above a box's title. A source box says where it watches, which
  // is the thing somebody chose when they dragged it out — "Channel" said the
  // same for a subreddit and a YouTube channel, and so said nothing.
  const heads = (node) => context.graphTriggerLabel(node);
  report.boxHeadings = {
    reddit: heads({ kind: "source", trigger: null, plugin: null, asks: null,
                    channel: { source: "Reddit" } }),
    youtube: heads({ kind: "source", trigger: null, plugin: null, asks: null,
                     channel: { source: "YouTube" } }),
    emptyReddit: heads({ kind: "source", trigger: null, plugin: null, channel: null,
                         asks: { kind: "reddit", source: "Reddit", label: "Subreddit" } }),
    sourceWithNothingKnown: heads({ kind: "source", trigger: null, plugin: null,
                                    channel: null, asks: null }),
    pluginBox: heads({ kind: "plugin", trigger: null, channel: null, asks: null,
                       plugin: { plugin: "YouTube" } }),
    feed: heads({ kind: "feed", trigger: null, plugin: null, channel: null, asks: null }),
    pulse: heads({ kind: "trigger", plugin: null, channel: null, asks: null,
                   trigger: { kind: "pulse" } }),
  };

  // A jigsaw piece is drawn under the box it is slotted into, stacked from
  // the box's own coordinates. `offsetTop` is measured against whichever
  // ancestor happens to be positioned, so a piece placed from it lands
  // wherever that ancestor is rather than under its host.
  report.slotting = slottedUnderTheirHost();

  // Where a piece has to be dropped to go in. Nobody aims at a one-pixel
  // seam, so the slot reaches well below the box — and is drawn while you
  // drag, so the distance is never a guess.
  report.snapping = await droppingAPieceNearABox();

  // Anything slotted under a box travels with it. A piece has no position of
  // its own worth keeping — it is drawn from its host's — so a box that
  // moved and left its pieces behind was a box drawn without them.
  report.following = piecesFollowTheirHost();

  // Pressing a piece opens the piece, even though dragging it moves the
  // assembly it is part of. Picking the dragged box instead meant a slotted
  // piece could not be opened at all — the feed opened instead.
  report.pressingAPiece = (() => {
    const picked = [];
    const state = {
      nodes: [
        { id: 7, kind: "feed", x: 0, y: 0, piece: null },
        { id: 8, kind: "timer", x: 0, y: 0, piece: { under: 7, minutes: 30, cron: "" } },
      ],
      picked: new Set(), boxes: new Map([[8, { classList: { remove() {} } }]]),
      drag: { kind: "move", nodeId: 7, pressed: 8, pointerId: 1, moved: false },
      parts: {
        canvas: { hasPointerCapture: () => false, releasePointerCapture() {},
                  classList: { remove() {} } },
        layer: { querySelector: () => null },
      },
      selectedNode: null, tab: "settings",
    };
    context.pickGraphNode = (_state, id) => picked.push(id);
    context.onGraphPointerUp(state, { pointerId: 1 });
    return { opened: picked[0] ?? null };
  })();

  report.removing = await removingWithDialogsBlocked();
  process.stdout.write(JSON.stringify(report));
}

/** Press Remove in a browser that has been told to stop this page making
 *  dialogs.
 *
 *  `window.confirm` answers "no" in that state and says nothing about it, so
 *  a Remove button that asked with it did nothing at all: no question, no
 *  request, no error, for the rest of the tab's life. Everything else in the
 *  panel kept working, because nothing else asked first. */
async function removingWithDialogsBlocked() {
  const nothing = { forEach() {} };
  const make = (tag) => ({
    tag, className: "", textContent: "", style: {}, dataset: {}, children: [],
    classList: { names: new Set(), add() {}, remove() {}, toggle() {} },
    setAttribute() {}, removeAttribute() {}, addEventListener() {},
    removeEventListener() {}, appendChild(c) { this.children.push(c); return c; },
    querySelector() { return null; }, querySelectorAll() { return nothing; },
  });
  class Element {
    constructor(fields) { Object.assign(this, fields); }
  }

  const sent = [];
  const yes = { onclick: null };
  const what = { textContent: "" };
  const dialog = {
    open: false,
    showModal() { this.open = true; },
    close() { this.open = false; },
    setAttribute() {}, removeAttribute() {},
    addEventListener() {}, removeEventListener() {},
    querySelector: (selector) => (selector.includes("what") ? what : null),
    querySelectorAll: (selector) => ({
      forEach(run) { run(selector.includes("yes") ? yes : { onclick: null }); },
    }),
  };
  const panel = { querySelector: (s) => (s.includes("graph-sure") ? dialog : null) };
  const canvas = Object.assign(make("div"), { closest: () => panel });

  const context = vm.createContext({
    document: {
      addEventListener() {},
      body: { addEventListener() {}, classList: { toggle() {} } },
      querySelectorAll() { return nothing; },
      createElement: make,
      createTextNode: (text) => ({ tag: "#text", textContent: text, children: [] }),
    },
    window: { confirm: () => false },  // the browser is refusing to ask
    console,
    Element,
    URLSearchParams,
    fetch: async (url) => {
      sent.push(String(url));
      return { ok: true, json: async () => ({ nodes: [], wires: [], sources: [] }) };
    },
  });
  loadGraph(context);

  const state = {
    nodes: [], wires: [], sources: [], picked: new Set(), busy: false,
    selectedNode: 1, selectedWire: null, tab: "settings",
    parts: { canvas, layer: make("div"), error: make("p"), verdict: make("p") },
    boxes: new Map(), marks: new Map(),
  };

  const done = context.removeGraphNode(state, "7", "Stop watching A Channel?");
  if (yes.onclick) yes.onclick();
  await done;
  return { asked: what.textContent, requests: sent };
}

/** Drop a Timer at several distances from a feed and say which ones go in. */
async function droppingAPieceNearABox() {
  const nothing = { forEach() {} };
  const make = (tag) => ({
    tag, className: "", textContent: "", style: {}, dataset: {}, children: [],
    hidden: false, offsetTop: 0, offsetLeft: 0, offsetHeight: 60, offsetWidth: 212,
    tabIndex: 0,
    classList: {
      names: new Set(),
      add(name) { this.names.add(name); },
      remove(name) { this.names.delete(name); },
      toggle(name, on) { if (on) this.names.add(name); else this.names.delete(name); },
      contains(name) { return this.names.has(name); },
    },
    setAttribute() {}, removeAttribute() {}, addEventListener() {},
    appendChild(child) { this.children.push(child); return child; },
    remove() {},
    querySelector(selector) {
      const want = selector.replace(".", "");
      return this.children.find(
        (child) => typeof child.className === "string" && child.className.includes(want),
      ) ?? null;
    },
    querySelectorAll() { return nothing; },
  });
  class Element {
    constructor(fields) { Object.assign(this, fields); }
  }

  const asked = [];
  const context = vm.createContext({
    document: {
      addEventListener() {},
      body: { addEventListener() {}, classList: { toggle() {} } },
      querySelectorAll() { return nothing; },
      createElement: make,
      createElementNS: (ns, tag) => make(tag),
      createTextNode: (text) => ({ tag: "#text", textContent: text, children: [] }),
      // Dropped on empty canvas every time: what is being measured is the
      // reach of the slot, not whether the pointer was over the box.
      elementFromPoint: () => null,
    },
    window: {}, console, Element, URLSearchParams,
    fetch: async (url, options) => {
      asked.push(String(options && options.body ? options.body : ""));
      return { ok: true, json: async () => ({ nodes: [], wires: [], sources: [] }) };
    },
  });
  loadGraph(context);

  const canvas = Object.assign(make("div"), {
    getBoundingClientRect: () => ({
      left: 0, top: 0, right: 1200, bottom: 900, width: 1200, height: 900,
    }),
    closest: () => null,
  });
  const feed = {
    id: 7, kind: "feed", x: 400, y: 100, title: "New feed", note: "generic",
    enabled: true, piece: null, trigger: null, sort: null, plugin: null,
    channel: null, asks: null, store: null, feed: null, size: null,
    overrides: {}, detail: null, polled: null,
  };
  const state = {
    nodes: [feed], wires: [], sources: [], picked: new Set(), busy: false,
    selectedNode: null, selectedWire: null, tab: "settings",
    parts: {
      canvas, drawer: make("div"), layer: make("div"), groups: make("div"),
      empty: null, wires: make("div"), error: make("p"), verdict: make("p"),
    },
    boxes: new Map(), marks: new Map(), run: new Map(),
    panX: 0, panY: 0, zoom: 1, dropping: null,
  };

  // The feed box runs y=100 to y=178.
  const drops = {
    onTheBox: [506, 140],
    justUnder: [506, 190],
    wellBelowAndAside: [460, 238],
    farAway: [900, 600],
  };
  const went = {};
  for (const [what, [x, y]] of Object.entries(drops)) {
    asked.length = 0;
    state.nodes = [feed];
    state.boxes = new Map([
      [7, Object.assign(make("div"), { offsetHeight: 78, offsetWidth: 212 })],
    ]);
    state.busy = false;
    state.dropping = { kind: "timer", which: "", pointerId: 1, ghost: make("div") };
    context.finishGraphDrop(state, { pointerId: 1, clientX: x, clientY: y });
    await new Promise((go) => setTimeout(go, 5));
    went[what] = (asked[0] ?? "").includes("attach_to=7");
  }
  return went;
}

/** Drag a feed with two pieces slotted under it, and say where they end up. */
function piecesFollowTheirHost() {
  const nothing = { forEach() {} };
  const make = (tag) => ({
    tag, className: "", textContent: "", style: {}, dataset: {}, children: [],
    hidden: false, offsetTop: 0, offsetLeft: 0, offsetHeight: 60, offsetWidth: 212,
    tabIndex: 0,
    classList: {
      names: new Set(),
      add(name) { this.names.add(name); },
      remove(name) { this.names.delete(name); },
      toggle(name, on) { if (on) this.names.add(name); else this.names.delete(name); },
      contains(name) { return this.names.has(name); },
    },
    setAttribute() {}, removeAttribute() {}, addEventListener() {},
    appendChild(child) { this.children.push(child); return child; },
    remove() {},
    querySelector() { return null; }, querySelectorAll() { return nothing; },
  });
  class Element {
    constructor(fields) { Object.assign(this, fields); }
  }
  const context = vm.createContext({
    document: {
      addEventListener() {},
      body: { addEventListener() {}, classList: { toggle() {} } },
      querySelectorAll() { return nothing; },
      createElement: make,
      createElementNS: (ns, tag) => make(tag),
      createTextNode: (text) => ({ tag: "#text", textContent: text, children: [] }),
    },
    window: {}, console, Element, URLSearchParams,
    fetch: async () => ({ ok: true, json: async () => ({}) }),
  });
  loadGraph(context);

  const plain = {
    title: "", note: "", enabled: true, piece: null, trigger: null, sort: null,
    plugin: null, channel: null, asks: null, store: null, feed: null, size: null,
    overrides: {}, detail: null, polled: null,
  };
  const feed = { ...plain, id: 7, kind: "feed", x: 130, y: 88 };
  const timer = {
    ...plain, id: 8, kind: "timer", x: 0, y: 0,
    piece: { under: 7, minutes: 30, cron: "" },
  };
  const reset = {
    ...plain, id: 9, kind: "reset", x: 0, y: 0,
    piece: { under: 8, minutes: 30, cron: "0 9 * * *" },
  };
  const canvas = Object.assign(make("div"), {
    getBoundingClientRect: () => ({ left: 0, top: 0, right: 1200, bottom: 900 }),
    hasPointerCapture: () => false,
    releasePointerCapture() {}, setPointerCapture() {},
  });
  const state = {
    nodes: [feed, timer, reset], wires: [], sources: [], picked: new Set(),
    busy: false, selectedNode: null, selectedWire: null, tab: "settings",
    parts: {
      canvas, drawer: make("div"), layer: make("div"), groups: make("div"),
      empty: null, wires: make("div"), error: make("p"), verdict: make("p"),
    },
    boxes: new Map(), marks: new Map(), run: new Map(),
    panX: 0, panY: 0, zoom: 1, drag: null, dropping: null, ghost: null,
  };
  context.drawGraphNodes(state);
  const at = (id) => {
    const box = state.boxes.get(id);
    return { left: box.style.left, top: box.style.top };
  };
  const before = { feed: at(7), timer: at(8), reset: at(9) };

  // A move drag of the feed, three hundred right and two hundred down.
  state.drag = {
    kind: "move", pointerId: 1, nodeId: 7, grabX: 70, grabY: 32,
    startX: 130, startY: 88, fromX: 200, fromY: 120, moved: true, carried: [],
  };
  context.onGraphPointerMove(state, { pointerId: 1, clientX: 500, clientY: 320 });

  return { before, after: { feed: at(7), timer: at(8), reset: at(9) } };
}

/** Draw a feed with two pieces chained under it, and say where they land. */
function slottedUnderTheirHost() {
  const nothing = { forEach() {} };
  const make = (tag) => ({
    tag, className: "", textContent: "", style: {}, dataset: {}, children: [],
    offsetTop: 0, offsetLeft: 0, offsetHeight: 60, offsetWidth: 200, tabIndex: 0,
    classList: {
      names: new Set(),
      add(name) { this.names.add(name); },
      remove(name) { this.names.delete(name); },
      toggle(name, on) { if (on) this.names.add(name); else this.names.delete(name); },
    },
    setAttribute() {}, removeAttribute() {}, addEventListener() {},
    appendChild(child) { this.children.push(child); return child; },
    querySelector() { return null; }, querySelectorAll() { return nothing; },
  });
  class Element {
    constructor(fields) { Object.assign(this, fields); }
  }
  const context = vm.createContext({
    document: {
      addEventListener() {},
      body: { addEventListener() {}, classList: { toggle() {} } },
      querySelectorAll() { return nothing; },
      createElement: make,
      createElementNS: (ns, tag) => make(tag),
      createTextNode: (text) => ({ tag: "#text", textContent: text, children: [] }),
    },
    window: {}, console, Element, URLSearchParams,
  });
  loadGraph(context);

  const plain = {
    title: "", note: "", enabled: true, piece: null, trigger: null, sort: null,
    plugin: null, channel: null, asks: null, store: null, feed: null, size: null,
    overrides: {}, detail: null, polled: null,
  };
  const feed = { ...plain, id: 7, kind: "feed", x: 400, y: 100 };
  const timer = {
    ...plain, id: 8, kind: "timer", x: 0, y: 0,
    piece: { under: 7, minutes: 30, cron: "" },
  };
  const reset = {
    ...plain, id: 9, kind: "reset", x: 0, y: 0,
    piece: { under: 8, minutes: 30, cron: "0 9 * * *" },
  };

  const state = {
    nodes: [feed, timer, reset], wires: [], sources: [], picked: new Set(),
    busy: false, selectedNode: null, selectedWire: null, tab: "settings",
    parts: {
      canvas: make("div"), layer: make("div"), groups: make("div"), empty: null,
    },
    boxes: new Map(), marks: new Map(), run: new Map(),
  };
  context.drawGraphNodes(state);

  const where = (id) => {
    const box = state.boxes.get(id);
    return { left: box.style.left, top: box.style.top, piece: box.classList.names.has("is-piece") };
  };
  // And the feed has one input now, not two: when it may be read is slotted
  // under it rather than arriving along a wire.
  const ports = state.boxes.get(7).children.filter(
    (child) => typeof child.className === "string" && child.className.includes("graph-port"),
  );
  return {
    feed: where(7),
    timer: where(8),
    reset: where(9),
    feedPorts: ports.map((one) => one.className),
  };
}

main();
