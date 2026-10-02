// The reading timer: how long you get with one item.
//
// Part of Focus mode; see main.ts.

function paintFocusTimer(sitting: FocusSitting): void {
  const seconds = Math.max(0, Math.ceil(sitting.msLeft / 1000));
  sitting.elements.timerCount.textContent = sitting.held ? "held" : `${seconds}s`;
  const share = (sitting.msLeft / (sitting.allowed * 1000)) * 100;
  sitting.elements.timerFill.style.width = `${share}%`;
}

function stopFocusTimer(sitting: FocusSitting): void {
  if (sitting.timerId !== null) window.clearInterval(sitting.timerId);
  sitting.timerId = null;
}

function startFocusTimer(sitting: FocusSitting, item?: FocusItem): void {
  stopFocusTimer(sitting);
  sitting.held = false;
  // What a Decay box gave you with this one, if anything did. The account's
  // own setting is what everything else gets.
  sitting.allowed = item?.seconds ?? sitting.postSeconds;
  sitting.locked = item?.locked === true;
  sitting.msLeft = sitting.allowed * 1000;
  sitting.elements.timerWord.textContent = sitting.locked
    ? "until the next one — cannot be paused"
    : "until the next one";
  paintFocusTimer(sitting);
  sitting.timerId = window.setInterval((): void => tickFocusTimer(sitting), 100);
}

function tickFocusTimer(sitting: FocusSitting): void {
  if (sitting.held) return;
  sitting.msLeft -= 100;
  paintFocusTimer(sitting);
  if (sitting.msLeft > 0) return;
  stopFocusTimer(sitting);
  advanceFocus(sitting, true);
}

/** Hold the timer where it is, for a post still being read.
 *
 *  Unless a Lock piece said otherwise. The point of a locked stretch is one
 *  that runs whether you are looking or not, so it refuses rather than
 *  quietly doing nothing. */
function toggleFocusTimer(sitting: FocusSitting): void {
  if (sitting.locked) {
    setFocusStatus(sitting, "this one cannot be paused");
    return;
  }
  sitting.held = !sitting.held;
  sitting.elements.timerWord.textContent = sitting.held
    ? "paused — click to resume"
    : "until the next one";
  paintFocusTimer(sitting);
}
