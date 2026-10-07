// What Focus mode works with: an item, a sitting, and the page it runs in.
//
// Part of Focus mode; see main.ts.

/** One entry in the queue, as `_focus_item` in web/routes/focus.py builds it. */
interface FocusItem {
  id: number;
  video_id: string;
  kind: "video" | "post" | "link";
  /** Which built-in player plays it, as its source's plugin chose; "" for
   *  anything read rather than played. */
  player: string;
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
