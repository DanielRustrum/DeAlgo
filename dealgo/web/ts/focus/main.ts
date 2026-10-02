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
// loads (`make js`, dealgo/web/scripts.py), a plain script that htmx re-runs
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
  };
}

/** Focus mode's entry point: start a sitting if this is the Focus page and there is a queue. */
function initFocusMode(): void {
  const root = document.getElementById("focus");
  if (!root) return; // every other page

  const opening = readFocusQueue()[0];
  if (!opening) return; // nothing left to go through

  const sitting = newFocusSitting(root, opening);
  bindFocusControls(sitting);
  pointFrameAtFirstVideo(sitting);
  awaitYouTubeApi(sitting);

  if (focusIsRead(sitting.current) && focusIsTimed(sitting.current)) {
    startFocusTimer(sitting, sitting.current);
  } else if (!focusIsRead(sitting.current)) {
    warnIfPlayerNeverWakes(sitting);
  }
}

initFocusMode();
