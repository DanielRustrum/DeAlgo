// Reading what the server said: a checked shape for everything the canvas draws.
//
// The server's JSON is the one thing nothing can check at compile time, so it is
// read here, once, into types — and the only casts in the canvas are in this file.
//
// Part of the Configuration canvas; see main.ts.

/** A plain JSON object, or null for anything else. */
function asGraphRecord(value: unknown): Record<string, unknown> | null {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

/** A kind the canvas knows how to draw, or null. */
function asGraphNodeKind(value: unknown): GraphNodeKind | null {
  if (
    value === "trigger" ||
    value === "source" ||
    value === "filter" ||
    value === "sort" ||
    value === "feed" ||
    value === "group" ||
    value === "pamphlet" ||
    value === "format" ||
    value === "transform" ||
    value === "count" ||
    value === "leaflet-feed" ||
    value === "leaflet-chart" ||
    value === "leaflet-text" ||
    value === "leaflet-link" ||
    value === "deposit" ||
    value === "withdraw" ||
    value === "timer" ||
    value === "reset" ||
    value === "alive" ||
    value === "lock" ||
    value === "after-watch" ||
    value === "decay" ||
    value === "expire" ||
    value === "tag" ||
    value === "has-words" ||
    value === "lacks-words" ||
    value === "longer-than" ||
    value === "shorter-than" ||
    value === "carrying" ||
    value === "lacks-tag" ||
    value === "at-most" ||
    value === "order" ||
    value === "rule"
  ) {
    return value;
  }
  return null;
}

/** One box or piece from the server, checked field by field; null if it has no id or kind. */
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
    enabled: raw["enabled"] !== false,
    polled: typeof polled === "string" ? polled : null,
    trigger: asGraphTrigger(raw["trigger"]),
    sort: asGraphSort(raw["sort"]),
    size: asGraphSize(raw["size"]),
    locked: raw["locked"] === true,
    imported: asGraphImported(raw["imported"]),
    channel: asGraphChannel(raw["channel"]),
    asks: asGraphAsks(raw["asks"]),
    store: asGraphStore(raw["store"]),
    stamp: asGraphStamp(raw["stamp"]),
    piece: asGraphPiece(raw["piece"]),
    condition: asGraphCondition(raw["condition"]),
    plugin: asGraphPlugin(raw["plugin"]),
    feed: asGraphFeed(raw["feed"]),
    leaflet: asGraphLeaflet(raw["leaflet"]),
    pamphlet: asGraphPamphlet(raw["pamphlet"]),
    format: asGraphFormat(raw["format"]),
    dataOnly: raw["dataOnly"] === true,
  };
}

/** What an empty source box asks to be told. */
function asGraphAsks(value: unknown): GraphAsks | null {
  const raw = asGraphRecord(value);
  if (raw === null) return null;
  return {
    kind: typeof raw["kind"] === "string" ? raw["kind"] : "",
    label: typeof raw["label"] === "string" ? raw["label"] : "",
    source: typeof raw["source"] === "string" ? raw["source"] : "",
    example: typeof raw["example"] === "string" ? raw["example"] : "",
    known: raw["known"] === true,
    colour: typeof raw["colour"] === "string" ? raw["colour"] : "",
  };
}

/** A piece's slot and settings. */
function asGraphPiece(value: unknown): GraphPiece | null {
  const raw = asGraphRecord(value);
  if (raw === null) return null;
  const under = raw["under"];
  return {
    under: typeof under === "number" ? under : null,
    side: raw["side"] === "beside" ? "beside" : "below",
    minutes: typeof raw["minutes"] === "number" ? raw["minutes"] : 30,
    cron: typeof raw["cron"] === "string" ? raw["cron"] : "",
    from: typeof raw["from"] === "string" ? raw["from"] : "",
    to: typeof raw["to"] === "string" ? raw["to"] : "",
    every: asGraphEvery(raw["every"]),
    hosts: typeof raw["hosts"] === "string" ? raw["hosts"] : "",
  };
}

/** A condition piece's value and how its field is asked for. */
function asGraphCondition(value: unknown): GraphCondition | null {
  const raw = asGraphRecord(value);
  if (raw === null) return null;
  const units = raw["units"];
  const field = raw["field"];
  return {
    label: typeof raw["label"] === "string" ? raw["label"] : "",
    blurb: typeof raw["blurb"] === "string" ? raw["blurb"] : "",
    field:
      field === "duration" || field === "number" || field === "order" || field === "tags"
        ? field
        : "text",
    asks: typeof raw["asks"] === "string" ? raw["asks"] : "",
    under: raw["under"] === "sort" ? "sort" : "filter",
    value: typeof raw["value"] === "string" ? raw["value"] : "",
    unit: typeof raw["unit"] === "string" ? raw["unit"] : "minutes",
    units: Array.isArray(units)
      ? units.filter((one): one is string => typeof one === "string")
      : [],
    says: typeof raw["says"] === "string" ? raw["says"] : "",
    choices: Array.isArray(raw["choices"])
      ? raw["choices"].filter((one): one is string => typeof one === "string")
      : [],
  };
}

