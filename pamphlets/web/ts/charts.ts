// Charts: the chart leaflets, drawn by Chart.js in the theme's colours.
//
// The server works a chart out (services/charting.py) and sets it on the page
// as a canvas with its data beside it, as JSON (templates/_chart.html). This
// draws each one: Chart.js, vendored into static/vendor, is only fetched the
// first time a page has a chart on it. Colours, lines and type are read from
// the theme as it is now — the six chart colours (--chart-1…6) for the
// series, the text and line colours for everything around them — so a chart
// is redrawn when the page goes light or dark, or the theme changes.
//
// Loaded on every page, from base.html; htmx swaps pages in without loading
// it again, so charts in swapped-in content are drawn when it settles. The
// canvas's editor draws its own through `drawCharts`.

/** One series of a chart, as the server sends it. A pie's single series
 *  carries a colour for each slice. */
interface ChartSpecSeries {
  name: string;
  slot?: number;
  slots?: number[];
  values: (number | null)[];
}

/** A Scatter or Bubble chart's series: a point a row. */
interface ChartSpecPoints {
  name: string;
  slot: number;
  data: { x: number; y: number; r?: number }[];
}

/** A chart, as the server works it out (Chart.config in charting.py). */
interface ChartSpec {
  type: string;
  style: Record<string, string>;
  labels: string[];
  titles: string[];
  series: ChartSpecSeries[];
  points: ChartSpecPoints[];
  measure: string;
  unit: string;
  xName: string;
  yName: string;
  xDates: boolean;
}

/** What a chart is drawn in, read off the theme as it is now. */
interface ChartTheme {
  colours: string[];
  text: string;
  muted: string;
  line: string;
  panel: string;
  font: string;
  still: boolean;
}

/** The theme's chart colours and inks, as the page has them now. */
function chartTheme(): ChartTheme {
  const look = getComputedStyle(document.documentElement);
  const read = (name: string, fallback: string): string => look.getPropertyValue(name).trim() || fallback;
  const colours: string[] = [];
  for (let slot = 1; slot <= 6; slot += 1) colours.push(read(`--chart-${slot}`, "#c04f2c"));
  return {
    colours,
    text: read("--text", "#22332e"),
    muted: read("--muted", "#606a62"),
    line: read("--line", "#e6d8c4"),
    panel: read("--panel", "#fffaf3"),
    font: getComputedStyle(document.body).fontFamily,
    still: window.matchMedia("(prefers-reduced-motion: reduce)").matches,
  };
}

/** A series' colour: the theme's chart colour in its slot, 1 to 6. */
function chartColour(theme: ChartTheme, slot: number | undefined): string {
  const at = Math.min(6, Math.max(1, slot ?? 1)) - 1;
  return theme.colours[at] ?? theme.colours[0] ?? "#c04f2c";
}

/** A colour seen through: for filled areas, which lines are drawn over. */
function chartSeeThrough(colour: string, alpha: number): string {
  const hex = /^#([0-9a-f]{6})$/i.exec(colour);
  if (hex === null || hex[1] === undefined) return colour;
  const value = parseInt(hex[1], 16);
  return `rgba(${(value >> 16) & 255}, ${(value >> 8) & 255}, ${value & 255}, ${alpha})`;
}

/** A number as a person writes it. */
function chartNumber(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return new Intl.NumberFormat(undefined, { maximumFractionDigits: 2 }).format(value);
}

/** A chart's data, from the JSON set beside its canvas. */
function chartSpec(figure: HTMLElement): ChartSpec | null {
  const said = figure.querySelector<HTMLScriptElement>("script[data-chart-config]")?.textContent ?? "";
  let raw: unknown;
  try {
    raw = JSON.parse(said);
  } catch {
    return null;
  }
  if (typeof raw !== "object" || raw === null) return null;
  const given = raw as Record<string, unknown>;
  const text = (key: string): string => (typeof given[key] === "string" ? given[key] : "");
  const list = (key: string): unknown[] => (Array.isArray(given[key]) ? given[key] : []);
  const style: Record<string, string> = {};
  if (typeof given["style"] === "object" && given["style"] !== null) {
    for (const [key, value] of Object.entries(given["style"])) if (typeof value === "string") style[key] = value;
  }
  return {
    type: text("type"),
    style,
    labels: list("labels").map((one): string => String(one)),
    titles: list("titles").map((one): string => String(one)),
    series: list("series") as ChartSpecSeries[],
    points: list("points") as ChartSpecPoints[],
    measure: text("measure"),
    unit: text("unit"),
    xName: text("xName"),
    yName: text("yName"),
    xDates: given["xDates"] === true,
  };
}

