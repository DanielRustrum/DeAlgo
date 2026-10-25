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

/** One map Leaflet has drawn: only what maps.ts does with one. */
interface LeafletMap {
  remove(): void;
  setView(at: [number, number], zoom: number): LeafletMap;
  fitBounds(bounds: [number, number][], options: object): LeafletMap;
  on(event: string, handler: () => void): LeafletMap;
  scrollWheelZoom: { enable(): void };
  attributionControl: { setPrefix(prefix: string | false): void };
}

/** A tile layer or a dot, once made. */
interface LeafletLayer {
  addTo(map: LeafletMap): LeafletLayer;
  bindPopup(content: HTMLElement): LeafletLayer;
}

/** Leaflet, the map library, vendored into static/vendor/. Only what is used. */
interface LeafletLibrary {
  map(element: HTMLElement, options: object): LeafletMap;
  tileLayer(address: string, options: object): LeafletLayer;
  circleMarker(at: [number, number], options: object): LeafletLayer;
}

/** What the page's scripts find on `window`: htmx, Chart.js, Leaflet,
 *  and what charts.ts and maps.ts give the canvas's editor
 *  to draw with. */
interface Window {
  htmx?: Htmx;
  Chart?: ChartJs;
  L?: LeafletLibrary;
  drawCharts?: (root: ParentNode) => void;
  drawMaps?: (root: ParentNode) => void;
}

/** htmx fires these on the body; only the target is ever read. */
interface HtmxSwapEvent extends Event {
  target: EventTarget | null;
}
