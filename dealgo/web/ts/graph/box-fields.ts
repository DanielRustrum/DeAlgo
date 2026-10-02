// The panel's fields for feeds, triggers, groups, sorts and filters.
//
// Part of the Configuration canvas; see main.ts.

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

/** A group's own panel: what it is called, and a way to hand it on. */
function graphGroupFields(form: HTMLElement, node: GraphNodeView): void {
  const give = document.createElement("a");
  give.className = "btn btn-quiet";
  give.href = `/graph/nodes/${node.id}/export`;
  give.textContent = "Export";
  give.title = "Save this group as a file to give to somebody else";
  form.appendChild(give);

  form.appendChild(
    graphElement(
      "p",
      "hint",
      "Everything inside the rectangle travels with it, and goes into the file. Channels travel as their YouTube ids; feeds travel as names, and are made afresh by whoever loads them.",
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