/** A date along the bottom, from the milliseconds it is placed by. */
function chartDate(value: number): string {
  return new Date(value).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "2-digit" });
}

/** The parts every chart shares: its size, motion, legend and tooltip. */
function chartOptions(spec: ChartSpec, theme: ChartTheme, legend: boolean): Record<string, unknown> {
  const font = { family: theme.font, size: 12 };
  const unit = spec.unit !== "" ? ` ${spec.unit}` : "";
  return {
    responsive: true,
    maintainAspectRatio: false,
    animation: theme.still ? false : { duration: 350 },
    plugins: {
      legend: {
        display: legend,
        position: "top",
        align: "start",
        labels: { color: theme.text, font, boxWidth: 10, boxHeight: 10, usePointStyle: true, pointStyle: "rectRounded" },
      },
      tooltip: {
        backgroundColor: theme.panel,
        titleColor: theme.text,
        bodyColor: theme.text,
        borderColor: theme.line,
        borderWidth: 1,
        padding: 8,
        cornerRadius: 6,
        boxPadding: 4,
        titleFont: { ...font, weight: "600" },
        bodyFont: font,
        callbacks: {
          title: (items: { dataIndex: number }[]): string => {
            const at = items[0]?.dataIndex ?? 0;
            return spec.titles[at] ?? spec.labels[at] ?? "";
          },
          label: (item: { dataset: { label?: string }; raw: unknown; parsed: unknown }): string => {
            const name = item.dataset.label ?? "";
            if (spec.type === "scatter" || spec.type === "bubble") {
              const point = item.raw as { x: number; y: number };
              const across = spec.xDates ? chartDate(point.x) : chartNumber(point.x);
              return `${name}: ${spec.xName} ${across}, ${spec.yName} ${chartNumber(point.y)}`;
            }
            const value = typeof item.raw === "number" ? item.raw : null;
            return `${name !== "" ? name + ": " : ""}${chartNumber(value)}${unit}`;
          },
        },
      },
    },
  };
}

/** The axes of a chart drawn on two: quiet lines, readable ticks, one scale. */
function chartAxes(theme: ChartTheme, across: boolean, stacked: boolean): Record<string, unknown> {
  const font = { family: theme.font, size: 11 };
  const ticks = { color: theme.muted, font, maxRotation: 0, autoSkip: true, autoSkipPadding: 12 };
  // The axis the bars stand on keeps no grid; the one they are measured on does.
  const base = { stacked, grid: { display: false }, border: { color: theme.line }, ticks };
  const measured = {
    stacked, beginAtZero: true, grid: { color: theme.line }, border: { display: false },
    ticks: { ...ticks, callback: (value: number | string): string => chartNumber(Number(value)) },
  };
  return across ? { x: measured, y: base } : { x: base, y: measured };
}

/** A radar's or polar area's one round scale. */
function chartRound(theme: ChartTheme): Record<string, unknown> {
  return {
    r: {
      beginAtZero: true,
      angleLines: { color: theme.line },
      grid: { color: theme.line },
      pointLabels: { color: theme.text, font: { family: theme.font, size: 11 } },
      // A few rings marked, not one every step: the shape is what is read.
      ticks: { color: theme.muted, backdropColor: "transparent", font: { family: theme.font, size: 10 }, maxTicksLimit: 4 },
    },
  };
}

