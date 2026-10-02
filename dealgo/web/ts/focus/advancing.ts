// Moving on: saying the item is finished, and showing the next.
//
// Part of Focus mode; see main.ts.

/** Nothing left: stop the timer and the player and say so. */
function finishFocusSitting(sitting: FocusSitting): void {
  stopFocusTimer(sitting);
  paintFocusQueue(sitting, []);
  const elements = sitting.elements;
  elements.root.classList.add("focus-done");
  elements.post.hidden = true;
  elements.timer.hidden = true;
  elements.title.textContent = "All caught up";
  elements.channel.textContent = "Nothing left unwatched";
  elements.remaining.textContent = "0";
  elements.count.textContent = "0";
  setFocusStatus(sitting, "");
  if (sitting.player) sitting.player.stopVideo();
}

/** The form the server is asked for the next item with. */
function focusAdvanceBody(sitting: FocusSitting, markWatched: boolean): string {
  const body = new URLSearchParams();
  body.set("order", sitting.order);
  body.set("playlist", sitting.playlist);
  body.set("watched", markWatched ? "1" : "0");
  body.set("skipped", sitting.passedOver.join(","));
  return body.toString();
}

/** markWatched=false means "skip": it stays unwatched but sits out this
 *  sitting. */
function advanceFocus(sitting: FocusSitting, markWatched: boolean): void {
  if (sitting.advancing) return;
  sitting.advancing = true;
  stopFocusTimer(sitting);
  setFocusStatus(sitting, markWatched ? "marking done…" : "skipping…");

  // A skipped item is remembered, so the server does not offer it again this sitting.
  if (!markWatched && !sitting.passedOver.includes(sitting.current.id)) {
    sitting.passedOver.push(sitting.current.id);
  }

  // The server says what comes next, so a queue left open cannot bring back something already done.
  fetch(`/focus/${sitting.current.id}/finished`, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: focusAdvanceBody(sitting, markWatched),
  })
    .then((response): Promise<FocusAdvance> => {
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      return response.json() as Promise<FocusAdvance>;
    })
    .then((data): void => {
      sitting.advancing = false;
      setFocusStatus(sitting, "");
      if (!data.next) {
        finishFocusSitting(sitting);
        return;
      }
      showFocusItem(sitting, data.next, data.remaining);
      paintFocusQueue(sitting, data.upcoming);
    })
    // Nothing advanced: say so, and give a timed item its time back.
    .catch((): void => {
      sitting.advancing = false;
      setFocusStatus(sitting, "could not advance — check the connection");
      if (focusIsRead(sitting.current) && focusIsTimed(sitting.current)) {
        startFocusTimer(sitting, sitting.current);
      }
    });
}
