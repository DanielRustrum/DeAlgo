// Settings → Theming: the preview follows the form before anything is saved.
//
// The form works without this — it posts, the server checks every value and
// the page comes back in the new look. What this adds is seeing a change as
// it is made: every variable the form sets is copied onto the preview, which
// is a small page of the app's own parts scoped by `.theme-scope`, and the
// contrast of each pairing the app paints is rechecked as you go.
//
// It sets custom properties on one element and nothing else: values come from
// colour pickers, sliders and fixed options, and the server checks them again.
//
// Structure: top-level `function` declarations and one call at the bottom.
// This is a plain script that htmx re-runs on every boosted navigation, and a
// top-level `const` or `class` would throw "already declared" the second time.

interface ThemingColour {
  name: string;
  light: string;
  dark: string;
  follows: string | null;
}

interface ThemingDial {
  name: string;
  unit: string;
  show: string;
  default: number;
}

interface ThemingPair {
  ink: string;
  ground: string;
  minimum: number;
  where: string;
}

interface ThemingData {
  colours: ThemingColour[];
  dials: ThemingDial[];
  fonts: Record<string, string>;
  pairs: ThemingPair[];
  shadow: Record<string, number[]>;
  choices: string[];
}

type ThemingMode = "light" | "dark";

/** What the page says it can change: names, defaults, typefaces, pairings. */
function themingData(): ThemingData | null {
  const node = document.getElementById("theming-data");
  if (!node || !node.textContent) return null;
  try {
    return JSON.parse(node.textContent) as ThemingData;
  } catch {
    return null;
  }
}

function themingInput(form: HTMLFormElement, name: string): HTMLInputElement | null {
  const found = form.elements.namedItem(name);
  return found instanceof HTMLInputElement ? found : null;
}

function themingSelect(form: HTMLFormElement, name: string): HTMLSelectElement | null {
  const found = form.elements.namedItem(name);
  return found instanceof HTMLSelectElement ? found : null;
}

/** What a choice is set to: a list's value, or the ticked radio's. */
function themingChoice(form: HTMLFormElement, name: string): string | null {
  const select = themingSelect(form, name);
  if (select) return select.value;
  const ticked = form.querySelector<HTMLInputElement>(`input[name="${name}"]:checked`);
  return ticked ? ticked.value : null;
}

/** Whether a colour that follows another is, in one mode, still following it. */
function themingFollowing(form: HTMLFormElement, mode: ThemingMode, name: string): boolean {
  const box = themingInput(form, `follow.${mode}.${name}`);
  return box !== null && box.checked;
}

/** Every colour in one mode as the form has it now, following where it follows. */
function themingResolve(data: ThemingData, form: HTMLFormElement, mode: ThemingMode): Map<string, string> {
  const byName = new Map(data.colours.map((colour) => [colour.name, colour]));
  const out = new Map<string, string>();
  function value(name: string, depth: number): string {
    const known = out.get(name);
    if (known) return known;
    const colour = byName.get(name);
    if (!colour) return "#000000";
    let result: string;
    if (colour.follows && depth < 8 && themingFollowing(form, mode, name)) {
      result = value(colour.follows, depth + 1);
    } else {
      const input = themingInput(form, `${mode}.${name}`);
      result = input ? input.value : mode === "dark" ? colour.dark : colour.light;
    }
    out.set(name, result);
    return result;
  }
  for (const colour of data.colours) value(colour.name, 0);
  return out;
}

function themingDialValue(form: HTMLFormElement, dial: ThemingDial): number {
  const input = themingInput(form, dial.name);
  const parsed = input ? parseFloat(input.value) : NaN;
  return Number.isFinite(parsed) ? parsed : dial.default;
}

/** A dial's value the way its slider reads it: 110%, 1.55, 600, 3px, 180°. */
function themingShown(value: number, show: string, unit: string): string {
  if (show === "%") return `${Math.round(value * 100)}%`;
  if (show === "x") return value.toFixed(2);
  if (show === "px") return `${value}px`;
  if (show === "deg") return `${value}°`;
  if (show === "unit") return `${value}${unit}`;
  return String(value);
}

