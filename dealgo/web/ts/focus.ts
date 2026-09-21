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
// Structure: top-level `function` declarations, and one call at the bottom.
// This file is a plain script that htmx re-runs each time it swaps the Focus
// page in, and a top-level `const` or `class` would throw "already declared"
// on the second visit. Everything a sitting needs to remember therefore lives
// in one FocusSitting object, passed explicitly rather than captured.

/** One entry in the queue, as `_focus_item` in web/app.py builds it. */
interface FocusItem {
  id: number;
  video_id: string;
  kind: "video" | "post" | "link";
  /** What its source is called — "YouTube", "Reddit" — for the link out. */
  source: string;
  title: string;
  channel: string;
  playlist: string;
  duration: string;
  thumbnail: string | null;
  body: string;
  images: string[];
  url: string;
  /** What a Decay box gave you with this one, in seconds. Null for the
   *  account's own setting, which is what most things use. */
  seconds: number | null;
  /** Whether a Lock under that box said the time cannot be held. */
  locked: boolean;
}

/** What POST /focus/<id>/finished answers with. */
interface FocusAdvance {
  next: FocusItem | null;
  remaining: number;
  upcoming: FocusItem[];
}

/** The parts of the page a sitting reads and writes. */
interface FocusElements {
  root: HTMLElement;
  stage: HTMLElement;
  post: HTMLElement;
  tiles: HTMLElement;
  words: HTMLElement;
  postUrl: HTMLAnchorElement;
  timer: HTMLElement;
  timerCount: HTMLElement;
  timerWord: HTMLElement;
  timerFill: HTMLElement;
  timerToggle: HTMLButtonElement;
  title: HTMLElement;
  channel: HTMLElement;
  remaining: HTMLElement;
  status: HTMLElement;
  list: HTMLElement;
  count: HTMLElement;
  reload: HTMLAnchorElement;
  next: HTMLButtonElement;
  skip: HTMLButtonElement;
  /** Absent when the queue holds nothing but posts: nothing to play. */
  frame: HTMLIFrameElement | null;
}

/** Everything one sitting remembers. */
interface FocusSitting {
  readonly elements: FocusElements;
  readonly order: string;
  readonly playlist: string;
  readonly postSeconds: number;
  /** What this item gets, which is the account's setting unless a Decay box
   *  on its way here said otherwise. */
  allowed: number;
  /** Whether that time may be held. */
  locked: boolean;
  /** What is open right now. */
  current: FocusItem;
  /** Skipped this sitting: still unwatched, but not offered again until the
   *  next one. The server needs telling, since it rebuilds the queue. */
  passedOver: number[];
  player: YouTubePlayer | null;
  /** True once anything has proved the page is working. */
  ready: boolean;
  /** One advance at a time, however many things ask for one. */
  advancing: boolean;
  timerId: number | null;
  msLeft: number;
  /** The reader has paused the timer. */
  held: boolean;
}

// -- finding the page ------------------------------------------------------

/** An element the template always renders. Missing means the template
 *  changed, which is worth saying by name rather than half-wiring the page. */
function focusElement<T extends HTMLElement>(id: string): T {
  const found = document.getElementById(id);
  if (!found) throw new Error(`Focus mode: #${id} is missing from the page`);
  return found as T;
}

/** An element that is legitimately absent sometimes. */
function optionalFocusElement<T extends HTMLElement>(id: string): T | null {
  return document.getElementById(id) as T | null;
}

function collectFocusElements(root: HTMLElement): FocusElements {
  return {
    root,
    stage: focusElement("focus-stage"),
    post: focusElement("focus-post"),
    tiles: focusElement("focus-tiles"),
    words: focusElement("focus-words"),
    postUrl: focusElement<HTMLAnchorElement>("focus-post-url"),
    timer: focusElement("focus-timer"),
    timerCount: focusElement("focus-timer-count"),
    timerWord: focusElement("focus-timer-word"),
    timerFill: focusElement("focus-timer-fill"),
    timerToggle: focusElement<HTMLButtonElement>("focus-timer-toggle"),
    title: focusElement("focus-title"),
    channel: focusElement("focus-channel"),
    remaining: focusElement("focus-remaining"),
    status: focusElement("focus-status"),
    list: focusElement("focus-list"),
    count: focusElement("focus-count"),
    reload: focusElement<HTMLAnchorElement>("focus-reload"),
    next: focusElement<HTMLButtonElement>("focus-next"),
    skip: focusElement<HTMLButtonElement>("focus-skip"),
    frame: optionalFocusElement<HTMLIFrameElement>("focus-player"),
  };
}

