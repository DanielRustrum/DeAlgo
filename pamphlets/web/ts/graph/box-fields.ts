// The panel's fields for feeds, triggers, groups, sorts and filters.
//
// Part of the Configuration canvas; see main.ts.

/** A feed's reading windows in its panel, and whether it is open now. */
function graphFeedWindows(form: HTMLElement, feed: GraphFeed): void {
  if (feed.windows.length === 0) return;
  const group = graphElement("div", "graph-group");
  group.appendChild(graphElement("span", "graph-group-name", "Reading"));
  for (const window of feed.windows) {
    group.appendChild(graphElement("span", "graph-group-note", window));
  }
  group.appendChild(
    graphElement(
      "span",
      feed.open ? "graph-group-note is-open" : "graph-group-note is-shut",
      feed.open ? "Open now." : "Shut now.",
    ),
  );
  form.appendChild(group);
}

/** A feed's panel fields: its size cap and per-run cap. */
function graphFeedFields(form: HTMLElement, node: GraphNodeView): void {
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
  ] as const) {
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

/** A trigger's panel fields: its gap or schedule, and its window when it opens one. */
function graphTriggerFields(form: HTMLElement, node: GraphNodeView): void {
  // Wired to a feed, it opens a window rather than setting something off, and
  // the one thing it needs that it does not otherwise is how long.
  if (node.trigger?.opens === true) {
    const window = document.createElement("input");
    window.type = "number";
    window.name = "duration_minutes";
    window.min = "1";
    window.value = String(node.trigger.duration ?? 30);
    form.appendChild(graphLabelled("Open for, in minutes", window));
  }
  if (node.trigger?.kind === "schedule") {
    const cron = document.createElement("input");
    cron.type = "text";
    cron.name = "cron";
    cron.value = node.trigger.cron ?? "0 9 * * *";
    cron.placeholder = "0 9 * * *";
    cron.spellcheck = false;
    form.appendChild(graphLabelled("Cron, in UTC", cron));
    form.appendChild(
      graphElement("p", "hint", `minute hour day month weekday — ${graphNextFiring(node)}`),
    );
    return;
  }
  const said = node.trigger?.every;
  const amount = document.createElement("input");
  amount.type = "number";
  amount.name = "every_minutes";
  amount.min = "1";
  amount.value = String(said?.amount ?? 60);

  const unit = document.createElement("select");
  unit.name = "every_unit";
  for (const choice of said?.units ?? []) {
    const option = document.createElement("option");
    option.value = choice.name;
    option.textContent = choice.label;
    option.selected = choice.name === said?.unit;
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
function graphNextFiring(node: GraphNodeView): string {
  const next = node.trigger?.next ?? null;
  if (next === null) return "it does not come round at all";
  return `next ${new Date(next).toLocaleString()}`;
}

/** A group's own panel: what it is called, a way to hand it on, and — for one
 *  loaded from a file — a way to bring it up to date with a newer copy. */
function graphGroupFields(state: GraphState, form: HTMLElement, node: GraphNodeView): void {
  // Its colour: the theme's own, as a comment's are.
  if (node.look !== null) {
    form.appendChild(graphLabelled("Colour", graphLeafletSelect("look_colour", node.look.colours, node.look.colour)));
  }
  // A group is not saved as a file any more — a Canvas box is. One loaded
  // from a file saved before can still be brought up to date from it.
  const row = graphElement("div", "graph-group-files");

  if (node.imported !== null) {
    // A file input behind a button: the browser cannot reopen the file it was
    // loaded from, so the newer copy is chosen again — and checked to be a
    // copy of the same group before anything changes.
    const pick = document.createElement("input");
    pick.type = "file";
    pick.accept = "application/json,.json";
    pick.hidden = true;
    const update = graphElement("button", "btn btn-quiet", "Update from file…") as HTMLButtonElement;
    update.type = "button";
    update.title = "Load a newer copy of the file this group came from";
    update.addEventListener("click", (): void => pick.click());
    pick.addEventListener("change", (): void => {
      const file = pick.files?.[0];
      if (file !== undefined) void updateGraphGroup(state, node.id, file);
      pick.value = "";
    });
    row.append(update, pick);
  }
  form.appendChild(row);

  if (node.imported !== null) {
    const when = node.imported.at !== null ? new Date(node.imported.at).toLocaleString() : "";
    const from = node.imported.from !== "" ? `“${node.imported.from}”` : "a file";
    form.appendChild(
      graphElement(
        "p",
        "hint",
        `Loaded from ${from}${when ? `, last on ${when}` : ""}. Updating keeps the boxes you moved where you put them, keeps any you added yourself, and never deletes a feed or what is in it.`,
      ),
    );
  }

  form.appendChild(
    graphElement(
      "p",
      "hint",
      "Everything inside the rectangle travels with it, and goes into the file. Sources travel as their own ids; feeds travel as names, and are made afresh by whoever loads them.",
    ),
  );
}

/** What to put the batch in order of, and which way round. */
function graphSortFields(form: HTMLElement, sort: GraphSort): void {
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

  // "Most first" means one thing for a duration and another for a date, so
  // the ends are named after what is being sorted, and renamed when that
  // changes rather than leaving the reader to work out which end is which.
  const way = graphEndsField(form, sort, "Which end first");
  by.addEventListener("change", (): void => nameGraphSortEnds(way, sort, by.value));

  form.appendChild(
    graphElement(
      "p",
      "hint",
      "The order things are added to the feed in. Views and likes are read when the details are fetched, so a video nobody has looked up yet sorts last.",
    ),
  );
}

/** Which end of an ordering comes first.
 *
 *  Shared, because a plugin's ordering is asked the same thing: it works its
 *  own number out, and which end of that number leads is still the reader's
 *  to choose. Given a name, it says "most X first" rather than "most first",
 *  since a number nobody named needs saying what it is a number of. */
function graphEndsField(
  form: HTMLElement, sort: GraphSort, label: string, named = ""
): HTMLSelectElement {
  const way = document.createElement("select");
  way.name = "sort_dir";
  for (const value of ["desc", "asc"] as const) {
    const option = document.createElement("option");
    option.value = value;
    option.selected = (value === "desc") === sort.desc;
    way.appendChild(option);
  }
  if (named === "") {
    nameGraphSortEnds(way, sort, sort.by);
  } else {
    const [most, least] = way.options;
    if (most !== undefined) most.textContent = `Most ${named.toLowerCase()} first`;
    if (least !== undefined) least.textContent = `Least ${named.toLowerCase()} first`;
  }
  form.appendChild(graphLabelled(label, way));
  return way;
}

/** Label the two ends for whatever is being sorted by. */
function nameGraphSortEnds(way: HTMLSelectElement, sort: GraphSort, by: string): void {
  const key = sort.keys.find((entry): boolean => entry.name === by);
  const [first, last] = key === undefined ? ["Most first", "Least first"] : [key.first, key.last];
  const options = way.options;
  if (options.length < 2) return;
  const falling = options[0];
  const rising = options[1];
  if (falling !== undefined) falling.textContent = first;
  if (rising !== undefined) rising.textContent = last;
}

/** A Filter or a Sort box. Neither carries a rule of its own any more: what
 *  a box narrows by is the conditions slotted under it, one piece per
 *  condition, so the canvas says what a box does without being opened. */
function graphFilterFields(form: HTMLElement, node: GraphNodeView): void {
  form.appendChild(
    graphElement(
      "p",
      "hint",
      node.kind === "sort"
        ? "Slot an Order piece under this to say what to put the batch in order by. Without one it orders nothing."
        : "Slot conditions under this — Title has, Longer than, At most — one piece each. Everything they all agree on gets past. Without any it narrows nothing.",
    ),
  );
}

/** An Activation's parameters: a name and a default each, as many as it
 *  takes. An Activate box elsewhere fills them; its flow reads them as
 *  {{ params.name }}, and from its { } port. */
function graphActivationFields(form: HTMLElement, node: GraphNodeView): void {
  form.appendChild(graphElement("p", "hint",
    "Set off by an Activate box elsewhere — or Run now, with the defaults. Its flow reads each value as {{ params.name }}, and its { } port gives them out as one row."));
  const list = graphElement("div", "graph-params");
  const row = (name: string, fallback: string): void => {
    const line = graphElement("div", "graph-param");
    const named = document.createElement("input");
    named.type = "text";
    named.name = "param_name";
    named.value = name;
    named.placeholder = "name";
    named.spellcheck = false;
    named.setAttribute("aria-label", "Parameter name");
    const given = document.createElement("input");
    given.type = "text";
    given.name = "param_default";
    given.value = fallback;
    given.placeholder = "default";
    given.setAttribute("aria-label", "Default value");
    const drop = graphElement("button", "btn btn-quiet graph-param-drop", "✕");
    drop.setAttribute("type", "button");
    drop.title = "Take this parameter away";
    drop.addEventListener("click", (): void => line.remove());
    line.appendChild(named);
    line.appendChild(given);
    line.appendChild(drop);
    list.appendChild(line);
  };
  for (const one of node.activation?.params ?? []) row(one.name, one.default);
  if ((node.activation?.params ?? []).length === 0) row("", "");
  form.appendChild(graphLabelled("Parameters", list));
  const more = graphElement("button", "btn btn-quiet", "Add a parameter");
  more.setAttribute("type", "button");
  more.addEventListener("click", (): void => row("", ""));
  form.appendChild(more);
  const last = node.activation?.last ?? {};
  const names = Object.keys(last);
  if (names.length > 0) {
    form.appendChild(graphElement("p", "hint",
      "Last set off with: " + names.map((one): string => `${one} = “${last[one] ?? ""}”`).join(", ")));
  }
}

/** An Activate box: which Activation it sets off — in any canvas — and what
 *  it fills each of that Activation's parameters with. */
function graphActivateFields(form: HTMLElement, node: GraphNodeView): void {
  const said = node.activate;
  form.appendChild(graphElement("p", "hint",
    "Once a run gets anything here, it sets the Activation off. Fill each value with words, or {{ fields }} of the first item to arrive — {{ title }}, {{ link }} — or of the data wired into its { } port, as {{ data… }}."));
  const pick = document.createElement("select");
  pick.name = "activate_target";
  const none = document.createElement("option");
  none.value = "";
  none.textContent = said?.choices.length ? "Choose an Activation…" : "No Activation triggers yet";
  pick.appendChild(none);
  for (const choice of said?.choices ?? []) {
    const option = document.createElement("option");
    option.value = String(choice.id);
    option.textContent = choice.where ? `${choice.title} — ${choice.where}` : choice.title;
    option.selected = choice.id === said?.target;
    pick.appendChild(option);
  }
  form.appendChild(graphLabelled("Sets off", pick));
  const values = graphElement("div", "graph-params");
  form.appendChild(values);
  // One field per parameter of the Activation chosen, drawn again on a new choice.
  const draw = (): void => {
    values.replaceChildren();
    const chosen = (said?.choices ?? []).find((one): boolean => String(one.id) === pick.value);
    if (chosen === undefined) return;
    if (chosen.params.length === 0) {
      values.appendChild(graphElement("p", "hint", "It takes no parameters: it is simply set off."));
      return;
    }
    for (const name of chosen.params) {
      const field = document.createElement("input");
      field.type = "text";
      field.name = `activate_value_${name}`;
      field.value = said?.values[name] ?? "";
      field.placeholder = "its default";
      field.spellcheck = false;
      values.appendChild(graphLabelled(name, field));
    }
  };
  pick.addEventListener("change", draw);
  draw();
}
