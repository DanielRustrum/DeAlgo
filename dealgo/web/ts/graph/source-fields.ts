// The panel's fields for a source: what it takes, its mirror, its counts.
//
// Part of the Configuration canvas; see main.ts.

/** A source box's panel: what to watch when empty, or its source's settings. */
function graphChannelFields(
  state: GraphState,
  form: HTMLElement,
  node: GraphNodeView,
): void {
  if (node.detail === null) {
    // An empty box: these are the fields that decide what it stands for. It
    // already knows which kind of somewhere it is for, because that is the
    // box that was dragged out, so it asks for that and nothing else.
    const asks = node.asks;
    const kind = asks === null ? "" : asks.kind;

    // Something already watched first: that needs no lookup and no
    // credentials, and most of the time it is already there.
    graphSourcePicker(state, form, kind);

    if (asks !== null && kind !== "" && !asks.known) {
      form.appendChild(
        graphElement(
          "p",
          "hint",
          `Nothing here provides ${kind} sources any more. Its plugin may be switched off on the Plugins page. Point this box at something already watched, or delete it.`,
        ),
      );
      return;
    }
    if (kind === "") {
      // A box from before sources had kinds. There is no longer a way to
      // make one, and no way to tell what it was meant to be.
      form.appendChild(
        graphElement(
          "p",
          "hint",
          "This box was made before sources had kinds. Point it at something already watched, or delete it and drag out the kind you want.",
        ),
      );
      return;
    }

    const handle = document.createElement("input");
    handle.type = "text";
    handle.name = "handle";
    handle.placeholder = asks === null ? "" : asks.example;
    form.appendChild(
      graphLabelled(state.sources.length > 0 ? "Or somewhere new" : "Where to watch", handle),
    );

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
        `${asks === null ? "" : asks.label}: ${asks === null ? "" : asks.example}. A source stays paused until it is wired to a feed.`,
      ),
    );
    return;
  }
  const channel = node.channel;
  if (channel === null) return;

  form.appendChild(graphTakes(channel));
  form.appendChild(graphChecks(node, channel));
  if (channel.rest !== null) form.appendChild(graphRestFields(node, channel, channel.rest));
  if (channel.mirrors) form.appendChild(graphMirror(channel));
  form.appendChild(graphChannelCounts(node, channel));
}

/** A switch for each kind of content the source's plugin says it publishes.
 *
 *  YouTube's are videos, Shorts, broadcasts and community posts. A source
 *  that publishes one kind of thing declares none, so the box says so
 *  rather than offering switches that would decide nothing. */
function graphTakes(channel: GraphChannel): HTMLElement {
  const group = graphElement("div", "graph-group");
  group.appendChild(graphElement("span", "graph-group-name", "Takes"));

  if (channel.takes.length === 0) {
    group.appendChild(
      graphElement(
        "span",
        "graph-group-note",
        `Everything ${channel.source} publishes to this feed. Filter boxes wired after this one are what narrow it.`,
      ),
    );
    return group;
  }

  const switches = graphElement("div", "graph-switches");
  for (const take of channel.takes) {
    const row = graphElement("label", "graph-switch");
    const tick = document.createElement("input");
    tick.type = "checkbox";
    tick.name = "takes";
    tick.value = take.name;
    tick.checked = take.on;
    row.appendChild(tick);
    row.appendChild(graphElement("span", "graph-switch-name", take.label));
    switches.appendChild(row);
  }
  group.appendChild(switches);
  return group;
}

/** A plugin augmentation's own fields, exactly as its plugin declared them.
 *
 *  The host knows none of these names. They are sent back under the names
 *  the plugin chose and stored as they came, because a column per field is
 *  not a thing a plugin can ask for. */
function graphPluginFields(form: HTMLElement, node: GraphNodeView): void {
  const box = node.plugin;
  if (box === null) return;

  if (box.missing !== null) {
    form.appendChild(
      graphElement(
        "p",
        "hint",
        `This condition belongs to “${box.missing}”, which is not loaded. It narrows nothing while that is true. Switch the plugin on under Admin → Plugins, or take the piece off the canvas.`,
      ),
    );
    return;
  }

  if (box.blurb !== "") form.appendChild(graphElement("p", "hint", box.blurb));

  for (const one of box.fields) {
    const field = document.createElement("input");
    field.type = one.type === "number" ? "number" : "text";
    // Prefixed, so a plugin cannot name a field "active" or "label" and
    // quietly take over one of the form's own.
    field.name = `plugin_${one.name}`;
    field.value = one.value;
    if (one.placeholder !== "") field.placeholder = one.placeholder;
    form.appendChild(graphLabelled(one.label, field));
  }

  if (node.piece?.under == null) {
    const where = box.under === "sort" ? "a Sort" : "a Filter";
    form.appendChild(
      graphElement("p", "hint", `Loose on the canvas. Drop it on ${where} box to slot it in.`),
    );
  }

  // A plugin's ordering works its own number out, so there is no key to
  // choose — only which end of it comes first.
  if (node.sort !== null) graphEndsField(form, node.sort, "Which end first", node.title);

  if (box.fields.length === 0) {
    form.appendChild(graphElement("p", "hint", "Nothing to set: it judges on its own."));
  }
}

