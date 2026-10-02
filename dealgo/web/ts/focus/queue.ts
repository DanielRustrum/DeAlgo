// The up-next list.
//
// Part of Focus mode; see main.ts.

/** One row of the up-next list. */
function buildQueueRow(item: FocusItem): HTMLLIElement {
  const row = document.createElement("li");
  row.dataset["video"] = String(item.id);

  const title = document.createElement("span");
  title.className = "queue-title";
  if (focusIsRead(item)) {
    const tag = document.createElement("span");
    tag.className = "pill pill-post";
    tag.textContent = item.kind === "post" ? "post" : item.source.toLowerCase();
    title.appendChild(tag);
    title.appendChild(document.createTextNode(" "));
  }
  title.appendChild(document.createTextNode(item.title));

  const meta = document.createElement("span");
  meta.className = "meta";
  meta.textContent = queueRowMeta(item);

  row.appendChild(title);
  row.appendChild(meta);
  return row;
}

/** The line under a queue row's title: source, feed, and length for a video. */
function queueRowMeta(item: FocusItem): string {
  let line = item.channel;
  if (item.playlist) line += ` · ${item.playlist}`;
  if (item.kind === "video" && item.duration && item.duration !== "—") {
    line += ` · ${item.duration}`;
  }
  return line;
}

/** Rebuilt from the server's own queue rather than by deleting rows, so the
 *  list cannot drift away from what actually plays next. */
function paintFocusQueue(sitting: FocusSitting, items: FocusItem[]): void {
  const list = sitting.elements.list;
  list.textContent = "";
  if (items.length === 0) {
    const none = document.createElement("li");
    none.className = "empty";
    none.textContent = "Nothing after this one.";
    list.appendChild(none);
    return;
  }
  items.forEach((item): void => {
    list.appendChild(buildQueueRow(item));
  });
}