/** The queue the server rendered into the page, or null if there is none. */
function readFocusQueue(): FocusItem[] {
  const script = document.getElementById("focus-queue");
  if (!script) return [];
  return JSON.parse(script.textContent ?? "[]") as FocusItem[];
}

// -- the status line -------------------------------------------------------

function setFocusStatus(sitting: FocusSitting, message: string): void {
  sitting.elements.status.textContent = message ? ` · ${message}` : "";
}

// -- the reading timer -----------------------------------------------------

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

// -- showing one item ------------------------------------------------------

function focusEmbedUrl(videoId: string): string {
  const origin = encodeURIComponent(window.location.origin);
  return `https://www.youtube-nocookie.com/embed/${videoId}?enablejsapi=1&autoplay=1&rel=0&origin=${origin}`;
}

function buildFocusTile(url: string): HTMLAnchorElement {
  const link = document.createElement("a");
  link.className = "focus-tile";
  link.href = url;
  link.target = "_blank";
  link.rel = "noopener";

  const image = document.createElement("img");
  image.src = url;
  image.alt = "";
  image.loading = "lazy";
  image.referrerPolicy = "no-referrer";
  link.appendChild(image);
  return link;
}

/** Whether this is read rather than played. Asked as "not a video" so a kind
 *  added later is read by default, which is the safe way round: the worst case
 *  is a reading timer on something, not an empty player nobody can advance. */
function focusIsRead(item: FocusItem): boolean {
  return item.kind !== "video";
}

function showFocusPost(sitting: FocusSitting, item: FocusItem): void {
  const elements = sitting.elements;
  elements.tiles.textContent = "";
  item.images.forEach((url): void => {
    elements.tiles.appendChild(buildFocusTile(url));
  });
  elements.words.textContent = item.body;
  elements.postUrl.href = item.url;
  elements.postUrl.textContent = `Open it on ${item.source} ↗`;
  elements.post.hidden = false;
  elements.timer.hidden = false;
  elements.stage.hidden = true;
  if (sitting.player) sitting.player.pauseVideo();
  startFocusTimer(sitting, item);
}

function showFocusVideo(sitting: FocusSitting, item: FocusItem): void {
  stopFocusTimer(sitting);
  const elements = sitting.elements;
  elements.post.hidden = true;
  elements.timer.hidden = true;
  elements.stage.hidden = false;

  if (sitting.player) {
    sitting.player.loadVideoById(item.video_id);
    return;
  }
  // No API attached — reload the iframe itself. Advancing must work even when
  // YouTube's script never arrives, or the queue is stuck on whatever happens
  // to be on screen.
  if (elements.frame) elements.frame.src = focusEmbedUrl(item.video_id);
}

function showFocusItem(sitting: FocusSitting, item: FocusItem, remaining: number): void {
  const elements = sitting.elements;
  sitting.current = item;
  sitting.ready = true; // whatever it is, the page got us this far

  // Reloading has to come back to the item actually open, not the one the page
  // was opened on.
  const order = encodeURIComponent(sitting.order);
  const playlist = encodeURIComponent(sitting.playlist);
  elements.reload.href = `/focus?start=${item.id}&order=${order}&playlist=${playlist}`;

  elements.title.textContent = item.title;
  elements.channel.textContent = item.channel;
  elements.remaining.textContent = String(remaining);
  elements.count.textContent = String(Math.max(0, remaining - 1));

  if (focusIsRead(item)) showFocusPost(sitting, item);
  else showFocusVideo(sitting, item);
}