/** What a Tag box marks items with. */
function asGraphStamp(value: unknown): GraphStamp | null {
  const raw = asGraphRecord(value);
  if (raw === null) return null;
  return { marks: typeof raw["marks"] === "string" ? raw["marks"] : "" };
}

/** A repository end's name, how much it holds, and how much it takes. */
function asGraphStore(value: unknown): GraphStore | null {
  const raw = asGraphRecord(value);
  if (raw === null) return null;
  return {
    name: typeof raw["name"] === "string" ? raw["name"] : "",
    waiting: typeof raw["waiting"] === "number" ? raw["waiting"] : 0,
    takes: typeof raw["takes"] === "number" ? raw["takes"] : 0,
    pulls: raw["pulls"] === true,
  };
}

/** A feed box's reading windows and caps. */
function asGraphFeed(value: unknown): GraphFeed | null {
  const raw = asGraphRecord(value);
  if (raw === null) return null;
  const windows = raw["windows"];
  return {
    windows: Array.isArray(windows)
      ? windows.filter((entry): entry is string => typeof entry === "string")
      : [],
    open: raw["open"] !== false,
    maxItems: typeof raw["max_items"] === "number" ? raw["max_items"] : 0,
    maxPerRun: typeof raw["max_per_run"] === "number" ? raw["max_per_run"] : 0,
    generic: raw["generic"] === true,
  };
}

/** What a source box shows about its source. */
function asGraphChannel(value: unknown): GraphChannel | null {
  const raw = asGraphRecord(value);
  if (raw === null) return null;

  const takes: GraphTake[] = [];
  const given = raw["takes"];
  if (Array.isArray(given)) {
    for (const one of given) {
      const take = asGraphRecord(one);
      if (take === null || typeof take["name"] !== "string") continue;
      takes.push({
        name: take["name"],
        label: typeof take["label"] === "string" ? take["label"] : take["name"],
        on: take["on"] === true,
      });
    }
  }

  const checked = raw["checked"];
  return {
    source: typeof raw["source"] === "string" ? raw["source"] : "",
    colour: typeof raw["colour"] === "string" ? raw["colour"] : "",
    mirrors: raw["mirrors"] !== false,
    feedUrl: typeof raw["feed_url"] === "string" ? raw["feed_url"] : "",
    mirror: typeof raw["mirror"] === "string" ? raw["mirror"] : null,
    mirrorHint: typeof raw["mirror_hint"] === "string" ? raw["mirror_hint"] : null,
    takes,
    checked: typeof checked === "string" ? checked : null,
    placed: typeof raw["placed"] === "number" ? raw["placed"] : 0,
    pending: typeof raw["pending"] === "number" ? raw["pending"] : 0,
    rest: asGraphRest(raw["rest"]),
  };
}

/** A REST source's mapping, as its box shows it. */
function asGraphRest(value: unknown): GraphRest | null {
  const raw = asGraphRecord(value);
  if (raw === null) return null;
  const paths: Record<string, string> = {};
  for (const name of graphRestFieldNames()) {
    const said = raw[name];
    paths[name] = typeof said === "string" ? said : "";
  }
  return {
    paths,
    headerName: typeof raw["header_name"] === "string" ? raw["header_name"] : "",
    hasKey: raw["has_key"] === true,
    error: typeof raw["error"] === "string" ? raw["error"] : "",
  };
}

/** A group's size, defaulting to the server's default. */
function asGraphSize(value: unknown): { width: number; height: number } | null {
  const raw = asGraphRecord(value);
  if (raw === null) return null;
  return {
    width: typeof raw["width"] === "number" ? raw["width"] : 520,
    height: typeof raw["height"] === "number" ? raw["height"] : 300,
  };
}

/** Where a group was loaded from, when it was. */
function asGraphImported(value: unknown): { from: string; at: string | null } | null {
  const raw = asGraphRecord(value);
  if (raw === null) return null;
  return {
    from: typeof raw["from"] === "string" ? raw["from"] : "",
    at: typeof raw["at"] === "string" ? raw["at"] : null,
  };
}

