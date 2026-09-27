"use strict";
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
/** The conditions the host itself offers, as against a plugin's. */
function graphConditionKinds() {
    return [
        "has-words", "lacks-words", "longer-than", "shorter-than",
        "carrying", "at-most", "order",
    ];
}
/** Which kinds are pieces rather than boxes. */
function graphIsPiece(kind) {
    return (kind === "timer" || kind === "reset" || kind === "alive" || kind === "lock" ||
        kind === "rule" || graphConditionKinds().indexOf(kind) >= 0);
}
/** Which boxes have somewhere for a piece to go. */
function graphTakesPieces(kind) {
    return (kind === "feed" || kind === "decay" || kind === "expire" ||
        kind === "filter" || kind === "sort");
}
// -- reading what the server said -----------------------------------------
function asGraphRecord(value) {
    return typeof value === "object" && value !== null && !Array.isArray(value)
        ? value
        : null;
}
function asGraphNodeKind(value) {
    if (value === "trigger" ||
        value === "source" ||
        value === "filter" ||
        value === "sort" ||
        value === "feed" ||
        value === "group" ||
        value === "deposit" ||
        value === "withdraw" ||
        value === "timer" ||
        value === "reset" ||
        value === "alive" ||
        value === "lock" ||
        value === "decay" ||
        value === "expire" ||
        value === "tag" ||
        value === "has-words" ||
        value === "lacks-words" ||
        value === "longer-than" ||
        value === "shorter-than" ||
        value === "carrying" ||
        value === "at-most" ||
        value === "order" ||
        value === "rule") {
        return value;
    }
    return null;
}
function asGraphNode(value) {
    const raw = asGraphRecord(value);
    if (raw === null)
        return null;
    const kind = asGraphNodeKind(raw["kind"]);
    const id = raw["id"];
    if (kind === null || typeof id !== "number")
        return null;
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
        channel: asGraphChannel(raw["channel"]),
        asks: asGraphAsks(raw["asks"]),
        store: asGraphStore(raw["store"]),
        stamp: asGraphStamp(raw["stamp"]),
        piece: asGraphPiece(raw["piece"]),
        condition: asGraphCondition(raw["condition"]),
        plugin: asGraphPlugin(raw["plugin"]),
        feed: asGraphFeed(raw["feed"]),
    };
}
function asGraphAsks(value) {
    const raw = asGraphRecord(value);
    if (raw === null)
        return null;
    return {
        kind: typeof raw["kind"] === "string" ? raw["kind"] : "",
        label: typeof raw["label"] === "string" ? raw["label"] : "",
        source: typeof raw["source"] === "string" ? raw["source"] : "",
        example: typeof raw["example"] === "string" ? raw["example"] : "",
        known: raw["known"] === true,
    };
}
function asGraphPiece(value) {
    const raw = asGraphRecord(value);
    if (raw === null)
        return null;
    const under = raw["under"];
    return {
        under: typeof under === "number" ? under : null,
        minutes: typeof raw["minutes"] === "number" ? raw["minutes"] : 30,
        cron: typeof raw["cron"] === "string" ? raw["cron"] : "",
        from: typeof raw["from"] === "string" ? raw["from"] : "",
        to: typeof raw["to"] === "string" ? raw["to"] : "",
        every: asGraphEvery(raw["every"]),
    };
}
function asGraphCondition(value) {
    const raw = asGraphRecord(value);
    if (raw === null)
        return null;
    const units = raw["units"];
    const field = raw["field"];
    return {
        label: typeof raw["label"] === "string" ? raw["label"] : "",
        blurb: typeof raw["blurb"] === "string" ? raw["blurb"] : "",
        field: field === "duration" || field === "number" || field === "order"
            ? field
            : "text",
        asks: typeof raw["asks"] === "string" ? raw["asks"] : "",
        under: raw["under"] === "sort" ? "sort" : "filter",
        value: typeof raw["value"] === "string" ? raw["value"] : "",
        unit: typeof raw["unit"] === "string" ? raw["unit"] : "minutes",
        units: Array.isArray(units)
            ? units.filter((one) => typeof one === "string")
            : [],
        says: typeof raw["says"] === "string" ? raw["says"] : "",
    };
}
function asGraphStamp(value) {
    const raw = asGraphRecord(value);
    if (raw === null)
        return null;
    return { marks: typeof raw["marks"] === "string" ? raw["marks"] : "" };
}
function asGraphStore(value) {
    const raw = asGraphRecord(value);
    if (raw === null)
        return null;
    return {
        name: typeof raw["name"] === "string" ? raw["name"] : "",
        waiting: typeof raw["waiting"] === "number" ? raw["waiting"] : 0,
        takes: typeof raw["takes"] === "number" ? raw["takes"] : 0,
        pulls: raw["pulls"] === true,
    };
}
function asGraphFeed(value) {
    const raw = asGraphRecord(value);
    if (raw === null)
        return null;
    const windows = raw["windows"];
    return {
        windows: Array.isArray(windows)
            ? windows.filter((entry) => typeof entry === "string")
            : [],
        open: raw["open"] !== false,
        maxItems: typeof raw["max_items"] === "number" ? raw["max_items"] : 0,
        maxPerRun: typeof raw["max_per_run"] === "number" ? raw["max_per_run"] : 0,
        generic: raw["generic"] === true,
    };
}
function asGraphChannel(value) {
    var _a;
    const raw = asGraphRecord(value);
    if (raw === null)
        return null;
    const takes = {};
    const given = (_a = asGraphRecord(raw["takes"])) !== null && _a !== void 0 ? _a : {};
    for (const key of Object.keys(given))
        takes[key] = given[key] === true;
    const checked = raw["checked"];
    return {
        source: typeof raw["source"] === "string" ? raw["source"] : "YouTube",
        // Absent means YouTube: everything on a canvas drawn before there was
        // anywhere else to draw is one.
        youtube: raw["youtube"] !== false,
        feedUrl: typeof raw["feed_url"] === "string" ? raw["feed_url"] : "",
        mirror: typeof raw["mirror"] === "string" ? raw["mirror"] : null,
        mirrorHint: typeof raw["mirror_hint"] === "string" ? raw["mirror_hint"] : null,
        takes,
        checked: typeof checked === "string" ? checked : null,
        placed: typeof raw["placed"] === "number" ? raw["placed"] : 0,
        pending: typeof raw["pending"] === "number" ? raw["pending"] : 0,
    };
}
function asGraphSize(value) {
    const raw = asGraphRecord(value);
    if (raw === null)
        return null;
    return {
        width: typeof raw["width"] === "number" ? raw["width"] : 520,
        height: typeof raw["height"] === "number" ? raw["height"] : 300,
    };
}
function asGraphPlugin(value) {
    const raw = asGraphRecord(value);
    if (raw === null)
        return null;
    const missing = raw["missing"];
    const fields = [];
    for (const entry of Array.isArray(raw["fields"]) ? raw["fields"] : []) {
        const one = asGraphRecord(entry);
        if (one === null)
            continue;
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
        fields: fields.filter((one) => one.name !== ""),
    };
}
function asGraphSort(value) {
    const raw = asGraphRecord(value);
    if (raw === null)
        return null;
    const keys = [];
    const offered = raw["keys"];
    if (Array.isArray(offered)) {
        for (const entry of offered) {
            const key = asGraphRecord(entry);
            if (key === null || typeof key["name"] !== "string")
                continue;
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
function asGraphEvery(value) {
    const raw = asGraphRecord(value);
    const units = [];
    const offered = raw === null ? null : raw["units"];
    if (Array.isArray(offered)) {
        for (const entry of offered) {
            const unit = asGraphRecord(entry);
            if (unit === null || typeof unit["name"] !== "string")
                continue;
            units.push({
                name: unit["name"],
                label: typeof unit["label"] === "string" ? unit["label"] : unit["name"],
            });
        }
    }
    return {
        amount: typeof (raw === null || raw === void 0 ? void 0 : raw["amount"]) === "number" ? raw["amount"] : 60,
        unit: typeof (raw === null || raw === void 0 ? void 0 : raw["unit"]) === "string" ? raw["unit"] : "minutes",
        units,
    };
}
function asGraphTrigger(value) {
    const raw = asGraphRecord(value);
    if (raw === null)
        return null;
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
function asGraphWire(value) {
    const raw = asGraphRecord(value);
    if (raw === null)
        return null;
    const id = raw["id"];
    const from = raw["from"];
    const to = raw["to"];
    if (typeof id !== "string" || typeof from !== "number" || typeof to !== "number")
        return null;
    return { id, from, to, kind: "edge" };
}
/** The graph, or null if this is not one — an error body, say. */
function asGraph(value) {
    const raw = asGraphRecord(value);
    if (raw === null)
        return null;
    const nodes = raw["nodes"];
    const wires = raw["wires"];
    if (!Array.isArray(nodes) || !Array.isArray(wires))
        return null;
    const readNodes = [];
    for (const entry of nodes) {
        const node = asGraphNode(entry);
        if (node !== null)
            readNodes.push(node);
    }
    const readWires = [];
    for (const entry of wires) {
        const wire = asGraphWire(entry);
        if (wire !== null)
            readWires.push(wire);
    }
    const watched = [];
    const offered = raw["sources"];
    if (Array.isArray(offered)) {
        for (const entry of offered) {
            const source = asGraphRecord(entry);
            if (source === null || typeof source["id"] !== "number")
                continue;
            watched.push({
                id: source["id"],
                title: typeof source["title"] === "string" ? source["title"] : "",
                kind: typeof source["kind"] === "string" ? source["kind"] : "",
            });
        }
    }
    return { nodes: readNodes, wires: readWires, sources: watched };
}
function asGraphError(value) {
    const raw = asGraphRecord(value);
    const message = raw === null ? null : raw["error"];
    return typeof message === "string" ? message : null;
}
// -- talking to the server -------------------------------------------------
async function askGraph(url, body) {
    const init = body === null
        ? { headers: { Accept: "application/json" } }
        : { method: "POST", body, headers: { Accept: "application/json" } };
    const response = await fetch(url, init);
    return (await response.json());
}
/** Send a change, take the graph that comes back, redraw. */
async function applyGraph(state, url, body) {
    var _a;
    if (state.busy)
        return false;
    state.busy = true;
    try {
        const answer = await askGraph(url, body);
        const view = asGraph(answer);
        if (view === null) {
            showGraphError(state, (_a = asGraphError(answer)) !== null && _a !== void 0 ? _a : "That change did not go through.");
            return false;
        }
        state.nodes = view.nodes;
        state.wires = view.wires;
        state.sources = view.sources;
        forgetMissingGraph(state);
        showGraphError(state, null);
        renderGraph(state);
        return true;
    }
    catch (_b) {
        showGraphError(state, "No connection, so nothing was changed.");
        return false;
    }
    finally {
        state.busy = false;
    }
}
/** A box or wire can vanish under a selection — the server had the last word. */
function forgetMissingGraph(state) {
    if (state.selectedNode !== null && !state.nodes.some((n) => n.id === state.selectedNode)) {
        state.selectedNode = null;
    }
    if (state.selectedWire !== null && !state.wires.some((w) => w.id === state.selectedWire)) {
        state.selectedWire = null;
    }
}
// -- drawing ---------------------------------------------------------------
function graphElement(tag, className, text) {
    const made = document.createElement(tag);
    made.className = className;
    if (text !== undefined)
        made.textContent = text;
    return made;
}
function graphKindLabel(kind) {
    if (kind === "source")
        return "Source";
    if (kind === "deposit")
        return "Deposit";
    if (kind === "withdraw")
        return "Withdraw";
    if (kind === "timer")
        return "Timer";
    if (kind === "reset")
        return "Reset";
    if (kind === "alive")
        return "Alive";
    if (kind === "lock")
        return "Lock";
    if (kind === "decay")
        return "Decay";
    if (kind === "expire")
        return "Expire";
    if (kind === "tag")
        return "Tag";
    if (kind === "feed")
        return "Feed";
    if (kind === "sort")
        return "Sort";
    if (kind === "group")
        return "Group";
    if (kind === "rule")
        return "Rule";
    if (kind === "has-words")
        return "Title has";
    if (kind === "lacks-words")
        return "Title lacks";
    if (kind === "longer-than")
        return "Longer than";
    if (kind === "shorter-than")
        return "Shorter than";
    if (kind === "carrying")
        return "Carrying";
    if (kind === "at-most")
        return "At most";
    if (kind === "order")
        return "Order";
    return kind === "trigger" ? "Trigger" : "Filter";
}
function graphPort(where, carries, says) {
    const dot = graphElement("span", `graph-port port-${where} carries-${carries}`);
    dot.dataset["port"] = where;
    dot.title = says;
    dot.appendChild(graphPortIcon(carries));
    return dot;
}
/** The mark inside a port. Drawn rather than written: at this size a letter
 *  is a smudge, and a shape is still a shape. */
function graphPortIcon(carries) {
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("class", "graph-port-icon");
    svg.setAttribute("viewBox", "0 0 10 10");
    svg.setAttribute("aria-hidden", "true");
    const mark = document.createElementNS("http://www.w3.org/2000/svg", "path");
    mark.setAttribute("d", carries === "signal"
        // A bolt: something setting the channel off.
        ? "M6.2 0.6 L2.2 5.6 H4.5 L3.8 9.4 L7.8 4.4 H5.5 Z"
        // A play mark: the videos and posts being carried along.
        : "M2.6 1.2 L8.2 5 L2.6 8.8 Z");
    svg.appendChild(mark);
    return svg;
}
/** What each side of a box takes in or gives out, in a sentence. */
function graphPortWords(kind, where) {
    if (kind === "trigger")
        return "Gives out a signal: wire it to a channel to say when to poll it.";
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
function drawGraphGroup(state, node) {
    var _a, _b;
    var _c, _d;
    const frame = graphElement("div", "graph-group-box");
    frame.dataset["node"] = String(node.id);
    frame.style.left = `${node.x}px`;
    frame.style.top = `${node.y}px`;
    frame.style.width = `${(_c = (_a = node.size) === null || _a === void 0 ? void 0 : _a.width) !== null && _c !== void 0 ? _c : 520}px`;
    frame.style.height = `${(_d = (_b = node.size) === null || _b === void 0 ? void 0 : _b.height) !== null && _d !== void 0 ? _d : 300}px`;
    frame.tabIndex = 0;
    frame.setAttribute("role", "button");
    frame.setAttribute("aria-label", `Group: ${node.title}`);
    if (state.picked.has(node.id))
        frame.classList.add("is-picked");
    if (!node.enabled)
        frame.classList.add("is-off");
    const name = graphElement("span", "graph-group-name", node.title);
    frame.appendChild(name);
    // Bottom-right, where a resize handle is looked for.
    const grip = graphElement("span", "graph-group-grip");
    grip.dataset["grip"] = String(node.id);
    grip.title = "Drag to resize";
    frame.appendChild(grip);
    return frame;
}
function drawGraphNode(state, node) {
    const box = graphElement("div", `graph-node kind-${node.kind}`);
    box.dataset["node"] = String(node.id);
    box.style.left = `${node.x}px`;
    box.style.top = `${node.y}px`;
    box.tabIndex = 0;
    box.setAttribute("role", "button");
    box.setAttribute("aria-label", `${graphTriggerLabel(node)}: ${node.title}`);
    if (state.picked.has(node.id))
        box.classList.add("is-picked");
    if (!node.enabled)
        box.classList.add("is-off");
    if (node.piece !== null) {
        // A piece is slotted, not wired: nothing runs into or out of one, so it
        // has no ports at all.
        box.classList.add("is-piece");
        // A piece nobody has slotted in yet is the only one that shows its tab:
        // a joined edge has the tab inside the joint, not drawn on top of it.
        if (node.piece.under === null)
            box.classList.add("is-loose");
        box.appendChild(graphElement("span", "graph-node-kind", graphKindLabel(node.kind)));
        box.appendChild(graphElement("strong", "graph-node-title", node.note));
        return box;
    }
    if (node.kind !== "trigger") {
        // A channel and a withdraw are set off by a signal; everything else is
        // fed content.
        const takes = node.kind === "source" || node.kind === "withdraw" ? "signal" : "content";
        box.appendChild(graphPort("in", takes, graphPortWords(node.kind, "in")));
    }
    box.appendChild(graphElement("span", "graph-node-kind", graphTriggerLabel(node)));
    box.appendChild(graphElement("strong", "graph-node-title", node.title));
    box.appendChild(graphElement("span", "graph-node-note", node.note));
    if (node.trigger !== null)
        box.appendChild(graphFireButton(node));
    // A feed and a deposit are both ends of a path: nothing leaves either.
    if (node.kind !== "feed" && node.kind !== "deposit") {
        const gives = node.kind === "trigger" ? "signal" : "content";
        box.appendChild(graphPort("out", gives, graphPortWords(node.kind, "out")));
    }
    return box;
}
/** A trigger says which of the two it is, since they behave nothing alike. */
function graphTriggerLabel(node) {
    if (node.trigger !== null)
        return node.trigger.kind === "pulse" ? "Pulse" : "Schedule";
    // A source box says where it watches rather than that it is a source box.
    // Which of the two it is, is the thing somebody chose when they dragged it
    // out; "Channel" said the same for a subreddit and a YouTube channel and
    // so said nothing at all.
    if (node.kind === "source")
        return graphSourceLabel(node);
    // A plugin box is its plugin's, and saying so is more use than the word
    // "plugin" over a name that is already the box's own.
    if (node.plugin !== null && node.plugin.plugin !== "")
        return node.plugin.plugin;
    return graphKindLabel(node.kind);
}
/** Where a source box watches: "Reddit", "YouTube". Filled boxes read it off
 *  the channel behind them, empty ones off the kind they were dragged out as,
 *  and a box whose plugin has gone falls back to the plain word. */
function graphSourceLabel(node) {
    if (node.channel !== null && node.channel.source !== "")
        return node.channel.source;
    if (node.asks !== null && node.asks.source !== "")
        return node.asks.source;
    return "Source";
}
function graphFireButton(node) {
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
function drawGraphNodes(state) {
    state.parts.layer.textContent = "";
    state.parts.groups.textContent = "";
    state.boxes.clear();
    // Groups into their own layer, under the wires: a group is a background,
    // and a rectangle over what it surrounds would be in the way of all of it —
    // including the wires crossing it, which would stop being clickable.
    for (const node of state.nodes) {
        if (node.kind !== "group")
            continue;
        const frame = drawGraphGroup(state, node);
        state.boxes.set(node.id, frame);
        state.parts.groups.appendChild(frame);
    }
    for (const node of state.nodes) {
        if (node.kind === "group")
            continue;
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
function placeGraphPieces(state) {
    var _a, _b;
    const under = new Map();
    for (const node of state.nodes) {
        const host = (_a = node.piece) === null || _a === void 0 ? void 0 : _a.under;
        if (host === undefined || host === null)
            continue;
        const kept = under.get(host);
        if (kept === undefined)
            under.set(host, [node]);
        else
            kept.push(node);
    }
    if (under.size === 0)
        return;
    // From the model's own coordinates, which is what every other box is drawn
    // from. `offsetTop` is measured against whichever ancestor happens to be
    // positioned, so a piece placed from it lands wherever that ancestor is
    // rather than under its host.
    const place = (hostId, left, top, depth) => {
        var _a;
        if (depth > 12)
            return; // a ring built before they were refused
        for (const piece of (_a = under.get(hostId)) !== null && _a !== void 0 ? _a : []) {
            const box = state.boxes.get(piece.id);
            if (box === undefined)
                continue;
            box.style.left = `${left}px`;
            box.style.top = `${top}px`;
            // Kept on the node as well, so anything that reads a position — a
            // group working out what it surrounds, a drag starting from here —
            // sees where the piece actually is.
            piece.x = left;
            piece.y = top;
            const next = top + box.offsetHeight;
            place(piece.id, left, next, depth + 1);
            top = next;
        }
    };
    // A box with something slotted into it gets the notch the tab sits in.
    for (const [hostId] of under) {
        (_b = state.boxes.get(hostId)) === null || _b === void 0 ? void 0 : _b.classList.add("has-piece");
    }
    for (const node of state.nodes) {
        if (node.piece !== null)
            continue; // a chain belongs to the box at its top
        const box = state.boxes.get(node.id);
        if (box === undefined || !under.has(node.id))
            continue;
        place(node.id, node.x, node.y + box.offsetHeight, 0);
    }
}
/** Where a wire leaves a box, and where it arrives — measured, not guessed. */
function graphPortPoint(state, nodeId, where) {
    const box = state.boxes.get(nodeId);
    const node = state.nodes.find((entry) => entry.id === nodeId);
    if (box === undefined || node === undefined)
        return null;
    return {
        x: where === "out" ? node.x + box.offsetWidth : node.x,
        y: node.y + box.offsetHeight / 2,
    };
}
function graphCurve(x1, y1, x2, y2) {
    const reach = Math.max(40, Math.abs(x2 - x1) * 0.5);
    return `M ${x1} ${y1} C ${x1 + reach} ${y1}, ${x2 - reach} ${y2}, ${x2} ${y2}`;
}
function graphSvgPath(className, d) {
    const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
    path.setAttribute("class", className);
    path.setAttribute("d", d);
    return path;
}
function drawGraphWires(state) {
    state.parts.wires.textContent = "";
    // The ✕ belongs to a wire but lives among the boxes, so it is cleared here
    // rather than with them — a drag redraws the wires many times over.
    state.parts.layer.querySelectorAll(".graph-cut").forEach((button) => button.remove());
    for (const wire of state.wires) {
        const from = graphPortPoint(state, wire.from, "out");
        const to = graphPortPoint(state, wire.to, "in");
        if (from === null || to === null)
            continue;
        const d = graphCurve(from.x, from.y, to.x, to.y);
        let classes = `graph-wire wire-${wire.kind}`;
        if (wire.id === state.selectedWire)
            classes += " is-picked";
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
        if (wire.id === state.selectedWire) {
            state.parts.layer.appendChild(graphCutButton(wire.id, (from.x + to.x) / 2, (from.y + to.y) / 2));
        }
    }
}
/** The ✕ on a picked wire. Two clicks to remove a wire, never one by accident. */
function graphCutButton(wireId, x, y) {
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
function graphZoomLimits() {
    return { least: 0.3, most: 2.5 };
}
/** Move the whole drawing under the window. The canvas has no edges. */
function panGraph(state, x, y) {
    state.panX = x;
    state.panY = y;
    showGraphView(state);
}
function showGraphView(state) {
    const { panX, panY, zoom } = state;
    state.parts.scene.style.transform = `translate(${panX}px, ${panY}px) scale(${zoom})`;
    state.parts.scene.style.transformOrigin = "0 0";
    // The grid moves and scales with it, or the drawing looks like it is
    // sliding over a pattern that is nailed down.
    const grid = 26 * zoom;
    state.parts.canvas.style.backgroundSize = `${grid}px ${grid}px`;
    state.parts.canvas.style.backgroundPosition = `${panX}px ${panY}px`;
    const reading = state.parts.canvas.querySelector("[data-graph-zoom]");
    if (reading !== null)
        reading.textContent = `${Math.round(zoom * 100)}%`;
}
/** Zoom about a point on screen, so whatever is under the pointer stays put.
 *
 *  Zooming about the corner instead would send the thing being looked at off
 *  the edge, which is the difference between a zoom and a surprise. */
function zoomGraph(state, factor, clientX, clientY) {
    const limits = graphZoomLimits();
    const next = Math.min(limits.most, Math.max(limits.least, state.zoom * factor));
    if (next === state.zoom)
        return;
    const at = pointInGraph(state, { clientX, clientY });
    const frame = state.parts.canvas.getBoundingClientRect();
    state.zoom = next;
    state.panX = clientX - frame.left - at.x * next;
    state.panY = clientY - frame.top - at.y * next;
    showGraphView(state);
}
function renderGraph(state) {
    drawGraphNodes(state);
    drawGraphWires(state);
    renderGraphPopover(state);
    renderGraphFinder(state);
    // The boxes were just rebuilt from scratch, so whatever the run had marked
    // on them has to go back on.
    paintGraphRun(state);
    // The canvas itself is never hidden: the palette lives inside it, so an
    // account with nothing on it would have nothing to add anything with.
    if (state.parts.empty !== null)
        state.parts.empty.hidden = state.nodes.length > 0;
}
function showGraphError(state, message) {
    const box = state.parts.error;
    if (box === null)
        return;
    box.textContent = message !== null && message !== void 0 ? message : "";
    box.hidden = message === null;
}
function showGraphVerdict(state, message) {
    const box = state.parts.verdict;
    if (box === null)
        return;
    box.textContent = message !== null && message !== void 0 ? message : "";
    box.hidden = message === null;
}
// -- the panel beside it ---------------------------------------------------
function graphLabelled(name, control) {
    const row = graphElement("label", "graph-field");
    row.appendChild(graphElement("span", "graph-field-name", name));
    row.appendChild(control);
    return row;
}
/** The open box's detail, drawn on the canvas beside the box it belongs to.
 *
 *  In the scene rather than beside it, so it pans with the box and stays
 *  plainly attached to it — a panel off to one side makes the reader hold
 *  "which box was this about?" in their head. */
function renderGraphPopover(state) {
    state.parts.layer.querySelectorAll(".graph-pop").forEach((old) => old.remove());
    renderGraphPickedBar(state);
    const node = state.nodes.find((entry) => entry.id === state.selectedNode);
    if (node === undefined)
        return;
    const box = state.boxes.get(node.id);
    if (box === undefined)
        return;
    const pop = graphElement("div", "graph-pop");
    placeGraphPopover(state, node, box, pop);
    const head = graphElement("div", "graph-pop-head");
    head.appendChild(graphElement("span", "graph-pop-kind", graphTriggerLabel(node)));
    const close = graphElement("button", "graph-pop-close", "✕");
    close.setAttribute("type", "button");
    close.setAttribute("aria-label", "Close");
    close.dataset["close"] = "1";
    head.appendChild(close);
    pop.appendChild(head);
    // A trigger always has two sides. Every other box grows one once a trial
    // has passed through it, and loses it again when that trial is replaced.
    const tested = node.trigger !== null || graphShareOf(state, node) !== null;
    const showing = tested ? state.tab : "settings";
    if (tested)
        pop.appendChild(graphPopTabs(node, showing));
    if (showing === "test") {
        pop.classList.add("is-wide");
        pop.appendChild(graphTrialBody(state, node));
    }
    else {
        pop.appendChild(graphNodeForm(state, node));
    }
    state.parts.layer.appendChild(pop);
}
/** The two sides of a trigger: what it does, and what it would do. */
function graphPopTabs(node, showing) {
    const strip = graphElement("div", "graph-pop-tabs");
    for (const [name, label] of [["settings", "Settings"], ["test", "Test"]]) {
        const tab = graphElement("button", "graph-pop-tab", label);
        tab.setAttribute("type", "button");
        tab.dataset["tab"] = name;
        tab.dataset["for"] = String(node.id);
        if (name === showing)
            tab.classList.add("is-on");
        strip.appendChild(tab);
    }
    return strip;
}
/** Whether opening this Test tab has to run a trial, or only show one.
 *
 *  Only a trigger can start one. Every other box has a Test tab because a
 *  trial already came through it, and asking the server to test a filter is
 *  refused — which used to take the whole trial down with it. */
function graphTabNeedsRun(box, trial, wanted) {
    if (wanted !== "test" || box === undefined || box.trigger === null)
        return false;
    return trial === null || trial.node !== box.id;
}
/** This box's share of the last trial, if it had one. */
function graphShareOf(state, node) {
    var _a;
    var _b;
    return (_b = (_a = state.trial) === null || _a === void 0 ? void 0 : _a.boxes.get(node.id)) !== null && _b !== void 0 ? _b : null;
}
/** What this box would do, inside the box itself. */
function graphTrialBody(state, node) {
    const sheet = graphElement("div", "graph-sheet");
    const trial = state.trial;
    if (trial === null || trial.asking) {
        sheet.appendChild(graphElement("p", "hint", "Working it out…"));
        return sheet;
    }
    const share = graphShareOf(state, node);
    if (share === null) {
        sheet.appendChild(graphElement("p", "hint", "The last test did not come through this node. Run one from a trigger."));
        return sheet;
    }
    sheet.appendChild(graphElement("p", "hint", "If it ran now. Nothing here has been added or written."));
    // A feed is where things arrive; everywhere else is somewhere they pass.
    sheet.appendChild(graphJudgedList(node.kind === "feed" ? "Would land" : "Gets through", share.through, "through", true));
    if (share.held.length > 0) {
        sheet.appendChild(graphJudgedList("Held back", share.held, "held", true));
    }
    return sheet;
}
/** How many are picked, and the one thing to do with several at once.
 *
 *  Over the canvas rather than beside a node, because it is not about any one
 *  of them. */
function renderGraphPickedBar(state) {
    var _a;
    const bar = (_a = state.parts.canvas
        .closest(".graph-panel")) === null || _a === void 0 ? void 0 : _a.querySelector("[data-graph-picked]");
    if (!bar)
        return;
    bar.hidden = state.picked.size < 2;
    if (bar.hidden)
        return;
    bar.textContent = "";
    bar.appendChild(graphElement("span", "", `${state.picked.size} picked`));
    const remove = graphElement("button", "btn btn-danger", "Remove");
    remove.setAttribute("type", "button");
    remove.dataset["removePicked"] = "1";
    bar.appendChild(remove);
}
/** Move the open panel to wherever its node is now.
 *
 *  Not only the node being dragged: a group takes what it surrounds with it,
 *  and a selection takes the rest of itself, so the open one may be moving
 *  without being the one under the pointer. */
function keepGraphPopoverWithItsNode(state) {
    const open = state.nodes.find((entry) => entry.id === state.selectedNode);
    if (open === undefined)
        return;
    const box = state.boxes.get(open.id);
    if (box !== undefined)
        placeGraphPopover(state, open, box);
}
/** Put the open box beside the box it belongs to, and keep it there.
 *
 *  Called again on every frame of a drag: a detail panel that stayed behind
 *  while its box moved away would be pointing at nothing. */
function placeGraphPopover(state, node, box, pop) {
    const panel = pop !== null && pop !== void 0 ? pop : state.parts.layer.querySelector(".graph-pop");
    if (!panel)
        return;
    panel.style.left = `${node.x + box.offsetWidth + 18}px`;
    panel.style.top = `${node.y}px`;
}
/** One form per box. Every kind has a name; what else it has depends. */
function graphNodeForm(state, node) {
    const form = document.createElement("form");
    form.className = "graph-form";
    form.dataset["save"] = String(node.id);
    // Says this form carried the switch, so the server can tell an unticked box
    // from a form that never showed one. Without it, an unticked box and an
    // absent one look the same and nothing could ever be switched off.
    const carried = document.createElement("input");
    carried.type = "hidden";
    carried.name = "box_form";
    carried.value = "1";
    form.appendChild(carried);
    form.appendChild(graphActive(node));
    const name = document.createElement("input");
    name.type = "text";
    name.name = "label";
    name.value = node.title;
    form.appendChild(graphLabelled("Name", name));
    if (node.kind === "group")
        graphGroupFields(form, node);
    // Conditions first: an Order piece carries a sort as well, and a plugin's
    // condition is a piece as well, so the narrowest answer has to be asked
    // before the broad ones.
    else if (node.condition !== null)
        graphConditionFields(form, node, node.condition);
    else if (node.kind === "rule")
        graphPluginFields(form, node);
    else if (node.stamp !== null)
        graphStampFields(form, node);
    else if (node.piece !== null)
        graphPieceFields(form, node);
    else if (node.store !== null)
        graphStoreFields(form, node.store);
    else if (node.kind === "source")
        graphChannelFields(state, form, node);
    else if (node.kind === "feed")
        graphFeedFields(form, node);
    else if (node.trigger !== null)
        graphTriggerFields(form, node);
    else
        graphFilterFields(form, node);
    const buttons = graphElement("div", "graph-form-buttons");
    const save = graphElement("button", "btn btn-primary", "Save");
    save.setAttribute("type", "submit");
    buttons.appendChild(save);
    if (node.trigger !== null) {
        const fire = graphElement("button", "btn btn-quiet", "Run now");
        fire.setAttribute("type", "button");
        fire.dataset["fire"] = String(node.id);
        buttons.appendChild(fire);
        const back = graphElement("button", "btn btn-quiet", "Backfill");
        back.setAttribute("type", "button");
        back.title = "Take everything these feeds still list, not only what is new";
        back.dataset["backfill"] = String(node.id);
        buttons.appendChild(back);
        const test = graphElement("button", "btn btn-quiet", "Test");
        test.setAttribute("type", "button");
        test.dataset["test"] = String(node.id);
        buttons.appendChild(test);
    }
    if (node.detail !== null) {
        const open = document.createElement("a");
        open.className = "btn btn-quiet";
        open.href = node.detail;
        open.textContent = "Open";
        buttons.appendChild(open);
    }
    if (node.kind === "filter") {
        const seen = graphElement("button", "btn btn-quiet", "What it catches");
        seen.setAttribute("type", "button");
        seen.dataset["filtered"] = String(node.id);
        buttons.appendChild(seen);
    }
    if (node.piece !== null && node.piece.under !== null) {
        const out = graphElement("button", "btn btn-quiet", "Take it out");
        out.setAttribute("type", "button");
        out.title = "Leave it on the canvas, slotted into nothing";
        out.dataset["unslot"] = String(node.id);
        buttons.appendChild(out);
    }
    const remove = graphElement("button", "btn btn-danger", "Remove");
    remove.setAttribute("type", "button");
    remove.dataset["remove"] = String(node.id);
    remove.dataset["what"] = graphRemovalWarning(node);
    buttons.appendChild(remove);
    form.appendChild(buttons);
    if (state.busy)
        form.setAttribute("aria-busy", "true");
    // What the panel said before anybody typed in it. Read from the fields as
    // they were filled in, which is the saved state — so an undo puts back what
    // was saved rather than what was typed and abandoned.
    form.dataset["was"] = graphFormValues(form).toString();
    return form;
}
/** Take away everything picked, once it has been said out loud what that is.
 *
 *  One question for the lot rather than one each: a person removing four
 *  nodes has decided once, and asking four times is a way of being ignored. */
async function removeGraphPicked(state) {
    const going = state.nodes.filter((node) => state.picked.has(node.id));
    if (going.length === 0)
        return;
    const costly = going.filter((node) => graphRemovalWarning(node) !== "");
    const named = going.map((node) => node.title).join(", ");
    const asked = costly.length === 0
        ? `Remove ${going.length} node${going.length === 1 ? "" : "s"}? (${named})`
        : `Remove ${named}? The channels and feeds among them go too, with their history; anything already in a feed stays put.`;
    if (!(await askGraphSure(state, asked)))
        return;
    state.selectedNode = null;
    state.picked = new Set();
    for (const node of going) {
        await applyGraph(state, `/graph/nodes/${node.id}/delete`, new URLSearchParams());
    }
}
/** The switch every box has: whether it is doing anything at all.
 *
 *  A box that is off is drawn greyed, and a filter that is off stops the flow
 *  rather than passing everything — off means off, not "no opinion". */
function graphActive(node) {
    const row = graphElement("label", "graph-switch is-active");
    const box = document.createElement("input");
    box.type = "checkbox";
    box.name = "active";
    box.value = "1";
    box.checked = node.enabled;
    row.appendChild(box);
    row.appendChild(graphElement("span", "graph-switch-name", "Active"));
    if (!node.enabled && node.kind === "filter") {
        row.appendChild(graphElement("span", "graph-group-note", "nothing passes while it is off"));
    }
    return row;
}
/** What taking this box away costs, said before it is taken away. */
function graphRemovalWarning(node) {
    // Only where something is actually at stake. An empty source box names no
    // source, so taking it away costs nothing — and asking "its history goes
    // too" of a box with no history is a frightening question about nothing.
    if (node.kind === "source" && node.detail !== null) {
        return `Stop watching ${node.title}? Its history goes too; anything already in a feed stays put.`;
    }
    if (node.kind === "feed") {
        return `Remove the feed ${node.title}? What it collected inside De-Algo goes with it.`;
    }
    return "";
}
/** Pick one of the sources already watched, out of however many there are.
 *
 *  A search box above a real select rather than a list built from scratch: the
 *  select keeps the keyboard, the form and the screen reader it already had,
 *  and the box only decides which options are in it. */
function graphSourcePicker(state, form, kind) {
    // Only sources of this box's own kind. A Subreddit box that offered a
    // YouTube channel would be offering something it could not then be.
    const offered = kind === "" ? state.sources : state.sources.filter((one) => one.kind === kind);
    if (offered.length === 0)
        return;
    const search = document.createElement("input");
    search.type = "search";
    search.placeholder = "Search sources…";
    // No name: this narrows the list, it is not part of the answer.
    search.autocomplete = "off";
    const pick = document.createElement("select");
    pick.name = "source_pk";
    pick.size = Math.min(6, offered.length + 1);
    const fill = () => {
        const chosen = pick.value;
        pick.textContent = "";
        const none = document.createElement("option");
        none.value = "";
        none.textContent = "— or add one below —";
        pick.appendChild(none);
        const matching = offered.filter((source) => graphMatches(source.title, search.value));
        for (const source of matching) {
            const option = document.createElement("option");
            option.value = String(source.id);
            option.textContent = source.title;
            option.selected = option.value === chosen;
            pick.appendChild(option);
        }
        if (matching.length === 0 && search.value.trim() !== "") {
            const nothing = document.createElement("option");
            nothing.value = "";
            nothing.disabled = true;
            nothing.textContent = `Nothing matches “${search.value.trim()}”`;
            pick.appendChild(nothing);
        }
    };
    search.addEventListener("input", fill);
    fill();
    const holder = graphElement("div", "graph-picker");
    holder.appendChild(search);
    holder.appendChild(pick);
    form.appendChild(graphLabelled("One of your sources", holder));
}
/** Whether a name answers to what has been typed.
 *
 *  Every word, in any order, part of a word counting — the same as searching
 *  anywhere else here, so one habit serves the whole app. */
function graphMatches(name, query) {
    const terms = query.toLowerCase().split(/\s+/).filter((term) => term !== "");
    const against = name.toLowerCase();
    return terms.every((term) => against.includes(term));
}
/** A box that marks what passes through it rather than narrowing it. */
function graphStampFields(form, node) {
    var _a;
    var _b;
    if (node.kind === "tag") {
        const named = document.createElement("input");
        named.type = "text";
        named.name = "marks";
        named.value = (_b = (_a = node.stamp) === null || _a === void 0 ? void 0 : _a.marks) !== null && _b !== void 0 ? _b : "";
        named.placeholder = "long reads";
        form.appendChild(graphLabelled("Marks it", named));
        form.appendChild(graphElement("p", "hint", "Everything through this box carries the tag from here on. A Filter box later in the path can ask for it."));
        return;
    }
    form.appendChild(graphElement("p", "hint", node.kind === "decay"
        ? "Slot a Timer under this to say how long you get with each item in Focus. A Lock under it makes that time one you cannot pause."
        : "Slot a Timer under this to say how long an item stays in the feed, counted from when it arrives. After that it is taken out — it stays in your history and in any other feed that said nothing about expiry."));
}
/** One condition. Exactly one thing to fill in, because that is what makes
 *  it one condition: a box narrowing three ways is three pieces. */
function graphConditionFields(form, node, said) {
    var _a;
    if (((_a = node.piece) === null || _a === void 0 ? void 0 : _a.under) == null) {
        const where = said.under === "sort" ? "a Sort box" : "a Filter box";
        form.appendChild(graphElement("p", "hint", `Loose on the canvas. Drop it on ${where} to slot it in.`));
    }
    if (said.field === "order") {
        if (node.sort !== null)
            graphSortFields(form, node.sort);
        return;
    }
    const field = document.createElement("input");
    field.type = said.field === "text" ? "text" : "number";
    field.name = "value";
    field.value = said.value;
    field.placeholder = said.field === "text" ? "" : "no limit";
    if (said.field !== "text")
        field.min = "1";
    if (said.field === "duration") {
        // A number and what it counts, side by side: "longer than 2 minutes" is
        // one answer, and splitting it across two rows makes it read as two.
        const unit = document.createElement("select");
        unit.name = "value_unit";
        for (const choice of said.units) {
            const option = document.createElement("option");
            option.value = choice;
            option.textContent = choice;
            option.selected = choice === said.unit;
            unit.appendChild(option);
        }
        const pair = graphElement("div", "graph-pair");
        pair.appendChild(field);
        pair.appendChild(unit);
        form.appendChild(graphLabelled(said.asks, pair));
    }
    else {
        form.appendChild(graphLabelled(said.asks, field));
    }
    if (said.blurb !== "")
        form.appendChild(graphElement("p", "hint", said.blurb));
}
/** An augmentation. One field each: a Timer says how long, a Reset says
 *  when you get another. */
function graphPieceFields(form, node) {
    const piece = node.piece;
    if (piece === null)
        return;
    if (node.kind === "lock") {
        form.appendChild(graphElement("p", "hint", piece.under === null
            ? "Loose on the canvas. Drop it on a Decay box to make its time one you cannot pause."
            : "The Timer above this cannot be paused. The point of it is a stretch that runs whether you are looking or not."));
        return;
    }
    if (node.kind === "alive") {
        const pair = graphElement("div", "graph-times");
        for (const [name, value, label] of [
            ["alive_from", piece.from, "From"],
            ["alive_to", piece.to, "To"],
        ]) {
            const when = document.createElement("input");
            when.type = "time";
            when.name = name;
            when.value = value;
            pair.appendChild(graphLabelled(label, when));
        }
        form.appendChild(pair);
    }
    else if (node.kind === "timer") {
        const amount = document.createElement("input");
        amount.type = "number";
        amount.name = "duration_minutes";
        amount.min = "1";
        amount.value = String(piece.every.amount);
        const unit = document.createElement("select");
        unit.name = "every_unit";
        for (const choice of piece.every.units) {
            const option = document.createElement("option");
            option.value = choice.name;
            option.textContent = choice.label;
            option.selected = choice.name === piece.every.unit;
            unit.appendChild(option);
        }
        const pair = graphElement("div", "graph-pair");
        pair.appendChild(amount);
        pair.appendChild(unit);
        // What the amount is an amount of depends on the box it is slotted
        // into: a sitting, a stretch with one item, or how long that item stays.
        form.appendChild(graphLabelled("How long", pair));
    }
    else {
        const when = document.createElement("input");
        when.type = "text";
        when.name = "cron";
        when.value = piece.cron;
        when.placeholder = "0 9 * * *";
        form.appendChild(graphLabelled("Comes round on", when));
    }
    form.appendChild(graphElement("p", "hint", piece.under === null
        ? "Loose on the canvas. Drop it on a box to slot it in — it changes what that box does."
        : node.kind === "alive"
            ? "Read on the clock, in UTC, and it narrows whatever else is slotted in: a sitting with time left on it is still no good outside these hours. An end before its start runs through midnight. Both the same means any time of day."
            : node.kind === "timer"
                ? "The clock starts when you open the feed, not at some hour of the day. Without a Reset under the same box you get one sitting and no more."
                : "Each time this comes round the Timer starts again. Several Resets are several chances to read."));
}
/** A Deposit or a Withdraw box: which repository, and how much to pull.
 *
 *  The name is the whole of what joins the two ends, so it is the first
 *  field on both and says what it is for. */
function graphStoreFields(form, store) {
    const named = document.createElement("input");
    named.type = "text";
    named.name = "repository";
    named.value = store.name;
    named.placeholder = "News";
    form.appendChild(graphLabelled("Repository", named));
    if (store.pulls) {
        const many = document.createElement("input");
        many.type = "number";
        many.name = "takes_how_many";
        many.min = "1";
        many.value = store.takes > 0 ? String(store.takes) : "";
        many.placeholder = "everything waiting";
        form.appendChild(graphLabelled("How many to take", many));
    }
    const group = graphElement("div", "graph-group");
    group.appendChild(graphElement("span", "graph-group-name", "Waiting"));
    group.appendChild(graphElement("span", "graph-group-note", store.name === ""
        ? "Give it a name. Two boxes only share a repository when they share its name."
        : `${store.waiting} item${store.waiting === 1 ? "" : "s"} in ${store.name}.`));
    form.appendChild(group);
    form.appendChild(graphElement("p", "hint", store.pulls
        ? "Wire a trigger to this box to say when to pull. What comes out goes down whatever is wired on, oldest first, and is taken out of the repository."
        : "Everything wired in ends here and waits. Nothing reaches a feed through this box — a Withdraw box with the same name is what lets it out."));
}
function graphChannelFields(state, form, node) {
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
            form.appendChild(graphElement("p", "hint", `Nothing here provides ${kind} sources any more. Its plugin may be switched off on the Plugins page. Point this box at something already watched, or delete it.`));
            return;
        }
        if (kind === "") {
            // A box from before sources had kinds. There is no longer a way to
            // make one, and no way to tell what it was meant to be.
            form.appendChild(graphElement("p", "hint", "This box was made before sources had kinds. Point it at something already watched, or delete it and drag out the kind you want."));
            return;
        }
        const handle = document.createElement("input");
        handle.type = "text";
        handle.name = "handle";
        handle.placeholder = asks === null ? "" : asks.example;
        form.appendChild(graphLabelled(state.sources.length > 0 ? "Or somewhere new" : "Where to watch", handle));
        const backfill = document.createElement("input");
        backfill.type = "number";
        backfill.name = "backfill";
        backfill.min = "0";
        backfill.placeholder = "the newest few";
        form.appendChild(graphLabelled("How far back, in days", backfill));
        form.appendChild(graphElement("p", "hint", `${asks === null ? "" : asks.label}: ${asks === null ? "" : asks.example}. A source stays paused until it is wired to a feed.`));
        return;
    }
    const channel = node.channel;
    if (channel === null)
        return;
    form.appendChild(graphTakes(channel));
    form.appendChild(graphChecks(node, channel));
    if (!channel.youtube)
        form.appendChild(graphMirror(channel));
    form.appendChild(graphChannelCounts(node, channel));
}
/** The four switches, and whether the channel is watched at all.
 *
 *  Videos, Shorts, broadcasts and community posts are distinctions YouTube
 *  draws. Everywhere else publishes one kind of thing, so the box says so
 *  rather than offering four switches that would decide nothing. */
function graphTakes(channel) {
    const group = graphElement("div", "graph-group");
    group.appendChild(graphElement("span", "graph-group-name", "Takes"));
    if (!channel.youtube) {
        group.appendChild(graphElement("span", "graph-group-note", `Everything ${channel.source} publishes to this feed. Filter boxes wired after this one are what narrow it.`));
        return group;
    }
    const switches = graphElement("div", "graph-switches");
    for (const [name, label] of [
        ["videos", "Videos"],
        ["shorts", "Shorts"],
        ["live", "Live"],
        ["posts", "Posts"],
    ]) {
        const row = graphElement("label", "graph-switch");
        const tick = document.createElement("input");
        tick.type = "checkbox";
        tick.name = `takes_${name}`;
        tick.value = "1";
        tick.checked = channel.takes[name] === true;
        row.appendChild(tick);
        row.appendChild(graphElement("span", "graph-switch-name", label));
        switches.appendChild(row);
    }
    group.appendChild(switches);
    return group;
}
/** A plugin box's own fields, exactly as its plugin declared them.
 *
 *  The host knows none of these names. They are sent back under the names
 *  the plugin chose and stored as they came, because a column per field is
 *  not a thing a plugin can ask for. */
function graphPluginFields(form, node) {
    var _a;
    const box = node.plugin;
    if (box === null)
        return;
    if (box.missing !== null) {
        form.appendChild(graphElement("p", "hint", `This condition belongs to “${box.missing}”, which is not loaded. It narrows nothing while that is true. Switch the plugin on under Admin → Plugins, or take the piece off the canvas.`));
        return;
    }
    if (box.blurb !== "")
        form.appendChild(graphElement("p", "hint", box.blurb));
    for (const one of box.fields) {
        const field = document.createElement("input");
        field.type = one.type === "number" ? "number" : "text";
        // Prefixed, so a plugin cannot name a field "active" or "label" and
        // quietly take over one of the form's own.
        field.name = `plugin_${one.name}`;
        field.value = one.value;
        if (one.placeholder !== "")
            field.placeholder = one.placeholder;
        form.appendChild(graphLabelled(one.label, field));
    }
    if (((_a = node.piece) === null || _a === void 0 ? void 0 : _a.under) == null) {
        form.appendChild(graphElement("p", "hint", "Loose on the canvas. Drop it on a Filter box to slot it in."));
    }
    if (box.fields.length === 0) {
        form.appendChild(graphElement("p", "hint", "Nothing to set: it judges on its own."));
    }
}
/** Somewhere else to read the same feed, for a host that rations us.
 *
 *  Offered only where it can help: YouTube's feed has never turned anybody
 *  away, and a box full of fields that do nothing is worse than no box.
 *  Tried only when the source itself refuses, so the source stays the source. */
function graphMirror(channel) {
    var _a, _b, _c;
    const group = graphElement("div", "graph-group");
    group.appendChild(graphElement("span", "graph-group-name", "If it will not have us"));
    const field = document.createElement("input");
    field.type = "url";
    field.name = "mirror_url";
    field.placeholder = (_a = channel.mirrorHint) !== null && _a !== void 0 ? _a : "https://…";
    field.value = (_b = channel.mirror) !== null && _b !== void 0 ? _b : "";
    group.appendChild(graphLabelled("Read it from here instead", field));
    // Offered rather than filled in: leaning on somebody else's service is the
    // reader's call, so the suggestion sits there until it is taken.
    if (channel.mirrorHint !== null && ((_c = channel.mirror) !== null && _c !== void 0 ? _c : "") === "") {
        const take = graphElement("button", "btn btn-quiet", "Use Open RSS");
        take.setAttribute("type", "button");
        take.title = channel.mirrorHint;
        take.addEventListener("click", () => {
            var _a;
            field.value = (_a = channel.mirrorHint) !== null && _a !== void 0 ? _a : "";
            take.remove();
        });
        group.appendChild(take);
    }
    group.appendChild(graphElement("span", "graph-group-note", `Used only when ${graphHostOf(channel.feedUrl)} refuses or rations us — never in its place. A mirror is somebody else's copy of the same feed.`));
    return group;
}
/** The host of an address, for saying which one is doing the refusing. */
function graphHostOf(url) {
    try {
        return new URL(url).hostname;
    }
    catch (_a) {
        return "the source";
    }
}
/** When it was last polled, and what decides when it next will be.
 *
 *  Nothing to set here: a trigger wired into this box decides that, and an
 *  interval offered in two places is an interval that will disagree with
 *  itself. The channel's own gap still applies while no trigger is wired, and
 *  the line below says which of the two is in force. */
function graphChecks(node, channel) {
    const group = graphElement("div", "graph-group");
    group.appendChild(graphElement("span", "graph-group-name", "Checks"));
    if (node.polled !== null)
        group.appendChild(graphElement("span", "graph-group-note", node.polled));
    if (channel.checked !== null) {
        group.appendChild(graphElement("span", "graph-group-note", `Last looked at ${graphWhen(channel.checked)}.`));
    }
    return group;
}
/** An instant on the reader's own clock, as near or far as it actually is. */
function graphWhen(instant) {
    const when = new Date(instant);
    const minutes = Math.round((when.getTime() - Date.now()) / 60000);
    const size = Math.abs(minutes);
    const [divisor, unit] = size < 60 ? [1, "minute"] : size < 1440 ? [60, "hour"] : [1440, "day"];
    const count = Math.max(1, Math.round(size / divisor));
    const plural = count === 1 ? "" : "s";
    return minutes < 0 ? `${count} ${unit}${plural} ago` : `in ${count} ${unit}${plural}`;
}
/** What it has put into its feeds. Not which feeds: the wires say that, and
 *  saying it twice invites the two to disagree. */
function graphChannelCounts(node, channel) {
    const group = graphElement("div", "graph-group");
    group.appendChild(graphElement("span", "graph-group-name", "Videos"));
    const counts = graphElement("div", "graph-counts");
    for (const [count, name, status] of [
        [channel.placed, "placed", "added"],
        [channel.pending, "pending", "pending"],
    ]) {
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
function graphChannelId(node) {
    var _a, _b;
    return (_b = ((_a = node.detail) !== null && _a !== void 0 ? _a : "").split("/").pop()) !== null && _b !== void 0 ? _b : "";
}
function graphFeedWindows(form, feed) {
    if (feed.windows.length === 0)
        return;
    const group = graphElement("div", "graph-group");
    group.appendChild(graphElement("span", "graph-group-name", "Reading"));
    for (const window of feed.windows) {
        group.appendChild(graphElement("span", "graph-group-note", window));
    }
    group.appendChild(graphElement("span", feed.open ? "graph-group-note is-open" : "graph-group-note is-shut", feed.open ? "Open now." : "Shut now."));
    form.appendChild(group);
}
function graphFeedFields(form, node) {
    const feed = node.feed;
    if (feed === null) {
        form.appendChild(graphElement("p", "hint", "This feed is no longer here."));
        return;
    }
    const group = graphElement("div", "graph-group");
    group.appendChild(graphElement("span", "graph-group-name", "Filling"));
    for (const [label, name, value, hint] of [
        [
            "Max size",
            "max_items",
            feed.maxItems,
            "0 keeps everything. Above that, the oldest go as new ones arrive, so the feed is a rolling window rather than one that grows for ever.",
        ],
        [
            "Most per sync",
            "feed_max_per_run",
            feed.maxPerRun,
            "Anything held back is queued for the next run rather than dropped — useful for spreading a tight API quota across several feeds.",
        ],
    ]) {
        const field = document.createElement("input");
        field.type = "number";
        field.min = "0";
        field.name = name;
        field.value = String(value);
        group.appendChild(graphLabelled(label, field));
        group.appendChild(graphElement("span", "graph-group-note", hint));
    }
    form.appendChild(group);
    graphFeedWindows(form, feed);
    form.appendChild(graphElement("p", "hint", `${node.note}. Everything wired in ends up here.`));
}
function graphTriggerFields(form, node) {
    var _a, _b, _c;
    var _d, _e, _f, _g;
    // Wired to a feed, it opens a window rather than setting something off, and
    // the one thing it needs that it does not otherwise is how long.
    if (((_a = node.trigger) === null || _a === void 0 ? void 0 : _a.opens) === true) {
        const window = document.createElement("input");
        window.type = "number";
        window.name = "duration_minutes";
        window.min = "1";
        window.value = String((_d = node.trigger.duration) !== null && _d !== void 0 ? _d : 30);
        form.appendChild(graphLabelled("Open for, in minutes", window));
    }
    if (((_b = node.trigger) === null || _b === void 0 ? void 0 : _b.kind) === "schedule") {
        const cron = document.createElement("input");
        cron.type = "text";
        cron.name = "cron";
        cron.value = (_e = node.trigger.cron) !== null && _e !== void 0 ? _e : "0 9 * * *";
        cron.placeholder = "0 9 * * *";
        cron.spellcheck = false;
        form.appendChild(graphLabelled("Cron, in UTC", cron));
        form.appendChild(graphElement("p", "hint", `minute hour day month weekday — ${graphNextFiring(node)}`));
        return;
    }
    const said = (_c = node.trigger) === null || _c === void 0 ? void 0 : _c.every;
    const amount = document.createElement("input");
    amount.type = "number";
    amount.name = "every_minutes";
    amount.min = "1";
    amount.value = String((_f = said === null || said === void 0 ? void 0 : said.amount) !== null && _f !== void 0 ? _f : 60);
    const unit = document.createElement("select");
    unit.name = "every_unit";
    for (const choice of (_g = said === null || said === void 0 ? void 0 : said.units) !== null && _g !== void 0 ? _g : []) {
        const option = document.createElement("option");
        option.value = choice.name;
        option.textContent = choice.label;
        option.selected = choice.name === (said === null || said === void 0 ? void 0 : said.unit);
        unit.appendChild(option);
    }
    // The number and what it counts, side by side: "every 2 hours" is one
    // answer, and splitting it across two rows makes it read as two.
    const pair = graphElement("div", "graph-pair");
    pair.appendChild(amount);
    pair.appendChild(unit);
    form.appendChild(graphLabelled("Poll every", pair));
}
/** When a schedule next comes round, on the reader's own clock. */
function graphNextFiring(node) {
    var _a;
    var _b;
    const next = (_b = (_a = node.trigger) === null || _a === void 0 ? void 0 : _a.next) !== null && _b !== void 0 ? _b : null;
    if (next === null)
        return "it does not come round at all";
    return `next ${new Date(next).toLocaleString()}`;
}
/** A group's own panel: what it is called, and a way to hand it on. */
function graphGroupFields(form, node) {
    const give = document.createElement("a");
    give.className = "btn btn-quiet";
    give.href = `/graph/nodes/${node.id}/export`;
    give.textContent = "Export";
    give.title = "Save this group as a file to give to somebody else";
    form.appendChild(give);
    form.appendChild(graphElement("p", "hint", "Everything inside the rectangle travels with it, and goes into the file. Channels travel as their YouTube ids; feeds travel as names, and are made afresh by whoever loads them."));
}
/** What to put the batch in order of, and which way round. */
function graphSortFields(form, sort) {
    const by = document.createElement("select");
    by.name = "sort_by";
    for (const key of sort.keys) {
        const option = document.createElement("option");
        option.value = key.name;
        option.textContent = key.label;
        option.selected = key.name === sort.by;
        by.appendChild(option);
    }
    form.appendChild(graphLabelled("Order by", by));
    const way = document.createElement("select");
    way.name = "sort_dir";
    for (const value of ["desc", "asc"]) {
        const option = document.createElement("option");
        option.value = value;
        option.selected = (value === "desc") === sort.desc;
        way.appendChild(option);
    }
    // "Most first" means one thing for a duration and another for a date, so
    // the ends are named after what is being sorted, and renamed when that
    // changes rather than leaving the reader to work out which end is which.
    nameGraphSortEnds(way, sort, sort.by);
    by.addEventListener("change", () => nameGraphSortEnds(way, sort, by.value));
    form.appendChild(graphLabelled("Which end first", way));
    form.appendChild(graphElement("p", "hint", "The order things are added to the feed in. Views and likes are read when the details are fetched, so a video nobody has looked up yet sorts last."));
}
/** Label the two ends for whatever is being sorted by. */
function nameGraphSortEnds(way, sort, by) {
    const key = sort.keys.find((entry) => entry.name === by);
    const [first, last] = key === undefined ? ["Most first", "Least first"] : [key.first, key.last];
    const options = way.options;
    if (options.length < 2)
        return;
    const falling = options[0];
    const rising = options[1];
    if (falling !== undefined)
        falling.textContent = first;
    if (rising !== undefined)
        rising.textContent = last;
}
/** A Filter or a Sort box. Neither carries a rule of its own any more: what
 *  a box narrows by is the conditions slotted under it, one piece per
 *  condition, so the canvas says what a box does without being opened. */
function graphFilterFields(form, node) {
    form.appendChild(graphElement("p", "hint", node.kind === "sort"
        ? "Slot an Order piece under this to say what to put the batch in order by. Without one it orders nothing."
        : "Slot conditions under this — Title has, Longer than, At most — one piece each. Everything they all agree on gets past. Without any it narrows nothing."));
}
// -- picking things up -----------------------------------------------------
/** The node a pointer is on, whatever shape that node is drawn as.
 *
 *  A group is a rectangle rather than a box, so it carries its own class —
 *  and looking only for the box's meant a group could not be pressed at all:
 *  not moved, not resized, not opened, and so not removed either. */
function graphNodeIdFrom(target) {
    if (!(target instanceof Element))
        return null;
    const box = target.closest(".graph-node, .graph-group-box");
    const raw = box === null || box === void 0 ? void 0 : box.dataset["node"];
    return raw === undefined ? null : Number(raw);
}
/** The wire under the pointer, if the pointer is on one. */
function graphWireIdFrom(target) {
    var _a;
    var _b;
    if (!(target instanceof Element))
        return null;
    return (_b = (_a = target.closest("[data-wire]")) === null || _a === void 0 ? void 0 : _a.getAttribute("data-wire")) !== null && _b !== void 0 ? _b : null;
}
/** Where a pointer is in the drawing, whatever the canvas is panned to. */
function pointInGraph(state, event) {
    const frame = state.parts.canvas.getBoundingClientRect();
    return {
        x: (event.clientX - frame.left - state.panX) / state.zoom,
        y: (event.clientY - frame.top - state.panY) / state.zoom,
    };
}
/** The fields every drag shares, whatever kind it turns out to be. */
function graphGrab(state, event) {
    return {
        kind: "pan",
        nodeId: 0,
        pressed: 0,
        pointerId: event.pointerId,
        grabX: 0,
        grabY: 0,
        fromX: event.clientX,
        fromY: event.clientY,
        scrollX: state.panX,
        scrollY: state.panY,
        moved: false,
        startX: 0,
        startY: 0,
        carried: [],
    };
}
/** Whether the pointer has gone far enough that this is a drag and not a click.
 *
 *  A few pixels of travel while pressing is normal, and without this a box
 *  could not be picked with a mouse that is not perfectly still. */
function graphMovedFar(drag, event) {
    return Math.abs(event.clientX - drag.fromX) > 3 || Math.abs(event.clientY - drag.fromY) > 3;
}
function beginGraphPan(state, event) {
    state.drag = graphGrab(state, event);
    state.parts.canvas.classList.add("is-panning");
}
function beginGraphWire(state, event, nodeId) {
    state.drag = Object.assign(Object.assign({}, graphGrab(state, event)), { kind: "wire", nodeId });
    const from = graphPortPoint(state, nodeId, "out");
    if (from === null)
        return;
    state.ghost = graphSvgPath("graph-wire wire-ghost", graphCurve(from.x, from.y, from.x, from.y));
    state.parts.wires.appendChild(state.ghost);
}
function beginGraphMove(state, event, node, pressed) {
    var _a;
    const at = pointInGraph(state, event);
    state.drag = Object.assign(Object.assign({}, graphGrab(state, event)), { kind: "move", nodeId: node.id, pressed: pressed !== null && pressed !== void 0 ? pressed : node.id, grabX: at.x - node.x, grabY: at.y - node.y, startX: node.x, startY: node.y, 
        // What travels with it: what a group surrounds, or the rest of what is
        // picked. Their starting positions are noted here so each can be moved by
        // the same amount without asking again half-way through the drag.
        carried: graphTravelsWith(state, node).map((held) => ({
            node: held,
            x: held.x,
            y: held.y,
        })) });
    (_a = state.boxes.get(node.id)) === null || _a === void 0 ? void 0 : _a.classList.add("is-held");
}
/** What moves when this node moves.
 *
 *  A group takes what it surrounds. Anything else takes the rest of what is
 *  picked, so several nodes dragged by one of them keep their arrangement. */
function graphTravelsWith(state, node) {
    if (node.kind === "group")
        return graphSurrounded(state, node);
    if (!state.picked.has(node.id) || state.picked.size < 2)
        return [];
    return state.nodes.filter((entry) => entry.id !== node.id && state.picked.has(entry.id));
}
/** What a group surrounds, worked out the way the server works it out. */
function graphSurrounded(state, group) {
    var _a, _b;
    var _c, _d;
    if (group.kind !== "group")
        return [];
    const right = group.x + ((_c = (_a = group.size) === null || _a === void 0 ? void 0 : _a.width) !== null && _c !== void 0 ? _c : 520);
    const bottom = group.y + ((_d = (_b = group.size) === null || _b === void 0 ? void 0 : _b.height) !== null && _d !== void 0 ? _d : 300);
    return state.nodes.filter((node) => node.id !== group.id &&
        node.kind !== "group" &&
        node.x >= group.x &&
        node.x <= right &&
        node.y >= group.y &&
        node.y <= bottom);
}
/** Drag a box round the canvas; what it covers is what gets picked. */
function beginGraphPick(state, event) {
    const at = pointInGraph(state, event);
    state.drag = Object.assign(Object.assign({}, graphGrab(state, event)), { kind: "pick", startX: at.x, startY: at.y });
    const marquee = graphElement("div", "graph-marquee");
    marquee.style.left = `${at.x}px`;
    marquee.style.top = `${at.y}px`;
    state.parts.layer.appendChild(marquee);
}
/** The box being dragged, if one is. */
function graphMarquee(state) {
    return state.parts.layer.querySelector(".graph-marquee");
}
function beginGraphResize(state, event, node) {
    var _a, _b;
    var _c, _d;
    state.drag = Object.assign(Object.assign({}, graphGrab(state, event)), { kind: "resize", nodeId: node.id, grabX: (_c = (_a = node.size) === null || _a === void 0 ? void 0 : _a.width) !== null && _c !== void 0 ? _c : 520, grabY: (_d = (_b = node.size) === null || _b === void 0 ? void 0 : _b.height) !== null && _d !== void 0 ? _d : 300 });
}
function onGraphPointerDown(state, event) {
    if (event.button !== 0)
        return;
    const target = event.target;
    // The open box is a form: a click in it is meant for the field it landed
    // on, and must not reach the canvas, which would read it as a click on
    // empty space and close the very box being typed into.
    if (target instanceof Element && target.closest(".graph-pop"))
        return;
    // The palette sits over the canvas rather than on it. Pressing a fold, or
    // the space between rows, is not a press on the drawing underneath — and
    // taking it as one starts a pan and swallows the fold.
    if (target instanceof Element && target.closest(".graph-palette"))
        return;
    // Buttons and links inside the canvas do their own thing.
    if (target instanceof Element && target.closest("a, button"))
        return;
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
        if (event.shiftKey)
            beginGraphPick(state, event);
        else
            beginGraphPan(state, event);
        state.parts.canvas.setPointerCapture(event.pointerId);
        event.preventDefault();
        return;
    }
    let node = state.nodes.find((entry) => entry.id === nodeId);
    if (node === undefined)
        return;
    // A slotted piece travels with whatever it is slotted into: dragging one
    // drags the assembly, the way picking up a puzzle by a piece picks up the
    // part it belongs to. Its own position is worked out from its host's.
    while (node !== undefined && node.piece !== null && node.piece.under !== null) {
        const above = node.piece.under;
        node = state.nodes.find((entry) => entry.id === above);
    }
    if (node === undefined)
        return;
    const grabbed = node.id;
    // Shift on a node adds it to what is picked rather than replacing it — but
    // a group is a background, and shift over one means the same as shift over
    // the canvas: draw a box round what is inside it.
    if (event.shiftKey) {
        if (node.kind === "group") {
            beginGraphPick(state, event);
            state.parts.canvas.setPointerCapture(event.pointerId);
            event.preventDefault();
            return;
        }
        alsoPickGraphNode(state, grabbed);
        event.preventDefault();
        return;
    }
    const onGrip = target instanceof Element && target.closest("[data-grip]");
    const onPort = target instanceof Element && target.closest(".graph-port");
    if (onGrip)
        beginGraphResize(state, event, node);
    else if (onPort && onPort.dataset["port"] === "out")
        beginGraphWire(state, event, grabbed);
    else
        beginGraphMove(state, event, node, nodeId);
    state.parts.canvas.setPointerCapture(event.pointerId);
    event.preventDefault();
}
function onGraphPointerMove(state, event) {
    const drag = state.drag;
    if (drag === null || drag.pointerId !== event.pointerId)
        return;
    if (graphMovedFar(drag, event))
        drag.moved = true;
    if (drag.kind === "pan") {
        panGraph(state, drag.scrollX + (event.clientX - drag.fromX), drag.scrollY + (event.clientY - drag.fromY));
        return;
    }
    if (drag.kind === "move") {
        const held = state.nodes.find((one) => one.id === drag.nodeId);
        if (held !== undefined && held.piece !== null && held.piece.under === null) {
            markGraphSlotFor(state, event, held.id, held.kind);
        }
    }
    if (drag.kind === "pick") {
        const marquee = graphMarquee(state);
        if (marquee === null)
            return;
        const at = pointInGraph(state, event);
        marquee.style.left = `${Math.min(drag.startX, at.x)}px`;
        marquee.style.top = `${Math.min(drag.startY, at.y)}px`;
        marquee.style.width = `${Math.abs(at.x - drag.startX)}px`;
        marquee.style.height = `${Math.abs(at.y - drag.startY)}px`;
        return;
    }
    const at = pointInGraph(state, event);
    if (drag.kind === "resize") {
        const node = state.nodes.find((entry) => entry.id === drag.nodeId);
        const frame = state.boxes.get(drag.nodeId);
        if (node === undefined || frame === undefined || node.size === null)
            return;
        node.size.width = Math.max(200, Math.round(drag.grabX + (event.clientX - drag.fromX) / state.zoom));
        node.size.height = Math.max(140, Math.round(drag.grabY + (event.clientY - drag.fromY) / state.zoom));
        frame.style.width = `${node.size.width}px`;
        frame.style.height = `${node.size.height}px`;
        return;
    }
    if (drag.kind === "move") {
        const node = state.nodes.find((entry) => entry.id === drag.nodeId);
        const box = state.boxes.get(drag.nodeId);
        if (node === undefined || box === undefined)
            return;
        // No clamping: the canvas goes on in every direction, including back.
        node.x = Math.round(at.x - drag.grabX);
        node.y = Math.round(at.y - drag.grabY);
        box.style.left = `${node.x}px`;
        box.style.top = `${node.y}px`;
        // A group takes what it surrounds with it, by the same amount.
        const across = node.x - drag.startX;
        const down = node.y - drag.startY;
        for (const held of drag.carried) {
            held.node.x = held.x + across;
            held.node.y = held.y + down;
            const moved = state.boxes.get(held.node.id);
            if (moved !== undefined) {
                moved.style.left = `${held.node.x}px`;
                moved.style.top = `${held.node.y}px`;
            }
        }
        // Anything slotted under what moved travels with it. A piece has no
        // position of its own worth keeping — it is drawn from its host's — so
        // this works them all out again rather than shifting each by the delta,
        // and a chain three deep follows as readily as one piece.
        placeGraphPieces(state);
        // Whichever node is open, wherever it has just been moved to — by being
        // dragged itself, or by the group or selection that carried it.
        keepGraphPopoverWithItsNode(state);
        drawGraphWires(state);
        return;
    }
    const from = graphPortPoint(state, drag.nodeId, "out");
    if (from !== null && state.ghost !== null) {
        state.ghost.setAttribute("d", graphCurve(from.x, from.y, at.x, at.y));
    }
}
function graphDropTarget(event) {
    const under = document.elementFromPoint(event.clientX, event.clientY);
    return graphNodeIdFrom(under);
}
function onGraphPointerUp(state, event) {
    var _a, _b;
    const drag = state.drag;
    if (drag === null || drag.pointerId !== event.pointerId)
        return;
    state.drag = null;
    if (state.parts.canvas.hasPointerCapture(event.pointerId)) {
        state.parts.canvas.releasePointerCapture(event.pointerId);
    }
    if (drag.kind === "pan") {
        state.parts.canvas.classList.remove("is-panning");
        // A press on empty canvas that went nowhere is a click, and a click on
        // nothing is how a selection is put down.
        if (!drag.moved)
            clearGraphPick(state);
        return;
    }
    if (drag.kind === "pick") {
        const at = pointInGraph(state, event);
        (_a = graphMarquee(state)) === null || _a === void 0 ? void 0 : _a.remove();
        pickGraphInside(state, drag.startX, drag.startY, at.x, at.y);
        return;
    }
    if (drag.kind === "resize") {
        // grabX and grabY held the size it started at.
        const wasSize = { width: drag.grabX, height: drag.grabY };
        const nodeId = drag.nodeId;
        rememberGraphUndo(state, "the resize", async () => {
            const node = state.nodes.find((entry) => entry.id === nodeId);
            if (node === undefined || node.size === null)
                return;
            node.size.width = wasSize.width;
            node.size.height = wasSize.height;
            renderGraph(state);
            await saveGraphSize(state, nodeId);
        });
        void saveGraphSize(state, nodeId);
        return;
    }
    if (drag.kind === "move") {
        (_b = state.boxes.get(drag.nodeId)) === null || _b === void 0 ? void 0 : _b.classList.remove("is-held");
        hideGraphSlot(state);
        // A loose piece dragged onto a slot goes into it. The other way a piece
        // gets slotted in: one already lying on the canvas could otherwise only
        // be deleted and dragged out of the palette again.
        const loose = state.nodes.find((one) => one.id === drag.nodeId);
        if (drag.moved && loose !== undefined && loose.piece !== null && loose.piece.under === null) {
            const slot = graphSlotFor(state, event, loose.kind);
            if (slot !== null && slot.under !== loose.id) {
                void applyGraph(state, `/graph/nodes/${loose.id}/attach`, new URLSearchParams({ under: String(slot.under) }));
                return;
            }
        }
        if (!drag.moved) {
            // The box that was pressed, not the one that was dragged: pressing a
            // augmentation opens that augmentation, even though dragging it moves
            // assembly it is part of.
            pickGraphNode(state, drag.pressed);
            return;
        }
        const nodeId = drag.nodeId;
        const wasAt = [
            { id: nodeId, x: drag.startX, y: drag.startY },
            ...drag.carried.map((held) => ({
                id: held.node.id,
                x: held.x,
                y: held.y,
            })),
        ];
        rememberGraphUndo(state, "the move", async () => {
            for (const was of wasAt) {
                const node = state.nodes.find((entry) => entry.id === was.id);
                if (node === undefined)
                    continue;
                node.x = was.x;
                node.y = was.y;
            }
            renderGraph(state);
            await Promise.all(wasAt.map((was) => saveGraphMove(state, was.id)));
        });
        // A group moves its contents server-side, in one call. Anything else that
        // travelled moved on its own, and has to say so on its own.
        void saveGraphMove(state, nodeId);
        if (!graphIsGroup(state, nodeId)) {
            for (const held of drag.carried)
                void saveGraphMove(state, held.node.id);
        }
        return;
    }
    if (state.ghost !== null) {
        state.ghost.remove();
        state.ghost = null;
    }
    const target = graphDropTarget(event);
    if (target === null || target === drag.nodeId)
        return;
    void wireGraphNodes(state, drag.nodeId, target);
}
/** Wire one node to another, and remember how to take it out again. */
async function wireGraphNodes(state, from, to) {
    const before = state.wires;
    const made = await applyGraph(state, "/graph/connect", new URLSearchParams({ source: String(from), target: String(to) }));
    if (!made)
        return;
    const fresh = graphWireAdded(before, state.wires);
    if (fresh === null)
        return;
    rememberGraphUndo(state, "the wire you drew", async () => {
        await applyGraph(state, "/graph/disconnect", new URLSearchParams({ wire: fresh }));
    });
}
/** Pick everything the dragged box covered. */
function pickGraphInside(state, fromX, fromY, toX, toY) {
    var _a;
    const left = Math.min(fromX, toX);
    const right = Math.max(fromX, toX);
    const top = Math.min(fromY, toY);
    const bottom = Math.max(fromY, toY);
    state.picked = new Set(state.nodes
        .filter((node) => node.x >= left && node.x <= right && node.y >= top && node.y <= bottom)
        .map((node) => node.id));
    state.selectedNode = state.picked.size === 1 ? (_a = [...state.picked][0]) !== null && _a !== void 0 ? _a : null : null;
    renderGraph(state);
}
async function saveGraphMove(state, nodeId) {
    const node = state.nodes.find((entry) => entry.id === nodeId);
    if (node === undefined)
        return;
    try {
        await askGraph(`/graph/nodes/${nodeId}/move`, new URLSearchParams({
            x: String(node.x),
            y: String(node.y),
            // One call for a group and everything in it, so a group of ten
            // cannot half-move if the second call never lands.
            carries: node.kind === "group" ? "1" : "",
        }));
    }
    catch (_a) {
        showGraphError(state, "That node moved on screen, but the position was not saved.");
    }
}
function graphIsGroup(state, nodeId) {
    var _a;
    return ((_a = state.nodes.find((entry) => entry.id === nodeId)) === null || _a === void 0 ? void 0 : _a.kind) === "group";
}
async function saveGraphSize(state, nodeId) {
    const node = state.nodes.find((entry) => entry.id === nodeId);
    if (node === undefined || node.size === null)
        return;
    try {
        await askGraph(`/graph/nodes/${nodeId}/resize`, new URLSearchParams({
            width: String(node.size.width),
            height: String(node.size.height),
        }));
    }
    catch (_a) {
        showGraphError(state, "That group changed size on screen, but it was not saved.");
    }
}
// -- picking, and what follows ---------------------------------------------
function pickGraphNode(state, nodeId) {
    if (nodeId !== state.selectedNode)
        state.tab = "settings";
    state.selectedNode = nodeId;
    state.picked = nodeId === null ? new Set() : new Set([nodeId]);
    state.selectedWire = null;
    renderGraph(state);
}
/** Add or drop one node from the picked set, leaving the rest alone.
 *
 *  More than one picked means no panel: a panel is about a node, and there is
 *  no such thing as the settings of three of them. */
function alsoPickGraphNode(state, nodeId) {
    var _a;
    if (state.picked.has(nodeId))
        state.picked.delete(nodeId);
    else
        state.picked.add(nodeId);
    const only = state.picked.size === 1 ? (_a = [...state.picked][0]) !== null && _a !== void 0 ? _a : null : null;
    state.selectedNode = only;
    state.selectedWire = null;
    renderGraph(state);
}
function pickGraphWire(state, wireId) {
    state.selectedWire = wireId;
    state.selectedNode = null;
    renderGraph(state);
}
function clearGraphPick(state) {
    if (state.selectedNode === null && state.selectedWire === null && state.picked.size === 0) {
        return;
    }
    state.selectedNode = null;
    state.picked = new Set();
    state.selectedWire = null;
    renderGraph(state);
}
function onGraphClick(state, event) {
    var _a, _b;
    const target = event.target;
    if (!(target instanceof Element))
        return;
    const cut = target.closest("[data-cut]");
    const cutId = cut === null || cut === void 0 ? void 0 : cut.dataset["cut"];
    if (cutId !== undefined) {
        event.preventDefault();
        const wire = state.wires.find((entry) => entry.id === cutId);
        state.selectedWire = null;
        if (wire !== undefined) {
            const ends = { from: String(wire.from), to: String(wire.to) };
            rememberGraphUndo(state, "the wire you took out", async () => {
                await applyGraph(state, "/graph/connect", new URLSearchParams({
                    source: ends.from, target: ends.to,
                }));
            });
        }
        void applyGraph(state, "/graph/disconnect", new URLSearchParams({ wire: cutId }));
        return;
    }
    if (target.closest("[data-remove-picked]") !== null) {
        event.preventDefault();
        void removeGraphPicked(state);
        return;
    }
    const fire = target.closest("[data-fire]");
    const fireId = fire === null || fire === void 0 ? void 0 : fire.dataset["fire"];
    if (fireId !== undefined) {
        event.preventDefault();
        void fireGraphPulse(state, fireId, null);
        return;
    }
    const back = target.closest("[data-backfill]");
    const backId = back === null || back === void 0 ? void 0 : back.dataset["backfill"];
    if (backId !== undefined) {
        event.preventDefault();
        askHowFarBack(state, backId);
        return;
    }
    const test = target.closest("[data-test]");
    const testId = test === null || test === void 0 ? void 0 : test.dataset["test"];
    if (testId !== undefined) {
        event.preventDefault();
        void tryGraph(state, testId);
        return;
    }
    const filtered = target.closest("[data-filtered]");
    const filteredId = filtered === null || filtered === void 0 ? void 0 : filtered.dataset["filtered"];
    if (filteredId !== undefined) {
        event.preventDefault();
        void showGraphFiltered(state, filteredId);
        return;
    }
    const unslot = target.closest("[data-unslot]");
    const unslotId = unslot === null || unslot === void 0 ? void 0 : unslot.dataset["unslot"];
    if (unslotId !== undefined) {
        event.preventDefault();
        void applyGraph(state, `/graph/nodes/${unslotId}/attach`, new URLSearchParams({ under: "" }));
        return;
    }
    const remove = target.closest("[data-remove]");
    const removeId = remove === null || remove === void 0 ? void 0 : remove.dataset["remove"];
    if (removeId !== undefined) {
        event.preventDefault();
        // A filter or a trigger stands for nothing else and just goes. A channel
        // or a feed takes its history with it, so that is said out loud first.
        const warning = (_a = remove === null || remove === void 0 ? void 0 : remove.dataset["what"]) !== null && _a !== void 0 ? _a : "";
        void removeGraphNode(state, removeId, warning);
        return;
    }
    const tab = target.closest("[data-tab]");
    const wanted = tab === null || tab === void 0 ? void 0 : tab.dataset["tab"];
    if (wanted !== undefined) {
        event.preventDefault();
        const whose = Number((_b = tab === null || tab === void 0 ? void 0 : tab.dataset["for"]) !== null && _b !== void 0 ? _b : "");
        const box = state.nodes.find((entry) => entry.id === whose);
        state.tab = wanted === "test" ? "test" : "settings";
        if (graphTabNeedsRun(box, state.trial, wanted)) {
            void tryGraph(state, String(whose));
            return;
        }
        renderGraph(state);
        return;
    }
    if (target.closest("[data-close]") !== null) {
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
async function fireGraphPulse(state, nodeId, reachBack) {
    var _a;
    if (state.busy)
        return;
    state.busy = true;
    try {
        const asking = new URLSearchParams();
        const where = reachBack === null ? "fire" : "backfill";
        if (reachBack !== null && reachBack > 0)
            asking.set("count", String(reachBack));
        const answer = await askGraph(`/graph/nodes/${nodeId}/${where}`, asking);
        const view = asGraph(answer);
        if (view === null) {
            showGraphError(state, (_a = asGraphError(answer)) !== null && _a !== void 0 ? _a : "That trigger did not fire.");
            return;
        }
        state.nodes = view.nodes;
        state.wires = view.wires;
        forgetMissingGraph(state);
        showGraphError(state, null);
        showGraphVerdict(state, graphSaid(answer));
        renderGraph(state);
        void followGraphRun(state);
    }
    catch (_b) {
        showGraphError(state, "No connection, so nothing was polled.");
    }
    finally {
        state.busy = false;
    }
}
/** What the server said it did, if it said anything. */
function graphSaid(value) {
    const raw = asGraphRecord(value);
    const said = raw === null ? null : raw["said"];
    return typeof said === "string" ? said : null;
}
/** Take one box away, once the question about it has been answered. */
async function removeGraphNode(state, nodeId, warning) {
    if (warning !== "" && !(await askGraphSure(state, warning)))
        return;
    state.selectedNode = null;
    await applyGraph(state, `/graph/nodes/${nodeId}/delete`, new URLSearchParams());
}
function onGraphKeyDown(state, event) {
    if (event.key === "Escape") {
        clearGraphPick(state);
        return;
    }
    if (event.key === "Delete" || event.key === "Backspace") {
        if (state.picked.size === 0 || !graphTakesTheKey(event.target))
            return;
        event.preventDefault();
        void removeGraphPicked(state);
        return;
    }
    if (event.key !== "Enter" && event.key !== " ")
        return;
    const nodeId = graphNodeIdFrom(event.target);
    if (nodeId === null)
        return;
    event.preventDefault();
    pickGraphNode(state, nodeId);
}
async function onGraphSubmit(state, event) {
    const form = event.target;
    if (!(form instanceof HTMLFormElement))
        return;
    const nodeId = form.dataset["save"];
    if (nodeId === undefined)
        return;
    event.preventDefault();
    const was = form.dataset["was"];
    if (was !== undefined && was !== "") {
        rememberGraphUndo(state, "the change to that node", async () => {
            await applyGraph(state, `/graph/nodes/${nodeId}`, new URLSearchParams(was));
        });
    }
    await applyGraph(state, `/graph/nodes/${nodeId}`, graphFormValues(form));
}
/** A form's fields as a body. FormData can hold files; this one never does. */
function graphFormValues(form) {
    const params = new URLSearchParams();
    new FormData(form).forEach((value, key) => {
        if (typeof value === "string")
            params.append(key, value);
    });
    return params;
}
function asGraphJudged(value) {
    if (!Array.isArray(value))
        return [];
    const read = [];
    for (const entry of value) {
        const raw = asGraphRecord(entry);
        if (raw === null || typeof raw["id"] !== "number")
            continue;
        const reason = raw["reason"];
        read.push({
            id: raw["id"],
            title: typeof raw["title"] === "string" ? raw["title"] : "",
            reason: typeof reason === "string" ? reason : null,
            marks: Array.isArray(raw["marks"])
                ? raw["marks"].filter((one) => typeof one === "string")
                : [],
        });
    }
    return read;
}
/** Open the list of what this filter lets through and what it holds back. */
async function showGraphFiltered(state, nodeId) {
    var _a, _b;
    try {
        const answer = await askGraph(`/graph/nodes/${nodeId}/filtered`, null);
        const raw = asGraphRecord(answer);
        if (raw === null) {
            showGraphError(state, (_a = asGraphError(answer)) !== null && _a !== void 0 ? _a : "That filter could not be read.");
            return;
        }
        showGraphError(state, null);
        const node = state.nodes.find((entry) => entry.id === Number(nodeId));
        drawGraphFiltered(state, (_b = node === null || node === void 0 ? void 0 : node.title) !== null && _b !== void 0 ? _b : "What it catches", asGraphJudged(raw["through"]), asGraphJudged(raw["held"]));
    }
    catch (_c) {
        showGraphError(state, "No connection, so there is nothing to show.");
    }
}
function drawGraphFiltered(state, name, through, held) {
    var _a;
    const dialog = graphCatchDialog(state);
    const body = (_a = state.parts.canvas
        .closest(".graph-panel")) === null || _a === void 0 ? void 0 : _a.querySelector("[data-graph-catch-body]");
    if (dialog === null || !body)
        return;
    const title = dialog.querySelector("[data-graph-catch-name]");
    if (title !== null)
        title.textContent = name;
    body.textContent = "";
    body.appendChild(graphJudgedList("Pass", through, "through"));
    body.appendChild(graphJudgedList("Failed", held, "held"));
    openGraphCatch(dialog);
}
function graphCatchDialog(state) {
    var _a;
    var _b;
    return ((_b = (_a = state.parts.canvas
        .closest(".graph-panel")) === null || _a === void 0 ? void 0 : _a.querySelector("[data-graph-catch]")) !== null && _b !== void 0 ? _b : null);
}
/** Open it as a modal where the browser supports one, and plainly where not. */
/** Ask before taking something away, and wait for the answer.
 *
 *  Not `window.confirm`. A browser that has been told to stop this page making
 *  dialogs — the "prevent this page from creating additional dialogs" tick,
 *  which appears after a few in a row — answers confirm() with "no" and says
 *  nothing about it. The Remove button then did nothing at all: no question,
 *  no request, no error, for the rest of the tab's life. Everything else in
 *  the panel kept working, because nothing else asked first.
 *
 *  Falls back to `confirm` only when the dialog is not on the page, which is
 *  the same courtesy the backfill box gets. */
function askGraphSure(state, question) {
    const dialog = graphSureDialog(state);
    if (dialog === null)
        return Promise.resolve(window.confirm(question));
    const said = dialog.querySelector("[data-graph-sure-what]");
    if (said !== null)
        said.textContent = question;
    return new Promise((answer) => {
        let done = false;
        const finish = (yes) => {
            if (done)
                return;
            done = true;
            dialog.removeEventListener("close", onClose);
            shutGraphSure(dialog);
            answer(yes);
        };
        function onClose() {
            finish(false);
        }
        dialog.addEventListener("close", onClose);
        dialog.querySelectorAll("[data-graph-sure-yes]").forEach((yes) => {
            yes.onclick = () => finish(true);
        });
        dialog.querySelectorAll("[data-graph-sure-no]").forEach((no) => {
            no.onclick = () => finish(false);
        });
        openGraphCatch(dialog);
    });
}
function graphSureDialog(state) {
    var _a;
    var _b;
    return ((_b = (_a = state.parts.canvas
        .closest(".graph-panel")) === null || _a === void 0 ? void 0 : _a.querySelector("[data-graph-sure]")) !== null && _b !== void 0 ? _b : null);
}
function shutGraphSure(dialog) {
    if (dialog.open) {
        if (typeof dialog.close === "function")
            dialog.close();
        else
            dialog.removeAttribute("open");
    }
    holdPageForGraph(false);
}
function openGraphCatch(dialog) {
    if (dialog.open)
        return;
    if (typeof dialog.showModal === "function")
        dialog.showModal();
    else
        dialog.setAttribute("open", "");
    holdPageForGraph(true);
}
/** Stop the page scrolling away behind whatever is open over it.
 *
 *  A modal makes the page inert, which stops it being clicked but not
 *  necessarily scrolled — and the fallback path, where showModal is missing,
 *  makes it neither. The same class the tab drawer uses. */
function holdPageForGraph(held) {
    document.body.classList.toggle("page-held", held);
}
/** One side of a report: what got through, or what did not.
 *
 *  Numbered where the order means something — a trial is the batch in the
 *  order it would arrive, and on a sort box that order is the whole answer.
 *  Left unnumbered where it does not, so a number is never implying one. */
function graphJudgedList(name, items, side, numbered = false) {
    const part = graphElement("div", `graph-sheet-part is-${side}`);
    part.appendChild(graphElement("h4", "graph-sheet-name", `${name} (${items.length})`));
    if (items.length === 0) {
        part.appendChild(graphElement("p", "hint", "Nothing."));
        return part;
    }
    const list = graphElement(numbered ? "ol" : "ul", numbered ? "graph-sheet-list is-numbered" : "graph-sheet-list");
    for (const item of items) {
        const row = graphElement("li", "graph-sheet-row");
        row.appendChild(graphElement("span", "graph-sheet-title", item.title));
        // Only the held-back side has a reason to give; only the side that got
        // through has anything left on it.
        if (side === "held" && item.reason !== null) {
            row.appendChild(graphElement("span", "graph-sheet-reason", item.reason));
        }
        if (item.marks.length > 0) {
            const marks = graphElement("span", "graph-sheet-marks");
            for (const said of item.marks) {
                marks.appendChild(graphElement("span", "graph-sheet-mark", said));
            }
            row.appendChild(marks);
        }
        list.appendChild(row);
    }
    part.appendChild(list);
    return part;
}
// -- putting something back ------------------------------------------------
/** How many steps back it can go. Far enough to fix a mistake, not so far
 *  that it becomes a second history of the setup. */
function graphUndoDepth() {
    return 40;
}
function rememberGraphUndo(state, says, run) {
    state.undo.push({ says, run });
    if (state.undo.length > graphUndoDepth())
        state.undo.shift();
}
/** Put the last change back. */
async function undoGraph(state) {
    const step = state.undo.pop();
    if (step === undefined) {
        showGraphVerdict(state, "Nothing left to undo.");
        return;
    }
    await step.run();
    showGraphVerdict(state, `Undone: ${step.says}.`);
}
/** Whether a keystroke is the page's to take.
 *
 *  Ctrl+Z inside a text field is that field's own undo, and taking it would
 *  make typing in a node's name unrecoverable. */
function graphTakesTheKey(target) {
    if (!(target instanceof Element))
        return true;
    return target.closest("input, textarea, select") === null;
}
/** The node that is on the canvas now and was not before. */
function graphNodeAdded(before, after) {
    var _a;
    var _b;
    const had = new Set(before.map((node) => node.id));
    const fresh = after.filter((node) => !had.has(node.id));
    return fresh.length === 1 ? ((_b = (_a = fresh[0]) === null || _a === void 0 ? void 0 : _a.id) !== null && _b !== void 0 ? _b : null) : null;
}
/** The wire that is on the canvas now and was not before. */
function graphWireAdded(before, after) {
    var _a;
    var _b;
    const had = new Set(before.map((wire) => wire.id));
    const fresh = after.filter((wire) => !had.has(wire.id));
    return fresh.length === 1 ? ((_b = (_a = fresh[0]) === null || _a === void 0 ? void 0 : _a.id) !== null && _b !== void 0 ? _b : null) : null;
}
// -- trying it without running it ------------------------------------------
/** Ask what a run would do, mark the boxes with it, and list where it lands. */
async function tryGraph(state, nodeId) {
    var _a;
    // Shown in the box that was asked, so open its test side first and say it
    // is working: the answer takes a moment and a blank panel reads as broken.
    state.selectedNode = Number(nodeId);
    state.tab = "test";
    state.trial = { node: Number(nodeId), boxes: new Map(), asking: true };
    renderGraph(state);
    try {
        const answer = await askGraph(`/graph/nodes/${nodeId}/test`, null);
        const run = asGraphRun(answer);
        const raw = asGraphRecord(answer);
        if (run === null || raw === null) {
            state.trial = null;
            state.tab = "settings";
            showGraphError(state, (_a = asGraphError(answer)) !== null && _a !== void 0 ? _a : "That could not be tried.");
            renderGraph(state);
            return;
        }
        showGraphError(state, null);
        state.trial = {
            node: Number(nodeId),
            boxes: asGraphShares(raw["items"]),
            asking: false,
        };
        // The same marks a real run leaves, so the drawing reads the same either
        // way: what differs is that nothing was written.
        state.run = run.nodes;
        renderGraph(state);
    }
    catch (_b) {
        state.trial = null;
        state.tab = "settings";
        showGraphError(state, "No connection, so nothing could be tried.");
        renderGraph(state);
    }
}
/** Every box the trial touched, and what each of them did. */
function asGraphShares(value) {
    const shares = new Map();
    const raw = asGraphRecord(value);
    if (raw === null)
        return shares;
    for (const key of Object.keys(raw)) {
        const share = asGraphRecord(raw[key]);
        if (share === null)
            continue;
        shares.set(Number(key), {
            through: asGraphJudged(share["through"]),
            held: asGraphHeld(share["held"]),
        });
    }
    return shares;
}
/** Held items, each naming the box that stopped it as part of its reason. */
function asGraphHeld(value) {
    if (!Array.isArray(value))
        return [];
    const read = [];
    for (const entry of value) {
        const raw = asGraphRecord(entry);
        if (raw === null || typeof raw["id"] !== "number")
            continue;
        const box = typeof raw["box"] === "string" ? raw["box"] : "";
        const why = typeof raw["reason"] === "string" ? raw["reason"] : "held back";
        read.push({
            id: raw["id"],
            title: typeof raw["title"] === "string" ? raw["title"] : "",
            reason: box === "" ? why : `${box}: ${why}`,
            // Nothing happens to something that was turned away.
            marks: [],
        });
    }
    return read;
}
function asGraphRun(value) {
    const raw = asGraphRecord(value);
    if (raw === null)
        return null;
    const marks = new Map();
    const nodes = asGraphRecord(raw["nodes"]);
    for (const key of Object.keys(nodes !== null && nodes !== void 0 ? nodes : {})) {
        const mark = asGraphRecord((nodes !== null && nodes !== void 0 ? nodes : {})[key]);
        if (mark === null)
            continue;
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
async function followGraphRun(state) {
    if (state.watching)
        return;
    state.watching = true;
    try {
        for (;;) {
            const run = asGraphRun(await askGraph("/api/graph/run", null));
            if (run === null)
                return;
            state.run = run.nodes;
            paintGraphRun(state);
            showGraphVerdict(state, graphStageWords(run));
            if (!run.running)
                break;
            await graphPause(900);
        }
    }
    catch (_a) {
        // A run nobody can watch is still a run. Leave what is on screen.
    }
    finally {
        state.watching = false;
        // The boxes have changed underneath: counts, last-polled times, feeds.
        // What the run found stays on them, which is the point of having watched.
        await applyGraph(state, "/api/graph", null);
    }
}
function graphPause(milliseconds) {
    return new Promise((wake) => {
        window.setTimeout(wake, milliseconds);
    });
}
/** What the run is doing, in words, above the canvas. */
function graphStageWords(run) {
    if (!run.running)
        return run.stage === null ? null : "Run finished.";
    if (run.stage === "polling")
        return "Checking channels for new items…";
    if (run.stage === "sorting")
        return "Looking at what came back…";
    if (run.stage === "filling")
        return "Filling the feeds…";
    return "Running…";
}
/** Mark the boxes the run has reached, and the wires between them. */
function paintGraphRun(state) {
    for (const [id, box] of state.boxes) {
        const mark = state.run.get(id);
        box.classList.toggle("is-busy", (mark === null || mark === void 0 ? void 0 : mark.state) === "busy");
        box.classList.toggle("is-visited", (mark === null || mark === void 0 ? void 0 : mark.state) === "done");
        graphTally(box, mark);
    }
    paintGraphRunWires(state);
}
/** What the run found here, said on the box.
 *
 *  A channel that was polled and brought back nothing says so. Leaving it
 *  blank would look the same as a channel the run never reached, and "there
 *  was nothing new" is an answer worth having — it is the usual one. */
function graphTally(box, mark) {
    var _a;
    const showing = box.querySelector(".graph-node-tally");
    if (mark === undefined || mark.state !== "done") {
        showing === null || showing === void 0 ? void 0 : showing.remove();
        box.classList.remove("is-dead-end");
        return;
    }
    const tally = showing !== null && showing !== void 0 ? showing : graphElement("span", "graph-node-tally");
    tally.textContent = graphTallyWords(mark);
    // Four readings, and they are not the same thing: something came through,
    // nothing was there to come through, something was there and this box is
    // where it stopped, and it went and could not get in.
    tally.classList.toggle("is-empty", mark.count === 0 && !mark.ends);
    const refused = typeof mark.trouble === "string" && mark.trouble !== "";
    tally.classList.toggle("is-end", mark.ends && !refused);
    tally.classList.toggle("is-trouble", refused);
    tally.title = refused ? ((_a = mark.trouble) !== null && _a !== void 0 ? _a : "") : "";
    box.classList.toggle("is-dead-end", mark.ends);
    if (showing === null)
        box.appendChild(tally);
}
function graphTallyWords(mark) {
    // It went and could not get in. Said in its own words, because "stops here"
    // sent people looking for a wiring fault when the feed was simply refusing
    // them — which is the one reading of a run they cannot check by looking.
    //
    // Asked for a non-empty string rather than "not null": a mark from anywhere
    // that leaves the field out gives undefined, which is also not null.
    if (typeof mark.trouble === "string" && mark.trouble !== "")
        return mark.trouble;
    if (mark.count > 0)
        return `+${mark.count}`;
    // Held something and passed none of it on: this is where the flow stopped.
    if (mark.stopped > 0)
        return `stops here · ${mark.stopped} held`;
    // Nothing left it and it had nothing to hold — a trigger whose channels are
    // all switched off. It did not look and find nothing; it never looked.
    if (mark.ends)
        return "stops here";
    return "nothing new";
}
/** A wire out of a box the run has reached is carrying something. */
function paintGraphRunWires(state) {
    const busy = new Set();
    for (const [id, mark] of state.run) {
        if (mark.state === "busy")
            busy.add(id);
    }
    state.parts.wires.querySelectorAll(".graph-wire").forEach((path) => {
        path.classList.remove("is-carrying");
    });
    if (busy.size === 0)
        return;
    for (const wire of state.wires) {
        if (!busy.has(wire.from))
            continue;
        state.parts.wires
            .querySelectorAll(`[data-line="${wire.id}"]`)
            .forEach((path) => path.classList.add("is-carrying"));
    }
}
/** The pieces of the page this canvas is made of, or null if one is missing. */
function graphPartsIn(canvas) {
    const panel = canvas.closest(".graph-panel");
    const scene = canvas.querySelector("[data-graph-scene]");
    const groups = canvas.querySelector("[data-graph-groups]");
    const layer = canvas.querySelector("[data-graph-nodes]");
    const wires = canvas.querySelector("[data-graph-wires]");
    if (!panel || scene === null || groups === null || layer === null || wires === null) {
        return null;
    }
    return {
        canvas,
        scene,
        groups,
        layer,
        wires,
        drawer: canvas.querySelector("[data-graph-drawer]"),
        error: panel.querySelector("[data-graph-error]"),
        verdict: panel.querySelector("[data-graph-verdict]"),
        empty: panel.querySelector("[data-graph-empty]"),
    };
}
// -- the palette -----------------------------------------------------------
function toggleGraphPalette(state, open) {
    var _a, _b;
    const drawer = state.parts.drawer;
    if (drawer === null)
        return;
    // They share an edge, so only one of them is ever out.
    if (open)
        toggleGraphFinder(state, false);
    drawer.hidden = !open;
    (_b = (_a = state.parts.canvas
        .closest(".graph-panel")) === null || _a === void 0 ? void 0 : _a.querySelector("[data-graph-palette]")) === null || _b === void 0 ? void 0 : _b.setAttribute("aria-expanded", open ? "true" : "false");
}
/** Start dragging a kind of box out of the palette. */
function beginGraphDrop(state, event, kind, which = "", named = "") {
    const ghost = graphElement("div", `graph-node kind-${graphPaletteKind(kind)} is-ghost`);
    // A plugin box is named by its plugin, so the ghost carries that rather
    // than the word "plugin", which would tell the reader nothing.
    ghost.appendChild(graphElement("span", "graph-node-kind", named || graphPaletteName(kind)));
    ghost.style.position = "fixed";
    ghost.style.pointerEvents = "none";
    moveGraphGhost(ghost, event);
    document.body.appendChild(ghost);
    state.dropping = { kind, which, pointerId: event.pointerId, ghost };
}
function moveGraphGhost(ghost, event) {
    ghost.style.left = `${event.clientX - 40}px`;
    ghost.style.top = `${event.clientY - 18}px`;
}
/** A pulse and a schedule are both trigger boxes, and look like one. */
function graphPaletteKind(kind) {
    if (kind === "pulse" || kind === "schedule")
        return "trigger";
    return kind;
}
function graphPaletteName(kind) {
    if (kind === "source")
        return "Source";
    if (kind === "plugin")
        return "Plugin";
    if (kind === "feed")
        return "Feed";
    if (kind === "filter")
        return "Filter";
    if (kind === "sort")
        return "Sort";
    if (kind === "group")
        return "Group";
    return kind === "pulse" ? "Pulse" : "Schedule";
}
/** The box under the pointer, for a piece being dropped onto one.
 *
 *  Asked of the document rather than worked out from coordinates: the boxes
 *  are where the browser put them, and the ghost is not in the way because it
 *  takes no pointer events. */
/** How near the underside of a box a piece has to be dropped to go into it.
 *
 *  Generous on purpose. Nobody aims at a one-pixel seam, and the slot is
 *  shown while you drag so the distance is never a guess.
 *
 *  A function rather than a constant: htmx re-inserts this script on every
 *  swap, and only top-level function declarations survive being run twice. */
function graphSlotReach() {
    return 150;
}
/** Whether this kind of piece belongs under this kind of box.
 *
 *  The same answer the server gives, said here as well so a piece being
 *  dragged only lights up the boxes it can actually go into — a refusal you
 *  can see coming is better than one that arrives after the drop. */
function graphPieceGoesUnder(piece, box) {
    if (piece === "order")
        return box === "sort";
    if (graphConditionKinds().indexOf(piece) >= 0)
        return box === "filter";
    // A plugin's condition goes where every other condition goes.
    if (piece === "rule")
        return box === "filter";
    // A Timer, Reset, Alive or Lock. These say something about reading, which
    // is a question only these three boxes ask.
    return box === "feed" || box === "decay" || box === "expire";
}
/** Every place a piece of this kind could be slotted, with where each sits.
 *
 *  Null asks for every slot there is, which is what an ordinary drag wants
 *  before anything is known about what is being dragged. */
function graphSlots(state, held = null) {
    var _a, _b;
    const below = new Map();
    for (const node of state.nodes) {
        const host = (_a = node.piece) === null || _a === void 0 ? void 0 : _a.under;
        if (host === undefined || host === null)
            continue;
        const kept = below.get(host);
        if (kept === undefined)
            below.set(host, [node]);
        else
            kept.push(node);
    }
    const found = [];
    for (const node of state.nodes) {
        // A group is a background, and a piece belongs to the box at the top of
        // its own chain rather than starting a second one.
        if (node.kind === "group" || node.piece !== null)
            continue;
        // A box that ignores what is slotted into it is not somewhere a piece
        // goes: offering a slot under a source box would be an invitation to
        // nothing. The same list the notch is drawn from.
        if (!graphTakesPieces(node.kind))
            continue;
        if (held !== null && !graphPieceGoesUnder(held, node.kind))
            continue;
        // Walk to the end of whatever is already slotted in, so a second piece
        // lands under the first rather than beside it.
        let last = node;
        for (let depth = 0; depth < 12; depth += 1) {
            const next = (_b = below.get(last.id)) === null || _b === void 0 ? void 0 : _b[0];
            if (next === undefined)
                break;
            last = next;
        }
        const box = state.boxes.get(last.id);
        if (box === undefined)
            continue;
        found.push({
            under: last.id,
            x: last.x,
            y: last.y + box.offsetHeight,
            width: box.offsetWidth,
        });
    }
    return found;
}
/** The slot a piece being dragged would drop into, if any. */
function graphSlotFor(state, event, held = null) {
    const at = pointInGraph(state, event);
    let nearest = null;
    let best = graphSlotReach();
    for (const slot of graphSlots(state, held)) {
        // Measured to the slot's middle, so a box is easiest to hit from
        // directly below it and hardest from off to one side.
        const dx = at.x - (slot.x + slot.width / 2);
        const dy = at.y - slot.y;
        const away = Math.sqrt(dx * dx + dy * dy);
        if (away < best) {
            best = away;
            nearest = slot;
        }
    }
    return nearest;
}
/** Show where a piece would land, while one is dragged out of the palette. */
function markGraphSlot(state, event) {
    const dropping = state.dropping;
    const wanted = dropping !== null && graphIsPiece(dropping.kind)
        ? graphSlotFor(state, event, dropping.kind)
        : null;
    showGraphSlot(state, wanted);
}
/** The same, for a piece already on the canvas being dragged onto one. */
function markGraphSlotFor(state, event, moving, held) {
    const slot = graphSlotFor(state, event, held);
    showGraphSlot(state, slot !== null && slot.under !== moving ? slot : null);
}
function showGraphSlot(state, wanted) {
    const marker = graphSlotMarker(state);
    if (marker === null)
        return;
    if (wanted === null) {
        marker.hidden = true;
        return;
    }
    marker.hidden = false;
    marker.style.left = `${wanted.x}px`;
    marker.style.top = `${wanted.y}px`;
    marker.style.width = `${wanted.width}px`;
}
/** The outline drawn where a piece would land. Made once and kept. */
function graphSlotMarker(state) {
    const layer = state.parts.layer;
    let marker = layer.querySelector(".graph-slot");
    if (marker === null) {
        marker = graphElement("div", "graph-slot");
        marker.hidden = true;
        layer.appendChild(marker);
    }
    return marker;
}
function hideGraphSlot(state) {
    const marker = state.parts.layer.querySelector(".graph-slot");
    if (marker !== null)
        marker.hidden = true;
}
function finishGraphDrop(state, event) {
    var _a;
    var _b;
    const dropping = state.dropping;
    if (dropping === null || dropping.pointerId !== event.pointerId)
        return;
    state.dropping = null;
    dropping.ghost.remove();
    hideGraphSlot(state);
    const frame = state.parts.canvas.getBoundingClientRect();
    const inside = event.clientX >= frame.left && event.clientX <= frame.right &&
        event.clientY >= frame.top && event.clientY <= frame.bottom;
    if (!inside)
        return;
    const at = pointInGraph(state, event);
    // A piece goes into the slot it was nearest, rather than lying where it
    // landed. Dropped nowhere near one it is simply a piece on the canvas,
    // which can be picked up and put somewhere.
    const onto = graphIsPiece(dropping.kind)
        ? ((_b = (_a = graphSlotFor(state, event, dropping.kind)) === null || _a === void 0 ? void 0 : _a.under) !== null && _b !== void 0 ? _b : null)
        : null;
    void dropGraphNode(state, dropping.kind, Math.round(at.x - 100), Math.round(at.y - 30), dropping.which, onto);
}
/** Make a box of this kind, at this spot in the drawing. */
async function dropGraphNode(state, kind, x, y, which = "", onto = null) {
    toggleGraphPalette(state, false);
    const before = state.nodes;
    const asking = new URLSearchParams({ kind, x: String(x), y: String(y) });
    if (onto !== null)
        asking.set("attach_to", String(onto));
    // The same word off the palette row, sent under whichever name the kind
    // being made reads it by.
    if (which !== "")
        asking.set(kind === "source" ? "source_kind" : "plugin_node", which);
    const made = await applyGraph(state, "/graph/nodes", asking);
    if (!made)
        return;
    // Whatever appeared is what an undo takes away. A node just added is empty,
    // so removing it costs nothing — unlike removing one that has been wired up
    // and filled, which undo deliberately does not offer.
    const fresh = graphNodeAdded(before, state.nodes);
    if (fresh === null)
        return;
    rememberGraphUndo(state, `the ${kind} you added`, async () => {
        await applyGraph(state, `/graph/nodes/${fresh}/delete`, new URLSearchParams());
    });
}
/** The run log, in a box on the canvas rather than a page away from it.
 *
 *  Fetched when it is opened rather than drawn with the page: most visits to
 *  the canvas are not about what the last run did, and a log nobody asked for
 *  should cost nothing. */
function listenForGraphLog(state, panel) {
    var _a;
    const dialog = panel.querySelector("[data-graph-log]");
    const body = dialog === null || dialog === void 0 ? void 0 : dialog.querySelector("[data-graph-log-body]");
    if (dialog === null || !body)
        return;
    (_a = panel.querySelector("[data-graph-log-open]")) === null || _a === void 0 ? void 0 : _a.addEventListener("click", () => {
        openGraphCatch(dialog);
        void fillGraphLog(body);
    });
    dialog.querySelectorAll("[data-graph-log-close]").forEach((shut) => {
        shut.addEventListener("click", () => dialog.close());
    });
    dialog.addEventListener("click", (event) => {
        if (event.target === dialog)
            dialog.close();
    });
    dialog.addEventListener("close", () => holdPageForGraph(false));
}
/** Ask for the log and put it in the box.
 *
 *  Through htmx rather than fetch, because what comes back has htmx
 *  attributes of its own — the filter buttons — and htmx swapping it in is
 *  what makes those live without this file knowing anything about them. */
async function fillGraphLog(body) {
    body.textContent = "";
    body.appendChild(graphElement("p", "empty", "Reading the log…"));
    const htmx = window.htmx;
    if (htmx === undefined) {
        body.textContent = "";
        body.appendChild(graphElement("p", "empty", "The log needs JavaScript to load."));
        return;
    }
    try {
        await htmx.ajax("GET", "/partials/log", { target: "#graph-log-body", swap: "innerHTML" });
    }
    catch (_a) {
        body.textContent = "";
        body.appendChild(graphElement("p", "empty", "The log could not be read just now."));
    }
}
/** Open the box that asks how far back to reach, remembering which trigger
 *  asked. The trigger is kept on the dialog rather than in a variable up here:
 *  this file is re-run on every htmx swap, so nothing may live at the top
 *  level between runs. */
function askHowFarBack(state, nodeId) {
    var _a;
    const dialog = graphReachDialog(state);
    if (dialog === null) {
        // No dialog on the page: reach back as far as the feeds go rather than
        // refusing to do the thing that was asked for.
        void fireGraphPulse(state, nodeId, 0);
        return;
    }
    dialog.dataset["forNode"] = nodeId;
    graphReachTrouble(dialog, null);
    openGraphCatch(dialog);
    (_a = dialog.querySelector("[data-graph-reach-count]")) === null || _a === void 0 ? void 0 : _a.select();
}
function graphReachDialog(state) {
    var _a;
    var _b;
    return ((_b = (_a = state.parts.canvas
        .closest(".graph-panel")) === null || _a === void 0 ? void 0 : _a.querySelector("[data-graph-reach]")) !== null && _b !== void 0 ? _b : null);
}
/** Wire the box up once, the way the group-file one is wired. */
function listenForGraphReach(state, panel) {
    var _a;
    const dialog = panel.querySelector("[data-graph-reach]");
    if (dialog === null)
        return;
    dialog.querySelectorAll("[data-graph-reach-close]").forEach((shut) => {
        shut.addEventListener("click", () => dialog.close());
    });
    dialog.addEventListener("click", (event) => {
        if (event.target === dialog)
            dialog.close();
    });
    dialog.addEventListener("close", () => holdPageForGraph(false));
    (_a = dialog.querySelector("[data-graph-reach-form]")) === null || _a === void 0 ? void 0 : _a.addEventListener("submit", (event) => {
        var _a;
        event.preventDefault();
        const field = dialog.querySelector("[data-graph-reach-count]");
        const wanted = Number.parseInt((_a = field === null || field === void 0 ? void 0 : field.value) !== null && _a !== void 0 ? _a : "", 10);
        if (!Number.isFinite(wanted) || wanted < 1) {
            graphReachTrouble(dialog, "Give it a number of posts, one or more.");
            return;
        }
        const nodeId = dialog.dataset["forNode"];
        if (nodeId === undefined) {
            graphReachTrouble(dialog, "That trigger is no longer there.");
            return;
        }
        dialog.close();
        void fireGraphPulse(state, nodeId, wanted);
    });
}
function graphReachTrouble(dialog, message) {
    const said = dialog.querySelector("[data-graph-reach-error]");
    if (said === null)
        return;
    said.textContent = message !== null && message !== void 0 ? message : "";
    said.hidden = message === null;
}
/** The box that asks for a group file, and what it does with one. */
function listenForGraphLoad(state, panel) {
    var _a, _b;
    const dialog = panel.querySelector("[data-graph-load]");
    if (dialog === null)
        return;
    (_a = panel.querySelector("[data-graph-load-open]")) === null || _a === void 0 ? void 0 : _a.addEventListener("click", () => {
        graphLoadTrouble(dialog, null);
        openGraphCatch(dialog);
    });
    dialog.querySelectorAll("[data-graph-load-close]").forEach((shut) => {
        shut.addEventListener("click", () => dialog.close());
    });
    // A click on the backdrop lands on the dialog itself, not on its contents.
    dialog.addEventListener("click", (event) => {
        if (event.target === dialog)
            dialog.close();
    });
    dialog.addEventListener("close", () => holdPageForGraph(false));
    (_b = dialog.querySelector("[data-graph-load-form]")) === null || _b === void 0 ? void 0 : _b.addEventListener("submit", (event) => {
        var _a;
        event.preventDefault();
        const picked = dialog.querySelector("[data-graph-load-file]");
        const file = (_a = picked === null || picked === void 0 ? void 0 : picked.files) === null || _a === void 0 ? void 0 : _a[0];
        if (file === undefined) {
            graphLoadTrouble(dialog, "Choose a group file first.");
            return;
        }
        void loadGraphGroup(state, file, dialog);
    });
}
/** Said inside the box rather than behind it, where it would go unread. */
function graphLoadTrouble(dialog, message) {
    const said = dialog.querySelector("[data-graph-load-error]");
    if (said === null)
        return;
    said.textContent = message !== null && message !== void 0 ? message : "";
    said.hidden = message === null;
}
/** Load a group somebody exported, into the middle of the view. */
async function loadGraphGroup(state, file, dialog) {
    var _a;
    const centre = graphViewCentre(state);
    const body = new FormData();
    body.append("file", file);
    // Dropped around the middle of what is on screen, not on top of whatever is
    // already at the coordinates it was exported from.
    body.append("x", String(Math.round(centre.x - 260)));
    body.append("y", String(Math.round(centre.y - 150)));
    try {
        const response = await fetch("/graph/groups", { method: "POST", body });
        const answer = (await response.json());
        const view = asGraph(answer);
        if (view === null) {
            graphLoadTrouble(dialog, (_a = asGraphError(answer)) !== null && _a !== void 0 ? _a : "That group could not be loaded.");
            return;
        }
        state.nodes = view.nodes;
        state.wires = view.wires;
        forgetMissingGraph(state);
        showGraphError(state, null);
        dialog.close();
        renderGraph(state);
    }
    catch (_b) {
        graphLoadTrouble(dialog, "No connection, so nothing was loaded.");
    }
}
/** Where the middle of the view is, for a box added without being dragged. */
function graphViewCentre(state) {
    const frame = state.parts.canvas.getBoundingClientRect();
    return pointInGraph(state, {
        clientX: frame.left + frame.width / 2,
        clientY: frame.top + frame.height / 2,
    });
}
function listenToPalette(state, panel) {
    var _a, _b;
    (_a = panel.querySelector("[data-graph-palette]")) === null || _a === void 0 ? void 0 : _a.addEventListener("click", () => {
        var _a;
        toggleGraphPalette(state, ((_a = state.parts.drawer) === null || _a === void 0 ? void 0 : _a.hidden) === true);
    });
    (_b = panel
        .querySelector("[data-graph-palette-close]")) === null || _b === void 0 ? void 0 : _b.addEventListener("click", () => toggleGraphPalette(state, false));
    panel.querySelectorAll("[data-palette]").forEach((item) => {
        var _a;
        var _b, _c, _d;
        const kind = item.dataset["palette"];
        if (kind === undefined)
            return;
        // A plugin's row says which of its boxes it is, and a source row says
        // which kind of somewhere it watches. Every other kind is the whole
        // answer by itself.
        const which = (_c = (_b = item.dataset["pluginNode"]) !== null && _b !== void 0 ? _b : item.dataset["sourceKind"]) !== null && _c !== void 0 ? _c : "";
        const named = (_d = (_a = item.querySelector(".palette-text strong")) === null || _a === void 0 ? void 0 : _a.textContent) !== null && _d !== void 0 ? _d : "";
        item.addEventListener("pointerdown", (event) => {
            event.preventDefault();
            beginGraphDrop(state, event, kind, which, named);
        });
        // Pressed rather than dragged: it goes in the middle of the view, which
        // is the only spot the reader is certainly looking at.
        item.addEventListener("keydown", (event) => {
            if (event.key !== "Enter" && event.key !== " ")
                return;
            event.preventDefault();
            const centre = graphViewCentre(state);
            void dropGraphNode(state, kind, Math.round(centre.x - 100), Math.round(centre.y - 30), which);
        });
    });
}
// -- finding a group -------------------------------------------------------
/** The list of groups, and the way back to each of them.
 *
 *  The canvas goes on for ever in every direction, so a group dragged far
 *  enough out is a group nobody can find by panning. */
function renderGraphFinder(state) {
    const list = graphFinderPart(state, "[data-graph-finder-list]");
    if (list === null)
        return;
    list.textContent = "";
    const groups = state.nodes.filter((node) => node.kind === "group");
    if (groups.length === 0) {
        list.appendChild(graphElement("li", "finder-empty", "No groups yet. Add one from +."));
        return;
    }
    for (const group of groups) {
        const row = graphElement("li", "finder-item");
        const go = graphElement("button", "finder-go", group.title);
        go.setAttribute("type", "button");
        go.dataset["goto"] = String(group.id);
        row.appendChild(go);
        list.appendChild(row);
    }
}
function graphFinderPart(state, selector) {
    var _a;
    var _b;
    return ((_b = (_a = state.parts.canvas
        .closest(".graph-panel")) === null || _a === void 0 ? void 0 : _a.querySelector(selector)) !== null && _b !== void 0 ? _b : null);
}
function toggleGraphFinder(state, open) {
    var _a;
    const drawer = graphFinderPart(state, "[data-graph-finder]");
    if (drawer === null)
        return;
    if (open) {
        renderGraphFinder(state);
        toggleGraphPalette(state, false);
    }
    drawer.hidden = !open;
    (_a = graphFinderPart(state, "[data-graph-find]")) === null || _a === void 0 ? void 0 : _a.setAttribute("aria-expanded", open ? "true" : "false");
}
/** Pan so that node sits in the middle of the view, and pick it out. */
function centreGraphOn(state, node) {
    var _a, _b;
    var _c, _d;
    const frame = state.parts.canvas.getBoundingClientRect();
    const middleX = node.x + ((_c = (_a = node.size) === null || _a === void 0 ? void 0 : _a.width) !== null && _c !== void 0 ? _c : 212) / 2;
    const middleY = node.y + ((_d = (_b = node.size) === null || _b === void 0 ? void 0 : _b.height) !== null && _d !== void 0 ? _d : 60) / 2;
    panGraph(state, frame.width / 2 - middleX * state.zoom, frame.height / 2 - middleY * state.zoom);
    // Brought into view and marked, not opened: the answer to "where is it" is
    // seeing it, and a panel over it would be in the way of the answer.
    state.picked = new Set([node.id]);
    state.selectedNode = null;
    renderGraph(state);
}
function listenForGraphFinder(state, panel) {
    var _a, _b, _c;
    (_a = panel.querySelector("[data-graph-find]")) === null || _a === void 0 ? void 0 : _a.addEventListener("click", () => {
        const drawer = graphFinderPart(state, "[data-graph-finder]");
        toggleGraphFinder(state, (drawer === null || drawer === void 0 ? void 0 : drawer.hidden) === true);
    });
    (_b = panel
        .querySelector("[data-graph-find-close]")) === null || _b === void 0 ? void 0 : _b.addEventListener("click", () => toggleGraphFinder(state, false));
    (_c = panel.querySelector("[data-graph-finder-list]")) === null || _c === void 0 ? void 0 : _c.addEventListener("click", (event) => {
        var _a;
        const target = event.target;
        if (!(target instanceof Element))
            return;
        const wanted = (_a = target.closest("[data-goto]")) === null || _a === void 0 ? void 0 : _a.dataset["goto"];
        if (wanted === undefined)
            return;
        const node = state.nodes.find((entry) => entry.id === Number(wanted));
        if (node !== undefined)
            centreGraphOn(state, node);
    });
}
// -- setting up ------------------------------------------------------------
function listenToGraph(state) {
    var _a, _b;
    const { canvas } = state.parts;
    const panel = canvas.closest(".graph-panel");
    canvas.addEventListener("pointerdown", (event) => onGraphPointerDown(state, event));
    canvas.addEventListener("pointerup", (event) => onGraphPointerUp(state, event));
    canvas.addEventListener("pointercancel", (event) => onGraphPointerUp(state, event));
    canvas.addEventListener("click", (event) => onGraphClick(state, event));
    canvas.addEventListener("keydown", (event) => onGraphKeyDown(state, event));
    canvas.addEventListener("submit", (event) => {
        void onGraphSubmit(state, event);
    });
    // On the document, not the canvas: after a drag the focus may be anywhere,
    // and an undo that only works while the canvas happens to be focused is an
    // undo nobody can rely on.
    document.addEventListener("keydown", (event) => {
        if (!(event.ctrlKey || event.metaKey) || event.key.toLowerCase() !== "z")
            return;
        if (!graphTakesTheKey(event.target))
            return;
        event.preventDefault();
        void undoGraph(state);
    });
    // The wheel zooms while the pointer is over the canvas. The canvas fills
    // the page, so a wheel there can only have been meant for it.
    canvas.addEventListener("wheel", (event) => {
        event.preventDefault();
        // A line-by-line wheel reports small deltas and a trackpad reports
        // large ones, so the step is taken from the direction, not the size.
        zoomGraph(state, event.deltaY < 0 ? 1.12 : 1 / 1.12, event.clientX, event.clientY);
    }, { passive: false });
    // On the window, not the canvas: a palette box is dragged from outside it,
    // and a box dragged past its edge should keep following the pointer.
    window.addEventListener("pointermove", (event) => {
        if (state.dropping !== null && state.dropping.pointerId === event.pointerId) {
            moveGraphGhost(state.dropping.ghost, event);
            markGraphSlot(state, event);
            return;
        }
        onGraphPointerMove(state, event);
    });
    window.addEventListener("pointerup", (event) => {
        finishGraphDrop(state, event);
    });
    if (panel !== null)
        listenToPalette(state, panel);
    (_a = panel === null || panel === void 0 ? void 0 : panel.querySelector("[data-graph-undo]")) === null || _a === void 0 ? void 0 : _a.addEventListener("click", () => {
        void undoGraph(state);
    });
    if (panel !== null)
        listenForGraphLoad(state, panel);
    if (panel !== null)
        listenForGraphReach(state, panel);
    if (panel !== null)
        listenForGraphLog(state, panel);
    if (panel !== null)
        listenForGraphFinder(state, panel);
    const catching = graphCatchDialog(state);
    (_b = catching === null || catching === void 0 ? void 0 : catching.querySelector("[data-graph-catch-close]")) === null || _b === void 0 ? void 0 : _b.addEventListener("click", () => catching.close());
    // A click on the backdrop lands on the dialog itself, not on its contents.
    catching === null || catching === void 0 ? void 0 : catching.addEventListener("click", (event) => {
        if (event.target === catching)
            catching.close();
    });
    // Every way of shutting it ends here — the button, the backdrop, Esc — so
    // this is the one place that has to give the page back.
    catching === null || catching === void 0 ? void 0 : catching.addEventListener("close", () => holdPageForGraph(false));
    // Boxes are measured to place the wires, so a resize moves them.
    window.addEventListener("resize", () => drawGraphWires(state));
}
function startGraph(canvas) {
    if (canvas.dataset["ready"] === "1")
        return;
    const parts = graphPartsIn(canvas);
    if (parts === null)
        return;
    canvas.dataset["ready"] = "1";
    const state = {
        parts,
        nodes: [],
        wires: [],
        sources: [],
        boxes: new Map(),
        selectedNode: null,
        picked: new Set(),
        selectedWire: null,
        drag: null,
        ghost: null,
        run: new Map(),
        watching: false,
        busy: false,
        panX: 0,
        panY: 0,
        zoom: 1,
        dropping: null,
        tab: "settings",
        trial: null,
        undo: [],
    };
    listenToGraph(state);
    panGraph(state, 0, 0);
    void openGraph(state);
}
/** Draw the graph, then pick up any run already in flight. */
async function openGraph(state) {
    await applyGraph(state, "/api/graph", null);
    const run = asGraphRun(await askGraph("/api/graph/run", null).catch(() => null));
    if (run !== null && run.running)
        void followGraphRun(state);
}
function findGraphs(root) {
    root.querySelectorAll("[data-graph]").forEach(startGraph);
}
function initGraph() {
    document.addEventListener("DOMContentLoaded", () => findGraphs(document));
    document.body.addEventListener("htmx:afterSwap", () => findGraphs(document));
    findGraphs(document);
}
initGraph();