function themingPreview(): HTMLElement | null {
  return document.getElementById("theme-preview");
}

function themingPreviewMode(): ThemingMode {
  return themingPreview()?.dataset["mode"] === "dark" ? "dark" : "light";
}

/** The modes the chosen setting can show: both, unless it is always one. */
function themingModesShown(form: HTMLFormElement): ThemingMode[] {
  const chosen = form.querySelector<HTMLInputElement>('input[name="mode"]:checked');
  if (chosen?.value === "light") return ["light"];
  if (chosen?.value === "dark") return ["dark"];
  return ["light", "dark"];
}

function themingLuminance(hex: string): number {
  const channels = [1, 3, 5].map((at) => parseInt(hex.slice(at, at + 2), 16) / 255);
  const linear = channels.map((c) => (c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4)));
  return 0.2126 * (linear[0] ?? 0) + 0.7152 * (linear[1] ?? 0) + 0.0722 * (linear[2] ?? 0);
}

function themingRatio(one: string, other: string): number {
  const a = themingLuminance(one);
  const b = themingLuminance(other);
  return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
}

/** Rewrite the list of pairings that read below their minimum. */
function themingReport(data: ThemingData, form: HTMLFormElement): void {
  const report = document.getElementById("contrast-report");
  if (!report) return;
  const lines: string[] = [];
  for (const mode of themingModesShown(form)) {
    const colours = themingResolve(data, form, mode);
    const seen = new Set<string>();
    for (const pair of data.pairs) {
      const key = `${pair.ink}/${pair.ground}`;
      if (seen.has(key)) continue;
      seen.add(key);
      const ratio = themingRatio(colours.get(pair.ink) ?? "#000000", colours.get(pair.ground) ?? "#ffffff");
      if (Math.round(ratio * 100) / 100 < pair.minimum) {
        lines.push(`${pair.where} (${mode}): ${ratio.toFixed(1)}:1, needs ${pair.minimum}:1`);
      }
    }
  }
  report.replaceChildren();
  const title = document.createElement("p");
  title.className = "contrast-title";
  if (lines.length === 0) {
    title.classList.add("contrast-ok");
    title.textContent = "Everything reads at the recommended contrast.";
    report.append(title);
    return;
  }
  const strong = document.createElement("strong");
  strong.textContent = "Hard to read";
  title.append(strong);
  const list = document.createElement("ul");
  for (const line of lines) {
    const item = document.createElement("li");
    item.textContent = line;
    list.append(item);
  }
  report.append(title, list);
}

/** Copy the form onto the preview, and keep the controls' own state honest. */
function themingApply(data: ThemingData, form: HTMLFormElement): void {
  const preview = themingPreview();
  const mode = themingPreviewMode();

  for (const which of ["light", "dark"] as ThemingMode[]) {
    const colours = themingResolve(data, form, which);
    for (const colour of data.colours) {
      const input = themingInput(form, `${which}.${colour.name}`);
      if (!input) continue;
      const following = colour.follows !== null && themingFollowing(form, which, colour.name);
      // A colour that follows another shows that one's value, greyed.
      input.disabled = following;
      if (following) input.value = colours.get(colour.name) ?? input.value;
      const reset = form.querySelector<HTMLButtonElement>(
        `[data-reset="${colour.name}"][data-mode="${which}"]`,
      );
      if (reset) reset.hidden = following || input.value.toLowerCase() === input.dataset["default"];
    }
    if (preview && which === mode) {
      for (const [name, value] of colours) preview.style.setProperty(`--${name}`, value);
    }
  }

  for (const dial of data.dials) {
    const value = themingDialValue(form, dial);
    const output = form.querySelector<HTMLOutputElement>(`output[for="dial-${dial.name}"]`);
    if (output) output.textContent = themingShown(value, dial.show, dial.unit);
    if (!preview) continue;
    if (dial.name === "depth") {
      const [r, g, b, alpha] = data.shadow[mode] ?? [0, 0, 0, 0.2];
      preview.style.setProperty("--shadow", `rgba(${r}, ${g}, ${b}, ${Math.min((alpha ?? 0.2) * value, 0.9)})`);
    } else {
      preview.style.setProperty(`--${dial.name}`, `${value}${dial.unit}`);
    }
  }

  for (const name of ["font-body", "font-display"]) {
    const select = themingSelect(form, name);
    const stack = select ? data.fonts[select.value] : undefined;
    if (preview && stack) preview.style.setProperty(`--${name}`, stack);
  }

  // The choices the stylesheet acts on, set on the preview as the page sets
  // them on its root: the background, the pattern, which plants and where.
  for (const name of data.choices) {
    const value = themingChoice(form, name);
    if (preview && value !== null) preview.setAttribute(`data-${name}`, value);
  }

  if (preview) preview.dataset["mode"] = mode;
  themingReport(data, form);
}

