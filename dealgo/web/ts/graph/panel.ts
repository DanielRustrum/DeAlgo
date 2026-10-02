// The panel beside a picked box: its tabs, its form, and removing it.
//
// Part of the Configuration canvas; see main.ts.

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

  if (node.kind === "group") graphGroupFields(form, node);
  // Conditions first: an Order piece carries a sort as well, and a plugin's
  // condition is a piece as well, so the narrowest answer has to be asked
  // before the broad ones.
  else if (node.condition !== null) graphConditionFields(form, node, node.condition);
  else if (node.kind === "rule") graphPluginFields(form, node);
  else if (node.stamp !== null) graphStampFields(form, node);
  else if (node.piece !== null) graphPieceFields(form, node);
  else if (node.store !== null) graphStoreFields(form, node.store);
  else if (node.kind === "source") graphChannelFields(state, form, node);
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
async function removeGraphPicked(state: GraphState): Promise<void> {
  const going = state.nodes.filter((node): boolean => state.picked.has(node.id));
  if (going.length === 0) return;

  const costly = going.filter((node): boolean => graphRemovalWarning(node) !== "");
  const named = going.map((node): string => node.title).join(", ");
  const asked =
    costly.length === 0
      ? `Remove ${going.length} node${going.length === 1 ? "" : "s"}? (${named})`
      : `Remove ${named}? The channels and feeds among them go too, with their history; anything already in a feed stays put.`;
  if (!(await askGraphSure(state, asked))) return;

  state.selectedNode = null;
  state.picked = new Set<number>();
  for (const node of going) {
    await applyGraph(state, `/graph/nodes/${node.id}/delete`, new URLSearchParams());
  }
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
    return `Remove the feed ${node.title}? What it collected inside De-Algo goes with it.`;
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
