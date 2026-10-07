// Focus mode: go through the queue, marking each item done as it finishes.
//
// Two sorts of thing arrive in the same queue. A video finishes on its own and
// the player says so. Everything else — a community post, an item from a feed
// somewhere else — is read, and has no end of its own, so reading time is the
// only thing that can advance it: hence the timer, and hence the pause, since
// something you are still reading should not slide out from under you.
//
// Advancing asks the server for the next item rather than walking the list it
// was given, so a queue left open overnight cannot resurrect something watched
// or removed in the meantime. The embedded list is only a preview.
//
// Structure: top-level `function` declarations, and one call at the bottom of
// this file. The parts in this folder are joined into the one focus.js the page
// loads (`make js`, ops/join_scripts.py), a plain script that htmx re-runs
// each time it swaps the Focus page in, and a top-level `const` or `class` would throw "already declared"
// on the second visit. Everything a sitting needs to remember therefore lives
// in one FocusSitting object, passed explicitly rather than captured.

/** Load the first video, with the origin the page is actually served from. */
function pointFrameAtFirstVideo(sitting: FocusSitting): void {
  const frame = sitting.elements.frame;
  if (!frame) return;
  // The origin has to be the host actually browsed to, not whatever
  // DEALGO_PUBLIC_URL happens to say.
  const source = frame.dataset["src"] ?? "";
  frame.src = `${source}&origin=${encodeURIComponent(window.location.origin)}`;
}

/** Wire up Next, Skip and the timer's pause button. */
function bindFocusControls(sitting: FocusSitting): void {
  sitting.elements.next.addEventListener("click", (): void => advanceFocus(sitting, true));
  sitting.elements.skip.addEventListener("click", (): void => advanceFocus(sitting, false));
  sitting.elements.timerToggle.addEventListener("click", (): void => toggleFocusTimer(sitting));
}

/** A player that never reports ready is the failure people actually hit: say
 *  so, and name the way out, rather than leaving a blank rectangle. */
function warnIfPlayerNeverWakes(sitting: FocusSitting): void {
  window.setTimeout((): void => {
    if (sitting.ready) return;
    setFocusStatus(
      sitting,
      sitting.player
        ? "the player is not responding — try Reload"
        : "auto-advance is unavailable — Done · next still works",
    );
  }, 8000);
}

/** A fresh sitting on the page, opening on its first item. */
function newFocusSitting(root: HTMLElement, opening: FocusItem): FocusSitting {
  return {
    elements: collectFocusElements(root),
    order: root.dataset["order"] ?? "oldest",
    playlist: root.dataset["playlist"] ?? "",
    postSeconds: parseInt(root.dataset["postSeconds"] ?? "", 10) || 30,
    allowed: parseInt(root.dataset["postSeconds"] ?? "", 10) || 30,
    locked: false,
    current: opening,
    passedOver: [],
    player: null,
    ready: false,
    advancing: false,
    timerId: null,
    msLeft: 0,
    held: false,
    seen: freshFocusSeen(focusPickedId(opening)),
  };
}

/** The item a sitting was opened on by clicking its card — a feed card or a
 *  pamphlet story says `picked=1` — rather than reached in turn or reloaded. */
function focusPickedId(opening: FocusItem): number | null {
  const asked = new URLSearchParams(window.location.search);
  return asked.get("picked") === "1" ? opening.id : null;
}

/** A clean slate for the item just shown. */
function freshFocusSeen(pickedId: number | null): FocusSeen {
  return { shownAt: Date.now(), pauses: 0, reached: 0, duration: 0, playing: false, pickedId };
}

/** Read how far the player got, while it can still be asked. */
function noteFocusPosition(sitting: FocusSitting): void {
  const player = sitting.player;
  if (player === null || focusIsRead(sitting.current)) return;
  try {
    sitting.seen.reached = Math.max(sitting.seen.reached, player.getCurrentTime() || 0);
    sitting.seen.duration = player.getDuration() || sitting.seen.duration;
  } catch {
    // A player not ready yet has nothing to say.
  }
}

/** How the open item went, as form fields. */
function focusSeenFields(sitting: FocusSitting, body: URLSearchParams): void {
  noteFocusPosition(sitting);
  const seen = sitting.seen;
  body.set("seconds", ((Date.now() - seen.shownAt) / 1000).toFixed(1));
  body.set("pauses", String(seen.pauses));
  body.set("clicked", seen.pickedId === sitting.current.id ? "1" : "0");
  if (!focusIsRead(sitting.current)) {
    body.set("reached", seen.reached.toFixed(1));
    body.set("duration", seen.duration.toFixed(1));
  }
}

/** Leaving the page with something open still says how it went. */
function sayFocusSeenOnLeaving(sitting: FocusSitting): void {
  window.addEventListener("pagehide", (): void => {
    if (sitting.elements.root.classList.contains("focus-done")) return;
    const body = new URLSearchParams();
    focusSeenFields(sitting, body);
    navigator.sendBeacon(`/focus/${sitting.current.id}/seen`, body);
  }, { once: true });
}

/** Focus mode's entry point: start a sitting if this is the Focus page and there is a queue. */
function initFocusMode(): void {
  const root = document.getElementById("focus");
  if (!root) return; // every other page

  const opening = readFocusQueue()[0];
  if (!opening) return; // nothing left to go through

  const sitting = newFocusSitting(root, opening);
  bindFocusControls(sitting);
  sayFocusSeenOnLeaving(sitting);
  pointFrameAtFirstVideo(sitting);
  awaitYouTubeApi(sitting);

  if (focusIsRead(sitting.current) && focusIsTimed(sitting.current)) {
    startFocusTimer(sitting, sitting.current);
  } else if (!focusIsRead(sitting.current)) {
    warnIfPlayerNeverWakes(sitting);
  }
}

initFocusMode();
