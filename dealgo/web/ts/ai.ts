// Settings → AI model: the model field's hint follows the kind chosen, and
// "Ask it" asks the saved model for a sentence, to know it answers.
//
// Structure: top-level `function` declarations and one call at the bottom.
// This is a plain script that htmx re-runs on every boosted navigation.

/** Show the chosen kind's own model as the model field's placeholder. */
function onAiProviderChange(event: Event): void {
  const select = event.target;
  if (!(select instanceof HTMLSelectElement) || !select.matches("[data-ai-provider]")) return;
  const model = document.querySelector<HTMLInputElement>("[data-ai-model]");
  if (model === null) return;
  const picked = select.options[select.selectedIndex];
  const fallback = picked?.dataset["defaultModel"] ?? "";
  model.placeholder = fallback !== "" ? fallback : "e.g. llama3.1 or gpt-5";
}

/** Ask the saved model for one sentence, and say what came back. */
async function askAiModel(button: HTMLButtonElement): Promise<void> {
  const said = document.querySelector<HTMLElement>("[data-ai-said]");
  if (said === null) return;
  said.textContent = "Asking…";
  button.disabled = true;
  try {
    const response = await fetch("/settings/ai/try", { method: "POST" });
    const answer: unknown = await response.json();
    const raw = typeof answer === "object" && answer !== null ? (answer as Record<string, unknown>) : {};
    said.textContent = typeof raw["error"] === "string"
      ? `It did not answer: ${raw["error"]}`
      : `“${typeof raw["said"] === "string" ? raw["said"] : ""}”`;
  } catch {
    said.textContent = "No connection, so it could not be asked.";
  } finally {
    button.disabled = false;
  }
}

function onAiClick(event: Event): void {
  const target = event.target;
  if (!(target instanceof Element)) return;
  const button = target.closest<HTMLButtonElement>("[data-ai-try]");
  if (button !== null) void askAiModel(button);
}

/** Listen once, on the document, so a page swapped in by htmx is covered. */
function initAiSettings(): void {
  const root = document.documentElement;
  if (root.dataset["aiReady"]) return;
  root.dataset["aiReady"] = "1";
  document.addEventListener("change", onAiProviderChange);
  document.addEventListener("click", onAiClick);
}

initAiSettings();
