// What the browser hands these scripts that TypeScript does not describe.
//
// Two libraries arrive as plain <script> tags rather than as packages, so
// there are no types to install. Declaring only the members actually used
// keeps the guesswork visible: anything else would need adding here first.

/** htmx, vendored into static/. Only the calls De-Algo makes are declared. */
interface Htmx {
  ajax(
    method: "GET" | "POST" | "DELETE",
    url: string,
    context: { target: string; swap: string },
  ): Promise<void>;
}

/** YouTube's IFrame Player API, loaded from youtube.com at runtime. */
interface YouTubePlayer {
  loadVideoById(videoId: string): void;
  pauseVideo(): void;
  stopVideo(): void;
}

/** What the player's events carry: its state. */
interface YouTubePlayerEvent {
  data: number;
}

/** The events De-Algo listens to on the player. */
interface YouTubePlayerOptions {
  events: {
    onReady?: () => void;
    onStateChange?: (event: YouTubePlayerEvent) => void;
    onError?: () => void;
  };
}

/** The part of YouTube's IFrame API De-Algo uses. */
interface YouTubeApi {
  Player: new (elementId: string, options: YouTubePlayerOptions) => YouTubePlayer;
  PlayerState: { ENDED: number };
}

/** What the page's scripts find on `window`: htmx, and YouTube's API. */
interface Window {
  htmx?: Htmx;
  YT?: YouTubeApi;
  /** Called once per document, by the API itself, when it has loaded. */
  onYouTubeIframeAPIReady?: () => void;
}

/** htmx fires these on the body; only the target is ever read. */
interface HtmxSwapEvent extends Event {
  target: EventTarget | null;
}