/** Everything Chart.js is told to draw one chart. */
function chartConfig(spec: ChartSpec, theme: ChartTheme, wide: boolean): object | null {
  const many = spec.series.length > 1;
  const style = spec.style;

  if (spec.type === "bar") {
    const across = style["direction"] === "horizontal";
    const stacked = style["stacking"] === "stacked";
    return {
      type: "bar",
      data: {
        labels: spec.labels,
        datasets: spec.series.map((one) => ({
          label: one.name,
          data: one.values,
          backgroundColor: chartColour(theme, one.slot),
          borderRadius: 4,
          borderSkipped: "start",
          maxBarThickness: 36,
          categoryPercentage: 0.8,
          barPercentage: 0.9,
        })),
      },
      options: { ...chartOptions(spec, theme, many), indexAxis: across ? "y" : "x", scales: chartAxes(theme, across, stacked) },
    };
  }

  if (spec.type === "line") {
    const area = style["fill"] === "area";
    const stacked = style["stacking"] === "stacked";
    return {
      type: "line",
      data: {
        labels: spec.labels,
        datasets: spec.series.map((one, index) => {
          const colour = chartColour(theme, one.slot);
          return {
            label: one.name,
            data: one.values,
            borderColor: colour,
            backgroundColor: area ? chartSeeThrough(colour, 0.35) : colour,
            fill: area ? (stacked && index > 0 ? "-1" : "origin") : false,
            tension: style["curve"] === "smooth" ? 0.35 : 0,
            borderWidth: 2,
            pointRadius: spec.labels.length <= 24 ? 3 : 0,
            pointHoverRadius: 5,
            pointBackgroundColor: colour,
            spanGaps: false,
          };
        }),
      },
      options: {
        ...chartOptions(spec, theme, many),
        interaction: { mode: "index", intersect: false },
        scales: chartAxes(theme, false, stacked),
      },
    };
  }

  if (spec.type === "pie" || spec.type === "polar") {
    const only = spec.series[0];
    if (only === undefined) return null;
    const colours = (only.slots ?? []).map((slot): string => chartColour(theme, slot));
    const total = only.values.reduce((sum: number, one): number => sum + (one ?? 0), 0);
    const options = chartOptions(spec, theme, true);
    const plugins = options["plugins"] as Record<string, Record<string, unknown>>;
    // Beside the pie when there is room for both; above it in a narrow column.
    if (plugins["legend"] !== undefined) plugins["legend"]["position"] = wide ? "right" : "top";
    if (plugins["tooltip"] !== undefined) {
      plugins["tooltip"]["callbacks"] = {
        label: (item: { label: string; raw: unknown }): string => {
          const value = typeof item.raw === "number" ? item.raw : 0;
          const share = total > 0 ? Math.round((1000 * value) / total) / 10 : 0;
          return `${item.label}: ${chartNumber(value)} (${share}%)`;
        },
      };
    }
    return {
      type: spec.type === "polar" ? "polarArea" : style["shape"] === "doughnut" ? "doughnut" : "pie",
      data: {
        labels: spec.labels,
        datasets: [{
          label: only.name,
          data: only.values,
          backgroundColor: spec.type === "polar" ? colours.map((one): string => chartSeeThrough(one, 0.8)) : colours,
          borderColor: theme.panel,
          borderWidth: 2,
          hoverOffset: 6,
        }],
      },
      options: spec.type === "polar" ? { ...options, scales: chartRound(theme) } : options,
    };
  }

  if (spec.type === "radar") {
    const filled = style["fill"] !== "none";
    return {
      type: "radar",
      data: {
        labels: spec.labels,
        datasets: spec.series.map((one) => {
          const colour = chartColour(theme, one.slot);
          return {
            label: one.name,
            data: one.values,
            borderColor: colour,
            backgroundColor: filled ? chartSeeThrough(colour, 0.25) : "transparent",
            fill: filled,
            borderWidth: 2,
            pointRadius: 3,
            pointBackgroundColor: colour,
          };
        }),
      },
      options: { ...chartOptions(spec, theme, many), scales: chartRound(theme) },
    };
  }

  if (spec.type === "scatter" || spec.type === "bubble") {
    const font = { family: theme.font, size: 11 };
    const named = (text: string): Record<string, unknown> => ({ display: text !== "", text, color: theme.muted, font });
    const ticks = { color: theme.muted, font };
    return {
      type: spec.type,
      data: {
        datasets: spec.points.map((one) => {
          const colour = chartColour(theme, one.slot);
          return {
            label: one.name,
            data: one.data,
            backgroundColor: chartSeeThrough(colour, spec.type === "bubble" ? 0.55 : 0.8),
            borderColor: colour,
            borderWidth: 1,
            pointRadius: 4,
            pointHoverRadius: 6,
          };
        }),
      },
      options: {
        ...chartOptions(spec, theme, spec.points.length > 1),
        scales: {
          x: {
            type: "linear", title: named(spec.xName), grid: { color: theme.line }, border: { color: theme.line },
            ticks: { ...ticks, callback: (value: number | string): string =>
              spec.xDates ? chartDate(Number(value)) : chartNumber(Number(value)) },
          },
          y: {
            type: "linear", title: named(spec.yName), grid: { color: theme.line }, border: { display: false },
            ticks: { ...ticks, callback: (value: number | string): string => chartNumber(Number(value)) },
          },
        },
      },
    };
  }
  return null;
}