/** Somewhere else to read the same feed, for a host that rations us.
 *
 *  Offered only where it can help: YouTube's feed has never turned anybody
 *  away, and a box full of fields that do nothing is worse than no box.
 *  Tried only when the source itself refuses, so the source stays the source. */
function graphMirror(channel: GraphChannel): HTMLElement {
  const group = graphElement("div", "graph-group");
  group.appendChild(graphElement("span", "graph-group-name", "If it will not have us"));

  const field = document.createElement("input");
  field.type = "url";
  field.name = "mirror_url";
  field.placeholder = channel.mirrorHint ?? "https://…";
  field.value = channel.mirror ?? "";
  group.appendChild(graphLabelled("Read it from here instead", field));

  // Offered rather than filled in: leaning on somebody else's service is the
  // reader's call, so the suggestion sits there until it is taken.
  if (channel.mirrorHint !== null && (channel.mirror ?? "") === "") {
    const take = graphElement("button", "btn btn-quiet", "Use Open RSS");
    take.setAttribute("type", "button");
    take.title = channel.mirrorHint;
    take.addEventListener("click", (): void => {
      field.value = channel.mirrorHint ?? "";
      take.remove();
    });
    group.appendChild(take);
  }

  group.appendChild(
    graphElement(
      "span",
      "graph-group-note",
      `Used only when ${graphHostOf(channel.feedUrl)} refuses or rations us — never in its place. A mirror is somebody else's copy of the same feed.`,
    ),
  );
  return group;
}

/** The host of an address, for saying which one is doing the refusing. */
function graphHostOf(url: string): string {
  try {
    return new URL(url).hostname;
  } catch {
    return "the source";
  }
}

/** When it was last polled, and what decides when it next will be.
 *
 *  Nothing to set here: a trigger wired into this box decides that, and an
 *  interval offered in two places is an interval that will disagree with
 *  itself. The channel's own gap still applies while no trigger is wired, and
 *  the line below says which of the two is in force. */
function graphChecks(node: GraphNodeView, channel: GraphChannel): HTMLElement {
  const group = graphElement("div", "graph-group");
  group.appendChild(graphElement("span", "graph-group-name", "Checks"));
  if (node.polled !== null) group.appendChild(graphElement("span", "graph-group-note", node.polled));
  if (channel.checked !== null) {
    group.appendChild(
      graphElement("span", "graph-group-note", `Last looked at ${graphWhen(channel.checked)}.`),
    );
  }
  return group;
}

/** An instant on the reader's own clock, as near or far as it actually is. */
function graphWhen(instant: string): string {
  const when = new Date(instant);
  const minutes = Math.round((when.getTime() - Date.now()) / 60000);
  const size = Math.abs(minutes);
  const [divisor, unit] =
    size < 60 ? [1, "minute"] : size < 1440 ? [60, "hour"] : [1440, "day"];
  const count = Math.max(1, Math.round(size / divisor));
  const plural = count === 1 ? "" : "s";
  return minutes < 0 ? `${count} ${unit}${plural} ago` : `in ${count} ${unit}${plural}`;
}

/** What it has put into its feeds. Not which feeds: the wires say that, and
 *  saying it twice invites the two to disagree. */
function graphChannelCounts(node: GraphNodeView, channel: GraphChannel): HTMLElement {
  const group = graphElement("div", "graph-group");
  group.appendChild(graphElement("span", "graph-group-name", "Videos"));

  const counts = graphElement("div", "graph-counts");
  for (const [count, name, status] of [
    [channel.placed, "placed", "added"],
    [channel.pending, "pending", "pending"],
  ] as const) {
    const link = document.createElement("a");
    link.href = `/videos?status=${status}&channel=${graphChannelId(node)}`;
    link.appendChild(graphElement("strong", "", String(count)));
    link.appendChild(document.createTextNode(` ${name}`));
    counts.appendChild(link);
  }
  group.appendChild(counts);
  return group;
}

/** The channel's own id, which is what its pages are addressed by. */
function graphChannelId(node: GraphNodeView): string {
  return (node.detail ?? "").split("/").pop() ?? "";
}


/** The fields a REST source maps, in the order they are shown, and what each is. */
function graphRestFieldNames(): string[] {
  return ["items", "id", "title", "link", "published", "image", "summary"];
}

function graphRestFieldLabel(name: string): string {
  if (name === "items") return "List of items";
  if (name === "id") return "Id";
  if (name === "published") return "Date";
  if (name === "image") return "Picture";
  return name.charAt(0).toUpperCase() + name.slice(1);
}

/** A REST API source's address, where its items are, which field of each is
 *  what, and the header that carries its key — with Try it, which reads the
 *  API with whatever the fields say now, before anything is saved. */
