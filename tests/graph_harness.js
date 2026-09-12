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
  };
}

function loadGraph(context) {
  vm.runInContext(fs.readFileSync(SCRIPT, "utf8"), context);
}

function main() {
  const context = vm.createContext({ document: stubDocument(), window: {}, console });
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

  // A schedule is stored in UTC and typed on the viewer's clock. Whatever the
  // machine's timezone, going out and back has to land where it started.
  const roundTrip = [0, 7 * 60 + 30, 9 * 60, 13 * 60 + 45, 23 * 60 + 59];
  report.clockRoundTrip = roundTrip.map((minute) =>
    context.graphUtcMinute(context.graphLocalTime(minute)),
  );
  report.clockRoundTripWanted = roundTrip;
  report.clockReads = context.graphLocalTime(9 * 60).length;

  const verdict = context.graphVerdictFor;
  report.landedSome = verdict({
    title: "A clip",
    steps: [
      { nodes: [1, 2], wires: [], accepted: true, reason: null },
      { nodes: [1, 3], wires: [], accepted: false, reason: "Short (30s)" },
    ],
  });
  report.landedNowhere = verdict({ title: "A clip", steps: [] });
  // The same refusal down two paths is said once.
  report.saysEachReasonOnce = verdict({
    title: "A clip",
    steps: [
      { nodes: [1, 2], wires: [], accepted: false, reason: "Short (30s)" },
      { nodes: [1, 3], wires: [], accepted: false, reason: "Short (30s)" },
    ],
  });

  process.stdout.write(JSON.stringify(report));
}

main();
