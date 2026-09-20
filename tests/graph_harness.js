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

  // Only what a filter actually decides is kept, so "inherit" stays visible.
  report.keepsOnlyRealOverrides = context.asGraphOverrides({
    skip_shorts: true, min_duration_sec: 600, title_include: null, nested: { no: 1 },
  });

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

  // A wire from a trigger into a feed is about when that feed may be read, so
  // it arrives at the second input rather than the first.
  const entering = (fromKind, toKind) => {
    const nodes = [
      { id: 1, kind: fromKind },
      { id: 2, kind: toKind },
    ];
    return context.graphWireEnters({ nodes }, { id: "edge:1", from: 1, to: 2 });
  };
  report.wireEnters = {
    triggerToFeed: entering("trigger", "feed"),
    triggerToChannel: entering("trigger", "source"),
    filterToFeed: entering("filter", "feed"),
    channelToFeed: entering("source", "feed"),
  };

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
      [{ id: 1, title: "One", reason: null }, { id: 2, title: "Two", reason: null }],
      "through",
      numbered,
    );
    const list = part.children[1];
    return { tag: list.tag, className: list.className };
  };
  report.lists = { trial: listed(true), report: listed(false) };

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

main();
