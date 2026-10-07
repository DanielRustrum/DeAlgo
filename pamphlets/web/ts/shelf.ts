// The Feed page's shelf: dragging feeds into your own order.
//
// Only while arranging (the shelf carries .is-arranging, and its tiles are
// draggable). A tile is dragged within its own part of the shelf —
// favourites among favourites, the rest among the rest — and the others make
// room as it goes, so what you see when you let go is the order that is
// sent. The server answers with the shelf, which replaces this one: its word
// is the order that stuck. Each tile also has arrow buttons, which work
// without this script and without a pointer.
//
// Structure: top-level `function` declarations and one call at the bottom.
// This is a plain script that htmx re-runs on every boosted navigation, and a
// top-level `const` or `class` would throw "already declared" the second time.

/** The tile being dragged, held on the document between events. */
function shelfDragged(): HTMLElement | null {
  return document.querySelector<HTMLElement>(".feed-tile.is-dragging");
}

/** The tile an event happened on, if it is one that may be arranged. */
function shelfTileFrom(target: EventTarget | null): HTMLElement | null {
  if (!(target instanceof Element)) return null;
  const tile = target.closest<HTMLElement>(".feed-tile");
  return tile && tile.closest(".is-arranging") ? tile : null;
}

/** Every feed id on the shelf, in the order the page now shows them. */
function shelfOrder(): string {
  return Array.from(document.querySelectorAll<HTMLElement>("#feed-shelf .feed-tile"))
    .map((tile) => tile.dataset["feed"] ?? "")
    .filter((id) => id !== "")
    .join(",");
}

/** Send the order as it stands, and take the shelf the server answers with. */
function shelfSend(): void {
  window.htmx?.ajax("POST", "/feed/arrange", {
    target: "#feed-shelf",
    swap: "outerHTML",
    values: { order: shelfOrder(), arrange: "1" },
  });
}

/** Whether a point is before a tile's middle, reading left to right, top to bottom. */
function shelfBefore(tile: HTMLElement, x: number, y: number): boolean {
  const box = tile.getBoundingClientRect();
  if (y < box.top) return true;
  if (y > box.bottom) return false;
  return x < box.left + box.width / 2;
}

function onShelfDragStart(event: DragEvent): void {
  const tile = shelfTileFrom(event.target);
  if (!tile) return;
  tile.classList.add("is-dragging");
  tile.dataset["startOrder"] = shelfOrder();
  if (event.dataTransfer) {
    event.dataTransfer.effectAllowed = "move";
    // Some browsers will not start a drag that carries nothing.
    event.dataTransfer.setData("text/plain", tile.dataset["feed"] ?? "");
  }
}

function onShelfDragOver(event: DragEvent): void {
  const dragged = shelfDragged();
  const over = shelfTileFrom(event.target);
  if (!dragged || !over) return;
  // Only among its own part: a favourite is moved out by its star, not by
  // being dropped among the rest.
  if (over.parentElement !== dragged.parentElement) return;
  event.preventDefault();
  if (event.dataTransfer) event.dataTransfer.dropEffect = "move";
  if (over === dragged) return;
  const before = shelfBefore(over, event.clientX, event.clientY);
  over.parentElement?.insertBefore(dragged, before ? over : over.nextElementSibling);
}

function onShelfDrop(event: DragEvent): void {
  if (shelfDragged()) event.preventDefault();
}

function onShelfDragEnd(): void {
  const dragged = shelfDragged();
  if (!dragged) return;
  dragged.classList.remove("is-dragging");
  const before = dragged.dataset["startOrder"];
  delete dragged.dataset["startOrder"];
  // Sent once, when the drag is over, and only if anything moved.
  if (before !== shelfOrder()) shelfSend();
}

function initShelf(): void {
  // The listeners are on the document, so they outlive every swap of the
  // shelf — and are added once, however often htmx runs this file again.
  const root = document.documentElement;
  if (root.dataset["shelfReady"]) return;
  root.dataset["shelfReady"] = "1";
  document.addEventListener("dragstart", onShelfDragStart);
  document.addEventListener("dragover", onShelfDragOver);
  document.addEventListener("drop", onShelfDrop);
  document.addEventListener("dragend", onShelfDragEnd);
}

initShelf();
