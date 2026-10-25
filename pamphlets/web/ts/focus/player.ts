// A source plugin's player: its frame, and the messages it is talked to with.
//
// Part of Content view; see main.ts.
//
// Pamphlets has no player of its own, and loads no player's script. A plugin
// declares one as data (plugins/registry/players.py): the frame's address on
// one https origin, the messages to say to it, and which messages heard back
// mean playing, paused, ended or failed. The frame is sandboxed and from
// another origin, so it can reach nothing of this page. Messages go only to
// that origin, and only messages from that frame and that origin are heard;
// what they say is read at the paths the plugin named and compared, never
// drawn or run.

/** A video's key as it may go into a frame's address (players.py KEY). */
function focusKeyIsPlain(key: string): boolean {
  return /^[A-Za-z0-9_.~-]{1,128}$/.test(key) && key !== "." && key !== "..";
}

/** The frame's address for one video, the way players.py fills it in. */
function focusFrameUrl(player: FocusPlayer, key: string, autoplay: boolean): string {
  if (!focusKeyIsPlain(key)) return "";
  return player.frame
    .split("{key}").join(encodeURIComponent(key))
    .split("{autoplay}").join(autoplay ? "1" : "0")
    .split("{origin}").join(encodeURIComponent(window.location.origin));
}

/** One field of what a player said, by its dotted path. */
function focusHeardAt(said: unknown, path: string): unknown {
  let here: unknown = said;
  for (const part of path.split(".")) {
    if (here === null || typeof here !== "object") return undefined;
    here = (here as Record<string, unknown>)[part];
  }
  return here;
}

/** Whether what was heard is any of the ways a state is said. */
function focusHeardAs(said: unknown, ways: FocusMatcher[] | undefined): boolean {
  return (ways ?? []).some((fields): boolean =>
    Object.entries(fields).every(([path, value]): boolean => focusHeardAt(said, path) === value));
}

/** Say one of the plugin's messages to the frame, at its origin only. */
function tellFocusPlayer(sitting: FocusSitting, what: "play" | "pause" | "stop"): void {
  const playing = sitting.playing;
  const frame = sitting.elements.frame;
  const message = playing?.player.say[what];
  if (!playing || !frame || !frame.contentWindow || !message) return;
  frame.contentWindow.postMessage(message, playing.player.origin);
}

/** Say hello until the player answers: some only talk once told someone
 *  is listening, and a frame still loading hears nothing. */
function greetFocusPlayer(sitting: FocusSitting, playing: FocusPlaying): void {
  const frame = sitting.elements.frame;
  if (!frame || playing.player.hello.length === 0) return;
  let tries = 0;
  const greeting = window.setInterval((): void => {
    tries += 1;
    if (sitting.playing !== playing || playing.heard || tries > 40) {
      window.clearInterval(greeting);
      return;
    }
    playing.player.hello.forEach((message): void => {
      frame.contentWindow?.postMessage(message, playing.player.origin);
    });
  }, 250);
}

/** Play one item in its source's player, in the page's one frame. */
function playInFocusFrame(sitting: FocusSitting, item: FocusItem, autoplay: boolean): boolean {
  const frame = sitting.elements.frame;
  const player = sitting.players[item.player];
  if (!frame || !player) return false;
  const src = focusFrameUrl(player, item.video_id, autoplay);
  if (!src) return false;
  const playing: FocusPlaying = { player, itemId: item.id, heard: false, ended: false, time: 0, duration: 0 };
  sitting.playing = playing;
  frame.addEventListener("load", (): void => greetFocusPlayer(sitting, playing), { once: true });
  frame.src = src;
  return true;
}

/** What the player in the frame says, if it is that player saying it. */
function hearFocusPlayer(sitting: FocusSitting, event: MessageEvent): void {
  const playing = sitting.playing;
  const frame = sitting.elements.frame;
  if (!playing || !frame || event.source !== frame.contentWindow || event.origin !== playing.player.origin) return;
  let said: unknown = event.data;
  if (typeof said === "string") {
    // The most of one message that is read at all.
    if (said.length > 65536) return;
    try {
      said = JSON.parse(said) as unknown;
    } catch {
      return;
    }
  }
  if (said === null || typeof said !== "object") return;
  const hears = playing.player.hears;
  if (!playing.heard) {
    playing.heard = true;
    sitting.ready = true;
    setFocusStatus(sitting, "");
    // Opened on something read: the player is there for what comes next,
    // and must stay quiet.
    if (focusIsRead(sitting.current)) tellFocusPlayer(sitting, "pause");
  }
  const time = hears.time ? focusHeardAt(said, hears.time) : undefined;
  if (typeof time === "number" && Number.isFinite(time)) playing.time = time;
  const duration = hears.duration ? focusHeardAt(said, hears.duration) : undefined;
  if (typeof duration === "number" && Number.isFinite(duration) && duration > 0) playing.duration = duration;
  noteFocusPosition(sitting);
  // Stopping and starting again is what engagement is counted from.
  if (focusHeardAs(said, hears.playing)) sitting.seen.playing = true;
  if (focusHeardAs(said, hears.paused) && sitting.seen.playing) {
    sitting.seen.pauses += 1;
    sitting.seen.playing = false;
  }
  if (playing.itemId !== sitting.current.id || focusIsRead(sitting.current) || playing.ended) return;
  if (focusHeardAs(said, hears.ended)) {
    playing.ended = true;
    advanceFocus(sitting, true);
  } else if (focusHeardAs(said, hears.failed)) {
    // Private, deleted or not embeddable: do not strand the queue on it.
    playing.ended = true;
    setFocusStatus(sitting, "this one would not play — skipping");
    advanceFocus(sitting, false);
  }
}

/** Listen to the frame for as long as this sitting's page is the one shown. */
function listenToFocusPlayer(sitting: FocusSitting): void {
  if (!sitting.elements.frame) return;
  const hearing = (event: MessageEvent): void => {
    // htmx swapped another page in: this sitting is over.
    if (!document.body.contains(sitting.elements.root)) {
      window.removeEventListener("message", hearing);
      return;
    }
    hearFocusPlayer(sitting, event);
  };
  window.addEventListener("message", hearing);
}
