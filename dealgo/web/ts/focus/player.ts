// The YouTube player, and waiting for its API.
//
// Part of Focus mode; see main.ts.

/** Attach YouTube's player to the existing iframe, once, when the API is here. */
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

/**
 * Attach the player once YouTube's API is here, however it arrives.
 *
 * Getting hold of the API is the fiddly part, because this page is usually
 * reached through an hx-boost swap rather than a page load:
 *
 *   * a script htmx inserts does not honour `defer`, so load order is not
 *     guaranteed and the API can run before the callback below exists;
 *   * YT calls onYouTubeIframeAPIReady exactly once per document, so on a
 *     second visit within the same document it never fires at all.
 *
 * Either way the player would stay null, the queue would stop advancing, and
 * the video on screen would simply keep playing. So: take the API if it is
 * already here, ask to be told if it is not, and poll as well, since neither
 * signal is reliable on its own.
 */
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