/** Draw one chart afresh: what was drawn there before is put away first. */
function drawChart(figure: HTMLElement, theme: ChartTheme): void {
  const library = window.Chart;
  const canvas = figure.querySelector<HTMLCanvasElement>("canvas");
  const spec = chartSpec(figure);
  if (library === undefined || canvas === null || spec === null) return;
  library.getChart(canvas)?.destroy();
  const config = chartConfig(spec, theme, figure.clientWidth >= 440);
  if (config === null) return;
  new library(canvas, config);
  figure.dataset["drawn"] = "1";
}

/** Draw every chart in part of the page, fetching Chart.js first if this is
 *  the first chart there has been. `again` redraws ones already drawn. */
function drawCharts(root: ParentNode, again = false): void {
  const figures = Array.from(root.querySelectorAll<HTMLElement>("[data-chart]"))
    .filter((one): boolean => again || one.dataset["drawn"] !== "1");
  if (figures.length === 0) return;
  if (window.Chart === undefined) {
    fetchChartJs((): void => drawCharts(root, again));
    return;
  }
  const theme = chartTheme();
  for (const figure of figures) drawChart(figure, theme);
}

/** Fetch Chart.js once, then carry on. Its address — with the version that
 *  keeps a cached copy current — is on this script's own tag. */
function fetchChartJs(then: () => void): void {
  const asked = document.querySelector<HTMLScriptElement>("script[data-chartjs-loading]");
  if (asked !== null) {
    asked.addEventListener("load", then, { once: true });
    return;
  }
  const address = document.querySelector<HTMLScriptElement>("script[data-chartjs]")?.dataset["chartjs"];
  if (address === undefined || address === "") return;
  const script = document.createElement("script");
  script.src = address;
  script.dataset["chartjsLoading"] = "1";
  script.addEventListener("load", then, { once: true });
  document.head.appendChild(script);
}

/** Draw the page's charts, and again whenever the page or its theme changes:
 *  content swapped in by htmx, a move between light and dark, a new theme. */
function initCharts(): void {
  // `drawCharts`, a function at the top of a plain script, is already
  // window.drawCharts: the canvas's editor calls it from there.
  drawCharts(document);
  // Listened for once: this script is loaded once per page, but say so.
  const root = document.documentElement;
  if (root.dataset["chartsListen"] === "1") return;
  root.dataset["chartsListen"] = "1";
  document.body.addEventListener("htmx:afterSettle", (event: Event): void => {
    drawCharts(event.target instanceof Element ? event.target : document);
  });
  window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", (): void => {
    drawCharts(document, true);
  });
  // Theming sets data-mode, and its colours in a style element, on the fly.
  new MutationObserver((): void => drawCharts(document, true)).observe(root, {
    attributes: true, attributeFilter: ["data-mode", "style", "class"],
  });
}

initCharts();
