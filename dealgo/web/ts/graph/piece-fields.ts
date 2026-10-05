// The panel's fields for pieces, stamps and repositories.
//
// Part of the Configuration canvas; see main.ts.

/** A box that marks what passes through it rather than narrowing it. */
function graphStampFields(form: HTMLElement, node: GraphNodeView): void {
  if (node.kind === "tag") {
    const named = document.createElement("input");
    named.type = "text";
    named.name = "marks";
    named.value = node.stamp?.marks ?? "";
    named.placeholder = "long reads";
    form.appendChild(graphLabelled("Marks it", named));
    form.appendChild(
      graphElement(
        "p",
        "hint",
        "Everything through this box carries the tag from here on. A Filter box later in the path can ask for it.",
      ),
    );
    return;
  }

  form.appendChild(
    graphElement(
      "p",
      "hint",
      node.kind === "decay"
        ? "Slot a Timer under this to say how long you get with each item in Focus. A Lock under it makes that time one you cannot pause."
        : "Slot a Timer under this to say how long an item stays in the feed, counted from when it arrives. After that it is taken out — it stays in your history and in any other feed that said nothing about expiry.",
    ),
  );
}

/** One condition. Exactly one thing to fill in, because that is what makes
 *  it one condition: a box narrowing three ways is three pieces. */
function graphConditionFields(
  form: HTMLElement, node: GraphNodeView, said: GraphCondition
): void {
  if (node.piece?.under == null) {
    const where = said.under === "sort" ? "a Sort box" : "a Filter box";
    form.appendChild(
      graphElement("p", "hint", `Loose on the canvas. Drop it on ${where} to slot it in.`),
    );
  }

  if (said.field === "order") {
    if (node.sort !== null) graphSortFields(form, node.sort);
    return;
  }

  if (said.field === "tags") {
    graphTagFields(form, said);
    return;
  }

  const field = document.createElement("input");
  field.type = said.field === "text" ? "text" : "number";
  field.name = "value";
  field.value = said.value;
  field.placeholder = said.field === "text" ? "" : "no limit";
  if (said.field !== "text") field.min = "1";

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
  } else {
    form.appendChild(graphLabelled(said.asks, field));
  }

  if (said.blurb !== "") form.appendChild(graphElement("p", "hint", said.blurb));
}

/** A list of tags: typed, commas between, or picked from every tag there is.
 *  A picked tag is added to the line, and picked again it comes off. */
function graphTagFields(form: HTMLElement, said: GraphCondition): void {
  const field = document.createElement("input");
  field.type = "text";
  field.name = "value";
  field.value = said.value;
  field.placeholder = "news, long reads";
  form.appendChild(graphLabelled(said.asks, field));

  const listed = (): string[] =>
    field.value
      .split(",")
      .map((one): string => one.trim().toLowerCase().split(/\s+/).join(" "))
      .filter((one): boolean => one !== "");

  if (said.choices.length > 0) {
    const chips = graphElement("div", "graph-tag-choices");
    const marked = (): void => {
      const now = listed();
      chips.querySelectorAll<HTMLButtonElement>("button").forEach((chip): void => {
        chip.setAttribute("aria-pressed", String(now.includes(chip.dataset["tag"] ?? "")));
      });
    };
    for (const tag of said.choices) {
      const chip = graphElement("button", "graph-tag-choice", tag);
      chip.setAttribute("type", "button");
      chip.dataset["tag"] = tag;
      chip.addEventListener("click", (): void => {
        const now = listed();
        field.value = (now.includes(tag)
          ? now.filter((one): boolean => one !== tag)
          : [...now, tag]
        ).join(", ");
        marked();
        field.dispatchEvent(new Event("input", { bubbles: true }));
        field.dispatchEvent(new Event("change", { bubbles: true }));
      });
      chips.appendChild(chip);
    }
    field.addEventListener("input", marked);
    marked();
    form.appendChild(chips);
  } else {
    form.appendChild(
      graphElement("p", "hint", "No tags yet. A Tag box puts them on, or tag items in a feed."),
    );
  }

  if (said.blurb !== "") form.appendChild(graphElement("p", "hint", said.blurb));
}

/** An augmentation. One field each: a Timer says how long, a Reset says
 *  when you get another. */
function graphPieceFields(form: HTMLElement, node: GraphNodeView): void {
  const piece = node.piece;
  if (piece === null) return;

  if (node.kind === "after-watch") {
    form.appendChild(
      graphElement(
        "p",
        "hint",
        piece.under === null
          ? "Loose on the canvas. Drop it on an Expire box to take items out once you watch them."
          : "Items leave once you watch them, at the next run. With a Timer slotted in too, they leave when watched or when that time from arriving runs out — whichever comes first.",
      ),
    );
    return;
  }

  if (node.kind === "lock") {
    form.appendChild(
      graphElement(
        "p",
        "hint",
        piece.under === null
          ? "Loose on the canvas. Drop it on a Decay box to make its time one you cannot pause."
          : "The Timer above this cannot be paused. The point of it is a stretch that runs whether you are looking or not.",
      ),
    );
    return;
  }

  if (node.kind === "alive") {
    const pair = graphElement("div", "graph-times");
    for (const [name, value, label] of [
      ["alive_from", piece.from, "From"],
      ["alive_to", piece.to, "To"],
    ] as const) {
      const when = document.createElement("input");
      when.type = "time";
      when.name = name;
      when.value = value;
      pair.appendChild(graphLabelled(label, when));
    }
    form.appendChild(pair);
  } else if (node.kind === "timer") {
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
  } else {
    const when = document.createElement("input");
    when.type = "text";
    when.name = "cron";
    when.value = piece.cron;
    when.placeholder = "0 9 * * *";
    form.appendChild(graphLabelled("Comes round on", when));
  }

  form.appendChild(
    graphElement(
      "p",
      "hint",
      piece.under === null
        ? "Loose on the canvas. Drop it on a box to slot it in — it changes what that box does."
        : node.kind === "alive"
          ? "Read on the clock, in UTC, and it narrows whatever else is slotted in: a sitting with time left on it is still no good outside these hours. An end before its start runs through midnight. Both the same means any time of day."
          : node.kind === "timer"
            ? "The clock starts when you open the feed, not at some hour of the day. Without a Reset under the same box you get one sitting and no more."
            : "Each time this comes round the Timer starts again. Several Resets are several chances to read.",
    ),
  );
}

/** A Deposit or a Withdraw box: which repository, and how much to pull.
 *
 *  The name is the whole of what joins the two ends, so it is the first
 *  field on both and says what it is for. */
function graphStoreFields(form: HTMLElement, store: GraphStore): void {
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
  group.appendChild(
    graphElement(
      "span",
      "graph-group-note",
      store.name === ""
        ? "Give it a name. Two boxes only share a repository when they share its name."
        : `${store.waiting} item${store.waiting === 1 ? "" : "s"} in ${store.name}.`,
    ),
  );
  form.appendChild(group);

  form.appendChild(
    graphElement(
      "p",
      "hint",
      store.pulls
        ? "Wire a trigger to this box to say when to pull. What comes out goes down whatever is wired on, oldest first, and is taken out of the repository."
        : "Everything wired in ends here and waits. Nothing reaches a feed through this box — a Withdraw box with the same name is what lets it out.",
    ),
  );
}