function themingSetPreviewMode(data: ThemingData, form: HTMLFormElement, mode: ThemingMode): void {
  const preview = themingPreview();
  if (preview) preview.dataset["mode"] = mode;
  document.querySelectorAll<HTMLButtonElement>("[data-preview-mode]").forEach((button) => {
    button.setAttribute("aria-pressed", String(button.dataset["previewMode"] === mode));
  });
  themingApply(data, form);
}

/** Show one mode's colours, and point the preview at it. */
function themingShowColours(data: ThemingData, form: HTMLFormElement, mode: ThemingMode): void {
  form.querySelectorAll<HTMLFieldSetElement>("[data-colour-mode]").forEach((set) => {
    set.hidden = set.dataset["colourMode"] !== mode;
  });
  form.querySelectorAll<HTMLButtonElement>("[data-colour-tab]").forEach((tab) => {
    tab.setAttribute("aria-selected", String(tab.dataset["colourTab"] === mode));
  });
  themingSetPreviewMode(data, form, mode);
}

function initTheming(): void {
  const form = document.getElementById("theme-form");
  if (!(form instanceof HTMLFormElement) || form.dataset["themingReady"]) return;
  const data = themingData();
  if (!data) return;
  form.dataset["themingReady"] = "1";

  const unsaved = document.getElementById("theming-unsaved");
  function changed(): void {
    if (unsaved) unsaved.hidden = false;
    themingApply(data as ThemingData, form as HTMLFormElement);
  }
  form.addEventListener("input", changed);
  form.addEventListener("change", changed);

  form.addEventListener("click", (event) => {
    const target = event.target instanceof Element ? event.target : null;
    const reset = target?.closest<HTMLButtonElement>("[data-reset]");
    if (reset) {
      const mode = reset.dataset["mode"] ?? "light";
      const input = themingInput(form, `${mode}.${reset.dataset["reset"] ?? ""}`);
      if (input && input.dataset["default"]) input.value = input.dataset["default"];
      changed();
      return;
    }
    const tab = target?.closest<HTMLButtonElement>("[data-colour-tab]");
    if (tab) themingShowColours(data, form, tab.dataset["colourTab"] === "dark" ? "dark" : "light");
  });

  document.querySelectorAll<HTMLElement>(".colour-tabs, [data-preview-tabs]").forEach((tabs) => {
    tabs.hidden = false;
  });
  document.getElementById("colours")?.classList.add("theming-tabbed");
  document.querySelectorAll<HTMLButtonElement>("[data-preview-mode]").forEach((button) => {
    button.addEventListener("click", () => {
      themingSetPreviewMode(data, form, button.dataset["previewMode"] === "dark" ? "dark" : "light");
    });
  });

  // Start on whichever the page is showing now.
  const shown = themingModesShown(form);
  const night = shown.length === 1 ? shown[0] === "dark" : window.matchMedia("(prefers-color-scheme: dark)").matches;
  themingShowColours(data, form, night ? "dark" : "light");
  if (unsaved) unsaved.hidden = true;
}

initTheming();
