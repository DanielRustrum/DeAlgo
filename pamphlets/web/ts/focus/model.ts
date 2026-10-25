// What Focus mode works with: an item, a sitting, and the page it runs in.
//
// Part of Focus mode; see main.ts.

/** One entry in the queue, as `_focus_item` in web/routes/focus.py builds it. */
interface FocusItem {
  id: number;
  video_id: string;
  kind: "video" | "post" | "link";
  /** Which source's player plays it — a key of the sitting's `players` —
   *  or "" for anything read rather than played. */
  player: string;
  /** What its source is called, for the link out. */
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
  /** Whether its source's plugin lays it out itself, as a view. */
  view: boolean;
}

/** A plugin's view of one item, as the server made it safe to show. */
interface FocusView {
  html: string;
  css: string;
  error: string;
  plugin: string;
}

/** How a player says something, as its plugin declared it: every field, by
 *  dotted path, equal to its value. */
type FocusMatcher = Record<string, string | number | boolean>;

/** A source plugin's player, as players.py checked it. */
interface FocusPlayer {
  /** Its address, with {key}, {autoplay} and {origin} to fill in. */
  frame: string;
  /** The one origin it is talked to at and heard from. */
  origin: string;
  hello: string[];
  say: { play?: string; pause?: string; stop?: string };
  hears: {
    ready?: FocusMatcher[];
    playing?: FocusMatcher[];
    paused?: FocusMatcher[];
    ended?: FocusMatcher[];
    failed?: FocusMatcher[];
    time?: string;
    duration?: string;
  };
}

/** What is in the frame now, and what has been heard from it. */
interface FocusPlaying {
  player: FocusPlayer;
  itemId: number;
  /** It has said something, so it is there to talk to. */
  heard: boolean;
  /** It has ended, or failed, once already: it is not moved on from twice. */
  ended: boolean;
  time: number;
  duration: number;
}

/** What POST /focus/<id>/finished answers with. */
interface FocusAdvance {
  next: FocusItem | null;
  /** The player the next item plays in, if it has one. */
  players: Record<string, FocusPlayer>;
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
  view: HTMLElement;
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
  /** The players its items play in, by source kind. */
  players: Record<string, FocusPlayer>;
  /** What the frame is playing, or null. */
  playing: FocusPlaying | null;
  /** True once anything has proved the page is working. */
  ready: boolean;
  /** One advance at a time, however many things ask for one. */
  advancing: boolean;
  timerId: number | null;
  msLeft: number;
  /** The reader has paused the timer. */
  held: boolean;
  /** How the item open now is going, for the algorithm to learn from:
   *  when it was shown, how often it was paused, how far a video got, and
   *  whether it is the one whose card was clicked to start the sitting. */
  seen: FocusSeen;
}

/** How one item went, while it was open. */
interface FocusSeen {
  shownAt: number;
  pauses: number;
  reached: number;
  duration: number;
  playing: boolean;
  /** The item the sitting was opened on by clicking its card, if any. */
  pickedId: number | null;
}
