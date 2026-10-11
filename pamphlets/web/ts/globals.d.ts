// What the browser hands these scripts that TypeScript does not describe.
//
// Two libraries arrive as plain <script> tags rather than as packages, so
// there are no types to install. Declaring only the members actually used
// keeps the guesswork visible: anything else would need adding here first.

/** htmx, vendored into static/. Only the calls Pamphlets makes are declared. */
interface Htmx {
  ajax(
    method: "GET" | "POST" | "DELETE",
    url: string,
    context: { target: string; swap: string; values?: Record<string, string> },
  ): Promise<void>;
}

/** YouTube's IFrame Player API, loaded from youtube.com at runtime. */
interface YouTubePlayer {
  loadVideoById(videoId: string): void;
  pauseVideo(): void;
  stopVideo(): void;
  /** How far into the video it is, and how long it is, in seconds. */
  getCurrentTime(): number;
  getDuration(): number;
}

/** What the player's events carry: its state. */
interface YouTubePlayerEvent {
  data: number;
}

/** The events Pamphlets listens to on the player. */
interface YouTubePlayerOptions {
  events: {
    onReady?: () => void;
    onStateChange?: (event: YouTubePlayerEvent) => void;
    onError?: () => void;
  };
}

/** The part of YouTube's IFrame API Pamphlets uses. */
interface YouTubeApi {
  Player: new (elementId: string, options: YouTubePlayerOptions) => YouTubePlayer;
  PlayerState: { ENDED: number; PLAYING: number; PAUSED: number };
}

/** One chart Chart.js has drawn: only what Pamphlets does with one. */
interface ChartJsChart {
  destroy(): void;
}

/** Chart.js, vendored into static/vendor/. Configurations are built as plain
 *  objects in charts.ts and handed over whole, so only these are declared. */
interface ChartJs {
  new (canvas: HTMLCanvasElement, config: object): ChartJsChart;
  getChart(canvas: HTMLCanvasElement): ChartJsChart | undefined;
}

/** What the page's scripts find on `window`: htmx, Chart.js, YouTube's API,
 *  and what charts.ts gives the canvas's editor to draw its charts with. */
interface Window {
  htmx?: Htmx;
  Chart?: ChartJs;
  drawCharts?: (root: ParentNode) => void;
  YT?: YouTubeApi;
  /** Called once per document, by the API itself, when it has loaded. */
  onYouTubeIframeAPIReady?: () => void;
}

/** htmx fires these on the body; only the target is ever read. */
interface HtmxSwapEvent extends Event {
  target: EventTarget | null;
}