// -- the up-next list ------------------------------------------------------

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

// -- advancing -------------------------------------------------------------

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

  if (!markWatched && !sitting.passedOver.includes(sitting.current.id)) {
    sitting.passedOver.push(sitting.current.id);
  }

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
    .catch((): void => {
      sitting.advancing = false;
      setFocusStatus(sitting, "could not advance — check the connection");
      if (focusIsRead(sitting.current)) startFocusTimer(sitting, sitting.current);
    });
}

// -- the YouTube player ----------------------------------------------------

function buildFocusPlayer(sitting: FocusSitting): void {
  const api = window.YT;
  if (sitting.player || !sitting.elements.frame || !api || !api.Player) return;

  // Attaching to the existing iframe keeps our allow list. Letting the API
  // build its own would re-add the pop-out button over fullscreen.
  sitting.player = new api.Player("focus-player", {
    events: {
      onReady: (): void => {
        sitting.ready = true;
        setFocusStatus(sitting, "");
        // Opened on a post: the player is loaded but must stay quiet.
        if (focusIsRead(sitting.current) && sitting.player) sitting.player.pauseVideo();
      },
      onStateChange: (event: YouTubePlayerEvent): void => {
        if (event.data === api.PlayerState.ENDED && sitting.current.kind === "video") {
          advanceFocus(sitting, true);
        }
      },
      onError: (): void => {
        // Private, deleted or not embeddable: do not strand the queue on it.
        if (sitting.current.kind !== "video") return;
        setFocusStatus(sitting, "this one would not play — skipping");
        advanceFocus(sitting, false);
      },
    },
  });
}

// Getting hold of the API is the fiddly part, because this page is usually
// reached through an hx-boost swap rather than a page load:
//
//   * a script htmx inserts does not honour `defer`, so load order is not
//     guaranteed and the API can run before the callback below exists;
//   * YT calls onYouTubeIframeAPIReady exactly once per document, so on a
//     second visit within the same document it never fires at all.
//
// Either way the player would stay null, the queue would stop advancing, and
// the video on screen would simply keep playing. So: take the API if it is
// already here, ask to be told if it is not, and poll as well, since neither
// signal is reliable on its own.
function awaitYouTubeApi(sitting: FocusSitting): void {
  if (!sitting.elements.frame) return;

  let waited = 0;
  const waiting = window.setInterval((): void => {
    buildFocusPlayer(sitting);
    waited += 200;
    if (sitting.player || waited > 15000) window.clearInterval(waiting);
  }, 200);

  const earlier = window.onYouTubeIframeAPIReady;
  window.onYouTubeIframeAPIReady = (): void => {
    if (typeof earlier === "function") earlier();
    buildFocusPlayer(sitting);
  };

  // Load the API ourselves, after the callback exists. Adding it twice is
  // harmless: the browser reuses the script it already has.
  if (!window.YT) {
    const script = document.createElement("script");
    script.src = "https://www.youtube.com/iframe_api";
    document.head.appendChild(script);
  }
  buildFocusPlayer(sitting);
}

// -- starting up -----------------------------------------------------------

function pointFrameAtFirstVideo(sitting: FocusSitting): void {
  const frame = sitting.elements.frame;
  if (!frame) return;
  // The origin has to be the host actually browsed to, not whatever
  // DEALGO_PUBLIC_URL happens to say.
  const source = frame.dataset["src"] ?? "";
  frame.src = `${source}&origin=${encodeURIComponent(window.location.origin)}`;
}

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

function initFocusMode(): void {
  const root = document.getElementById("focus");
  if (!root) return; // every other page

  const opening = readFocusQueue()[0];
  if (!opening) return; // nothing left to go through

  const sitting = newFocusSitting(root, opening);
  bindFocusControls(sitting);
  pointFrameAtFirstVideo(sitting);
  awaitYouTubeApi(sitting);

  if (focusIsRead(sitting.current)) startFocusTimer(sitting, sitting.current);
  else warnIfPlayerNeverWakes(sitting);
}

initFocusMode();