function graphRestFields(node: GraphNodeView, channel: GraphChannel, rest: GraphRest): HTMLElement {
  const group = graphElement("div", "graph-group graph-rest");
  group.appendChild(graphElement("span", "graph-group-name", "What to read"));

  const url = document.createElement("input");
  url.type = "url";
  url.name = "rest_url";
  url.value = channel.feedUrl;
  group.appendChild(graphLabelled("API address", url));

  group.appendChild(
    graphElement(
      "span",
      "graph-group-note",
      "Paths into the JSON, with dots between the steps and numbers for a place in a list: data.children, images.0.url. Leave one empty to have it guessed; Try it shows what was guessed.",
    ),
  );
  const inputs = new Map<string, HTMLInputElement>();
  for (const name of graphRestFieldNames()) {
    const field = document.createElement("input");
    field.type = "text";
    field.name = `rest_${name}`;
    field.value = rest.paths[name] ?? "";
    field.placeholder = "guessed";
    field.spellcheck = false;
    inputs.set(name, field);
    group.appendChild(graphLabelled(graphRestFieldLabel(name), field));
  }

  // The key travels as one header. Its value is never sent back to the page,
  // so the field shows that one is set and stays empty: left empty, it is kept.
  const headerName = document.createElement("input");
  headerName.type = "text";
  headerName.name = "rest_header_name";
  headerName.value = rest.headerName;
  headerName.placeholder = "Authorization, X-API-Key…";
  headerName.spellcheck = false;
  const headerValue = document.createElement("input");
  headerValue.type = "password";
  headerValue.name = "rest_header_value";
  headerValue.autocomplete = "off";
  headerValue.placeholder = rest.hasKey ? "set — leave empty to keep it" : "Bearer …, or the key";
  const pair = graphElement("div", "graph-pair");
  pair.append(headerName, headerValue);
  group.appendChild(graphLabelled("Header with its key", pair));
  if (rest.hasKey) {
    const clear = document.createElement("label");
    clear.className = "check";
    const box = document.createElement("input");
    box.type = "checkbox";
    box.name = "rest_header_clear";
    box.value = "1";
    clear.append(box, " Stop sending it");
    group.appendChild(clear);
  }

  if (rest.error !== "") {
    group.appendChild(graphElement("p", "error-note", `Last read: ${rest.error}`));
  }

  const tryIt = graphElement("button", "btn btn-quiet", "Try it") as HTMLButtonElement;
  tryIt.type = "button";
  tryIt.title = "Read the API with these fields, without saving them";
  const said = graphElement("div", "graph-rest-said");
  said.setAttribute("aria-live", "polite");
  tryIt.addEventListener("click", (): void => {
    void tryGraphRest(node.id, group, inputs, said);
  });
  group.append(tryIt, said);
  return group;
}

/** Read the API with the fields as they stand, and show what came back. */
async function tryGraphRest(
  nodeId: number,
  group: HTMLElement,
  inputs: Map<string, HTMLInputElement>,
  said: HTMLElement,
): Promise<void> {
  const body = new URLSearchParams();
  group.querySelectorAll<HTMLInputElement>("input[name^='rest_']").forEach((field) => {
    if (field.type === "checkbox") {
      if (field.checked) body.append(field.name, field.value);
    } else {
      body.append(field.name, field.value);
    }
  });
  said.replaceChildren(graphElement("p", "hint", "Reading…"));
  let answer: unknown;
  try {
    answer = await askGraph(`/graph/nodes/${nodeId}/rest/try`, body);
  } catch {
    said.replaceChildren(graphElement("p", "error-note", "No connection, so it could not be tried."));
    return;
  }
  const raw = asGraphRecord(answer);
  if (raw === null || typeof raw["error"] === "string") {
    const why = raw !== null && typeof raw["error"] === "string" ? raw["error"] : "That did not work.";
    said.replaceChildren(graphElement("p", "error-note", why));
    return;
  }
  // What was guessed goes into the empty fields as a placeholder, so it can
  // be seen, and typed in to keep it whatever the API does later.
  const paths = asGraphRecord(raw["paths"]);
  if (paths !== null) {
    for (const [name, field] of inputs) {
      const path = paths[name];
      if (field.value === "" && typeof path === "string") field.placeholder = path || "(the whole answer)";
    }
  }
  const count = typeof raw["count"] === "number" ? raw["count"] : 0;
  const list = graphElement("ol", "graph-rest-items");
  const items = raw["items"];
  if (Array.isArray(items)) {
    for (const one of items) {
      const item = asGraphRecord(one);
      if (item === null) continue;
      const row = graphElement("li", "");
      row.appendChild(graphElement("strong", "", typeof item["title"] === "string" ? item["title"] : ""));
      const when = typeof item["published"] === "string" ? new Date(item["published"]).toLocaleString() : "no date";
      const link = typeof item["link"] === "string" && item["link"] !== "" ? item["link"] : "no link";
      row.appendChild(graphElement("span", "graph-rest-meta", `${when} · ${link}`));
      list.appendChild(row);
    }
  }
  said.replaceChildren(
    graphElement("p", "hint", `Read ${count} item${count === 1 ? "" : "s"}. The first few, as they will arrive:`),
    list,
  );
}
