// The panel beside a picked box: its tabs, its form, and removing it.
//
// Part of the Configuration canvas; see main.ts.

/** A form field with its label. */
function graphLabelled(name: string, control: HTMLElement): HTMLElement {
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
function renderGraphPopover(state: GraphState): void {
  state.parts.layer.querySelectorAll(".graph-pop").forEach((old): void => old.remove());
  renderGraphPickedBar(state);

  const node = state.nodes.find((entry): boolean => entry.id === state.selectedNode);
  if (node === undefined) return;
  const box = state.boxes.get(node.id);
  if (box === undefined) return;

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
  if (tested) pop.appendChild(graphPopTabs(node, showing));

  if (showing === "test") {
    pop.classList.add("is-wide");
    pop.appendChild(graphTrialBody(state, node));
  } else {
    pop.appendChild(graphNodeForm(state, node));
  }
  state.parts.layer.appendChild(pop);
}

/** The two sides of a trigger: what it does, and what it would do. */
function graphPopTabs(node: GraphNodeView, showing: string): HTMLElement {
  const strip = graphElement("div", "graph-pop-tabs");
  for (const [name, label] of [["settings", "Settings"], ["test", "Test"]] as const) {
    const tab = graphElement("button", "graph-pop-tab", label);
    tab.setAttribute("type", "button");
    tab.dataset["tab"] = name;
    tab.dataset["for"] = String(node.id);
    if (name === showing) tab.classList.add("is-on");
    strip.appendChild(tab);
  }
  return strip;
}

/** Whether opening this Test tab has to run a trial, or only show one.
 *
 *  Only a trigger can start one. Every other box has a Test tab because a
 *  trial already came through it, and asking the server to test a filter is
 *  refused — which used to take the whole trial down with it. */
function graphTabNeedsRun(
  box: GraphNodeView | undefined,
  trial: GraphTrial | null,
  wanted: string,
): boolean {
  if (wanted !== "test" || box === undefined || box.trigger === null) return false;
  return trial === null || trial.node !== box.id;
}

/** This box's share of the last trial, if it had one. */
function graphShareOf(state: GraphState, node: GraphNodeView): GraphShare | null {
  return state.trial?.boxes.get(node.id) ?? null;
}

/** What this box would do, inside the box itself. */
function graphTrialBody(state: GraphState, node: GraphNodeView): HTMLElement {
  const sheet = graphElement("div", "graph-sheet");
  const trial = state.trial;

  if (trial === null || trial.asking) {
    sheet.appendChild(graphElement("p", "hint", "Working it out…"));
    return sheet;
  }

  const share = graphShareOf(state, node);
  if (share === null) {
    sheet.appendChild(
      graphElement(
        "p",
        "hint",
        "The last test did not come through this node. Run one from a trigger.",
      ),
    );
    return sheet;
  }

  sheet.appendChild(
    graphElement("p", "hint", "If it ran now. Nothing here has been added or written."),
  );
  // A feed is where things arrive; everywhere else is somewhere they pass.
  sheet.appendChild(
    graphJudgedList(
      node.kind === "feed" ? "Would land" : "Gets through",
      share.through,
      "through",
      true,
    ),
  );
  if (share.held.length > 0) {
    sheet.appendChild(graphJudgedList("Held back", share.held, "held", true));
  }
  return sheet;
}

/** How many are picked, and the one thing to do with several at once.
 *
 *  Over the canvas rather than beside a node, because it is not about any one
 *  of them. */
function renderGraphPickedBar(state: GraphState): void {
  const bar = state.parts.canvas
    .closest<HTMLElement>(".graph-panel")
    ?.querySelector<HTMLElement>("[data-graph-picked]");
  if (!bar) return;

  bar.hidden = state.picked.size < 2;
  if (bar.hidden) return;

  bar.textContent = "";
  bar.appendChild(graphElement("span", "", `${state.picked.size} picked`));
  // What can be done to all of them, as the keys do it: copy, cut, paste
  // what is waiting, take them away.
  const action = (label: string, data: string, keys: string, danger = false): void => {
    const button = graphElement("button", danger ? "btn btn-danger" : "btn btn-quiet", label);
    button.setAttribute("type", "button");
    button.dataset[data] = "1";
    button.title = keys;
    bar.appendChild(button);
  };
  action("Copy", "copyPicked", "Ctrl+C");
  action("Cut", "cutPicked", "Ctrl+X — they move when pasted");
  if (graphClip() !== null) action("Paste", "pasteHere", "Ctrl+V");
  action("Remove", "removePicked", "Delete", true);
}

/** Move the open panel to wherever its node is now.
 *
 *  Not only the node being dragged: a group takes what it surrounds with it,
 *  and a selection takes the rest of itself, so the open one may be moving
 *  without being the one under the pointer. */
function keepGraphPopoverWithItsNode(state: GraphState): void {
  const open = state.nodes.find((entry): boolean => entry.id === state.selectedNode);
  if (open === undefined) return;
  const box = state.boxes.get(open.id);
  if (box !== undefined) placeGraphPopover(state, open, box);
}

/** Put the open box beside the box it belongs to, and keep it there.
 *
 *  Called again on every frame of a drag: a detail panel that stayed behind
 *  while its box moved away would be pointing at nothing. */
function placeGraphPopover(
  state: GraphState,
  node: GraphNodeView,
  box: HTMLElement,
  pop?: HTMLElement,
): void {
  const panel = pop ?? state.parts.layer.querySelector<HTMLElement>(".graph-pop");
  if (!panel) return;
  panel.style.left = `${node.x + box.offsetWidth + 18}px`;
  panel.style.top = `${node.y}px`;
}

/** One form per box. Every kind has a name; what else it has depends. */
function graphNodeForm(state: GraphState, node: GraphNodeView): HTMLElement {
  const form = document.createElement("form");
  form.className = "graph-form";
  form.dataset["save"] = String(node.id);

  // Says this form carried the switch, so the server can tell an unticked box
  // from a form that never showed one. Without it, an unticked box and an
  // absent one look the same and nothing could ever be switched off.
  // Layout boxes do nothing to switch off: a comment, a relay, a canvas
  // (whose insides run whatever it says). They carry no switch, and so no
  // word that the form carried one — which would read as switching them off.
  if (node.kind !== "comment" && node.kind !== "relay" && node.kind !== "canvas") {
    const carried = document.createElement("input");
    carried.type = "hidden";
    carried.name = "box_form";
    carried.value = "1";
    form.appendChild(carried);
    form.appendChild(graphActive(node));
  }

  const name = document.createElement("input");
  name.type = "text";
  name.name = "label";
  name.value = node.title;
  form.appendChild(graphLabelled("Name", name));

  if (node.kind === "group") graphGroupFields(state, form, node);
  // Conditions first: an Order piece carries a sort as well, and a plugin's
  // condition is a piece as well, so the narrowest answer has to be asked
  // before the broad ones.
  else if (node.condition !== null) graphConditionFields(form, node, node.condition);
  else if (node.kind === "rule") graphPluginFields(form, node);
  else if (node.kind === "aggregation") graphAggregationFields(form, node);
  else if (node.leaflet !== null) graphLeafletFields(form, node);
  else if (node.kind === "pamphlet") graphPamphletFields(form, node);
  else if (node.kind === "format") graphFormatFields(form, node);
  else if (node.kind === "text") graphTextBoxFields(form, node);
  else if (node.kind === "transform") {
    form.appendChild(graphElement("p", "hint",
      "Wire items (▶) or data ({ }) into this — one or the other — and slot a piece under it to say what it makes of them. Count gives how many came in, as one number. What it gives out is data: for a Chart leaflet, a Format box, or another operation."));
  }
  else if (node.stamp !== null) graphStampFields(form, node);
  else if (node.piece !== null) graphPieceFields(form, node);
  else if (node.store !== null) graphStoreFields(form, node.store);
  else if (node.kind === "source") graphChannelFields(state, form, node);
  else if (node.kind === "feed") graphFeedFields(form, node);
  else if (node.trigger !== null) graphTriggerFields(form, node);
  else if (node.kind === "canvas") {
    form.appendChild(graphElement("p", "hint",
      node.frozen
        ? "Frozen: nothing inside it runs — no trigger fires, nothing is polled, nothing reaches a feed — however deep. Thaw it to put everything back as it was."
        : "A canvas of its own. Double-click it, or press Open, to work inside it; boxes inside are wired only to each other, and every one of them runs. Freeze it to stop all of it at once."));
  }
  else if (node.kind === "comment" && node.comment !== null) {
    const words = document.createElement("textarea");
    words.name = "comment_text";
    words.rows = 6;
    words.value = node.comment.text;
    form.appendChild(graphLabelled("Words", words));
    form.appendChild(graphLabelled("Colour", graphLeafletSelect("comment_colour", node.comment.colours, node.comment.colour)));
    form.appendChild(graphElement("p", "hint", "Or double-click the comment to write in it where it is. It is wired to nothing, and changes nothing."));
  }
  else if (node.kind === "relay") {
    if (node.relay !== null) {
      form.appendChild(graphRelaySides(form, node.relay.in, node.relay.out));
      form.appendChild(graphLabelled("Colour", graphLeafletSelect("look_colour", node.relay.colours, node.relay.colour)));
    }
    form.appendChild(graphElement("p", "hint",
      "A point a wire passes through, to route it round other boxes. It takes one wire in and passes it on, unchanged, to as many boxes as you like."));
  }
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

  // The editor: what comes in and goes out, and — for a data box — its
  // settings beside them. A double-click on the box opens it too.
  const editor = graphEditorFor(node.kind);
  if (node.kind === "canvas") {
    const open = graphElement("button", "btn btn-quiet", "Open");
    open.setAttribute("type", "button");
    open.title = "Or double-click the box";
    open.dataset["editor"] = String(node.id);
    buttons.appendChild(open);
    // Everything inside it, as a .pam file to hand somebody else.
    const save = document.createElement("a");
    save.className = "btn btn-quiet";
    save.href = `/graph/nodes/${node.id}/export`;
    save.textContent = "Save as file";
    save.title = "Save this canvas, and everything inside it, as a .pam file";
    buttons.appendChild(save);
    // Everything inside stops, or starts again — each box keeping its switch.
    const freeze = graphElement("button", "btn btn-quiet", node.frozen ? "Thaw" : "Freeze");
    freeze.setAttribute("type", "button");
    freeze.title = node.frozen ? "Let everything inside it run again" : "Stop everything inside it from running";
    freeze.addEventListener("click", (): void => {
      void applyGraph(state, `/graph/nodes/${node.id}/freeze`,
        new URLSearchParams({ frozen: node.frozen ? "0" : "1" }));
    });
    buttons.appendChild(freeze);
  }
  if (editor !== null) {
    const open = graphElement("button", "btn btn-quiet", editor === "settings" ? "Open editor" : "Input & output");
    open.setAttribute("type", "button");
    open.title = "Or double-click the box";
    open.dataset["editor"] = String(node.id);
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

  if (state.busy) form.setAttribute("aria-busy", "true");
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
async function removeGraphPicked(state: GraphState, fromKey = false): Promise<void> {
  const going = state.nodes.filter((node): boolean => state.picked.has(node.id));
  if (going.length === 0) return;

  const costly = going.filter((node): boolean => graphRemovalWarning(node) !== "");
  // From the Delete key, with nothing at stake, it goes at once — and an undo
  // puts it back, from a copy taken first. Where a channel's history or a
  // feed's items would go too, it asks, as the Remove button does: that
  // cannot be put back.
  const putBack = fromKey && costly.length === 0 ? await graphTakeBackCopy(state, going) : null;
  if (putBack === null) {
    const named = going.map((node): string => node.title).join(", ");
    const asked =
      costly.length === 0
        ? `Remove ${going.length} node${going.length === 1 ? "" : "s"}? (${named})`
        : `Remove ${named}? The channels and feeds among them go too, with their history; anything already in a feed stays put.`;
    if (!(await askGraphSure(state, asked))) return;
  }

  state.selectedNode = null;
  state.picked = new Set<number>();
  for (const node of going) {
    await applyGraph(state, `/graph/nodes/${node.id}/delete`, new URLSearchParams());
  }
  if (putBack !== null) rememberGraphUndo(state, "the boxes you took away", putBack);
}

/** A way to put boxes back once they are gone: a copy of them, pasted where
 *  they were, and the wires to the boxes around them drawn again. Null if
 *  no copy could be taken — then it is asked about instead. */
async function graphTakeBackCopy(state: GraphState, going: GraphNodeView[]): Promise<(() => Promise<void>) | null> {
  let answer: unknown;
  try {
    answer = await askGraph("/graph/copy", new URLSearchParams({ nodes: going.map((node): number => node.id).join(",") }));
  } catch {
    return null;
  }
  const clip = asGraphRecord(answer)?.["clip"];
  if (clip === undefined) return null;
  const ids = new Set(going.map((node): number => node.id));
  const boxes = going.filter((node): boolean => node.piece === null);
  const left = Math.min(...(boxes.length > 0 ? boxes : going).map((node): number => node.x));
  const top = Math.min(...(boxes.length > 0 ? boxes : going).map((node): number => node.y));
  // The wires out to boxes that stay; the ones between the boxes going travel in the copy.
  const across = state.wires
    .filter((wire): boolean => ids.has(wire.from) !== ids.has(wire.to))
    .map((wire): { from: number; to: number; carries: GraphCarries } => ({
      from: wire.from, to: wire.to, carries: graphWireCarries(state, wire),
    }));
  return async (): Promise<void> => {
    const pasted = asGraphRecord(await askGraph("/graph/paste", new URLSearchParams({
      clip: JSON.stringify(clip), x: String(left), y: String(top),
    })));
    const made = asGraphRecord(pasted?.["made"]) ?? {};
    const now = (id: number): number => (typeof made[String(id)] === "number" ? (made[String(id)] as number) : id);
    for (const wire of across) {
      await askGraph("/graph/connect", new URLSearchParams({
        source: String(now(wire.from)), target: String(now(wire.to)), carries: wire.carries,
      }));
    }
    await applyGraph(state, "/api/graph", null);
  };
}

/** The switch every box has: whether it is doing anything at all.
 *
 *  A box that is off is drawn greyed, and a filter that is off stops the flow
 *  rather than passing everything — off means off, not "no opinion". */
function graphActive(node: GraphNodeView): HTMLElement {
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
function graphRemovalWarning(node: GraphNodeView): string {
  // Only where something is actually at stake. An empty source box names no
  // source, so taking it away costs nothing — and asking "its history goes
  // too" of a box with no history is a frightening question about nothing.
  if (node.kind === "source" && node.detail !== null) {
    return `Stop watching ${node.title}? Its history goes too; anything already in a feed stays put.`;
  }
  if (node.kind === "feed") {
    return `Remove the feed ${node.title}? What it collected inside Pamphlets goes with it.`;
  }
  if (node.kind === "canvas" && !node.note.startsWith("empty")) {
    return `Remove the canvas ${node.title}? Everything inside it goes too — sources and feeds included.`;
  }
  return "";
}

/** Pick one of the sources already watched, out of however many there are.
 *
 *  A search box above a real select rather than a list built from scratch: the
 *  select keeps the keyboard, the form and the screen reader it already had,
 *  and the box only decides which options are in it. */
function graphSourcePicker(
  state: GraphState,
  form: HTMLElement,
  kind: string,
): void {
  // Only sources of this box's own kind. A Subreddit box that offered a
  // YouTube channel would be offering something it could not then be.
  const offered =
    kind === "" ? state.sources : state.sources.filter((one): boolean => one.kind === kind);
  if (offered.length === 0) return;

  const search = document.createElement("input");
  search.type = "search";
  search.placeholder = "Search sources…";
  // No name: this narrows the list, it is not part of the answer.
  search.autocomplete = "off";

  const pick = document.createElement("select");
  pick.name = "source_pk";
  pick.size = Math.min(6, offered.length + 1);

  const fill = (): void => {
    const chosen = pick.value;
    pick.textContent = "";

    const none = document.createElement("option");
    none.value = "";
    none.textContent = "— or add one below —";
    pick.appendChild(none);

    const matching = offered.filter((source): boolean =>
      graphMatches(source.title, search.value),
    );
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
function graphMatches(name: string, query: string): boolean {
  const terms = query.toLowerCase().split(/\s+/).filter((term): boolean => term !== "");
  const against = name.toLowerCase();
  return terms.every((term): boolean => against.includes(term));
}

/** A drawing of a relay to choose its sides on: the dot, and its four
 *  sides. Choose whether you are placing the way in or the way out, then
 *  press a side; placed on the other one's side, the two swap. */
function graphRelaySides(form: HTMLElement, taken: string, given: string): HTMLElement {
  const sides = { in: taken, out: given };
  const fields = { in: document.createElement("input"), out: document.createElement("input") };
  for (const end of ["in", "out"] as const) {
    fields[end].type = "hidden";
    fields[end].name = `look_${end}`;
    fields[end].value = sides[end];
    form.appendChild(fields[end]);
  }
  let placing: "in" | "out" = "in";
  const holder = graphElement("div", "graph-relay-sides");
  const modes = graphElement("div", "graph-chart-kinds");
  modes.setAttribute("role", "radiogroup");
  modes.setAttribute("aria-label", "Placing");
  const drawing = graphElement("div", "graph-relay-drawing");
  drawing.appendChild(graphElement("span", "graph-relay-dot"));
  const buttons = new Map<string, HTMLElement>();
  const show = (): void => {
    modes.querySelectorAll<HTMLElement>("button").forEach((one): void => {
      one.setAttribute("aria-checked", String(one.dataset["placing"] === placing));
    });
    for (const [side, button] of buttons) {
      const role = side === sides.in ? "in" : side === sides.out ? "out" : "";
      button.dataset["role"] = role;
      button.textContent = role === "in" ? "In" : role === "out" ? "Out" : "";
      button.setAttribute("aria-label", `${side}${role ? `: ${role}` : ""}`);
    }
    fields.in.value = sides.in;
    fields.out.value = sides.out;
  };
  for (const [end, label] of [["in", "Placing the way in"], ["out", "Placing the way out"]] as const) {
    const mode = graphElement("button", "graph-chart-kind", label);
    mode.setAttribute("type", "button");
    mode.setAttribute("role", "radio");
    mode.dataset["placing"] = end;
    mode.addEventListener("click", (): void => {
      placing = end;
      show();
    });
    modes.appendChild(mode);
  }
  for (const side of ["top", "left", "right", "bottom"]) {
    const button = graphElement("button", `graph-relay-side is-${side}`);
    button.setAttribute("type", "button");
    button.title = `The ${side} side`;
    button.addEventListener("click", (): void => {
      const other = placing === "in" ? "out" : "in";
      // Onto the other end's side: they swap, so there is always one of each.
      if (sides[other] === side) sides[other] = sides[placing];
      sides[placing] = side;
      show();
    });
    buttons.set(side, button);
    drawing.appendChild(button);
  }
  holder.appendChild(graphElement("span", "graph-field-name", "Sides — where its wire comes in and goes out"));
  holder.appendChild(modes);
  holder.appendChild(drawing);
  show();
  return holder;
}