/** A plugin piece: which plugin, where it slots, and its settings fields. */
function asGraphPlugin(value: unknown): GraphPlugin | null {
  const raw = asGraphRecord(value);
  if (raw === null) return null;
  const missing = raw["missing"];
  const fields: GraphPluginField[] = [];
  for (const entry of Array.isArray(raw["fields"]) ? raw["fields"] : []) {
    const one = asGraphRecord(entry);
    if (one === null) continue;
    fields.push({
      name: typeof one["name"] === "string" ? one["name"] : "",
      label: typeof one["label"] === "string" ? one["label"] : "",
      type: one["type"] === "number" ? "number" : "text",
      value: typeof one["value"] === "string" ? one["value"] : "",
      placeholder: typeof one["placeholder"] === "string" ? one["placeholder"] : "",
    });
  }
  return {
    ref: typeof raw["ref"] === "string" ? raw["ref"] : "",
    missing: typeof missing === "string" ? missing : null,
    plugin: typeof raw["plugin"] === "string" ? raw["plugin"] : "",
    blurb: typeof raw["blurb"] === "string" ? raw["blurb"] : "",
    under: raw["under"] === "sort" ? "sort" : "filter",
    fields: fields.filter((one): boolean => one.name !== ""),
  };
}

/** What a Sort orders by, and the keys it offers. */
function asGraphSort(value: unknown): GraphSort | null {
  const raw = asGraphRecord(value);
  if (raw === null) return null;

  const keys: GraphSortKey[] = [];
  const offered = raw["keys"];
  if (Array.isArray(offered)) {
    for (const entry of offered) {
      const key = asGraphRecord(entry);
      if (key === null || typeof key["name"] !== "string") continue;
      keys.push({
        name: key["name"],
        label: typeof key["label"] === "string" ? key["label"] : key["name"],
        first: typeof key["first"] === "string" ? key["first"] : "Most first",
        last: typeof key["last"] === "string" ? key["last"] : "Least first",
      });
    }
  }
  return {
    by: typeof raw["by"] === "string" ? raw["by"] : "published",
    desc: raw["desc"] !== false,
    keys,
  };
}

/** An amount of time as an amount, a unit, and the units on offer. */
function asGraphEvery(value: unknown): GraphEvery {
  const raw = asGraphRecord(value);
  const units: { name: string; label: string }[] = [];
  const offered = raw === null ? null : raw["units"];
  if (Array.isArray(offered)) {
    for (const entry of offered) {
      const unit = asGraphRecord(entry);
      if (unit === null || typeof unit["name"] !== "string") continue;
      units.push({
        name: unit["name"],
        label: typeof unit["label"] === "string" ? unit["label"] : unit["name"],
      });
    }
  }
  return {
    amount: typeof raw?.["amount"] === "number" ? raw["amount"] : 60,
    unit: typeof raw?.["unit"] === "string" ? raw["unit"] : "minutes",
    units,
  };
}

/** A trigger's schedule, window and last firing. */
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
    every: asGraphEvery(raw["every"]),
    cron: typeof cron === "string" ? cron : null,
    duration: typeof raw["duration"] === "number" ? raw["duration"] : null,
    opens: raw["opens"] === true,
    next: typeof next === "string" ? next : null,
    lastFired: typeof fired === "string" ? fired : null,
  };
}

/** One wire; null if any end is missing. */
function asGraphWire(value: unknown): GraphWireView | null {
  const raw = asGraphRecord(value);
  if (raw === null) return null;
  const id = raw["id"];
  const from = raw["from"];
  const to = raw["to"];
  if (typeof id !== "string" || typeof from !== "number" || typeof to !== "number") return null;
  const kind = raw["kind"] === "page" || raw["kind"] === "data" ? raw["kind"] : "edge";
  return { id, from, to, kind };
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
  const watched: { id: number; title: string; kind: string }[] = [];
  const offered = raw["sources"];
  if (Array.isArray(offered)) {
    for (const entry of offered) {
      const source = asGraphRecord(entry);
      if (source === null || typeof source["id"] !== "number") continue;
      watched.push({
        id: source["id"],
        title: typeof source["title"] === "string" ? source["title"] : "",
        kind: typeof source["kind"] === "string" ? source["kind"] : "",
      });
    }
  }
  return { nodes: readNodes, wires: readWires, sources: watched };
}

/** The error message in a refusal, or null. */
function asGraphError(value: unknown): string | null {
  const raw = asGraphRecord(value);
  const message = raw === null ? null : raw["error"];
  return typeof message === "string" ? message : null;
}
