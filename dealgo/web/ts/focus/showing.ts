// Showing one item: a video in the player, or a post on its own.
//
// Part of Focus mode; see main.ts.

/** The privacy-enhanced embed address for a video, set to autoplay. */
function focusEmbedUrl(videoId: string): string {
  const origin = encodeURIComponent(window.location.origin);
  return `https://www.youtube-nocookie.com/embed/${videoId}?enablejsapi=1&autoplay=1&rel=0&origin=${origin}`;
}

/** One picture from a post, linking to itself. */
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

/** Whether this is read rather than played. Asked as "has no player" so a
 *  source that chose none is read by default, which is the safe way round:
 *  the worst case is a reading timer on something, not an empty player
 *  nobody can advance. "youtube" is the one player built in. */
function focusIsRead(item: FocusItem): boolean {
  return item.player !== "youtube";
}

/** Whether this one is on the clock at all.
 *
 *  Only what came through a Decay box. Everything else sits there until you
 *  say you are done with it: a countdown nobody asked for is a countdown
 *  that hurries you for no reason, and the box is how you ask. */
function focusIsTimed(item: FocusItem | null): boolean {
  return item !== null && item.seconds !== null;
}

/** Show a post: its pictures and words, with its timer if it has one. */
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
  elements.timer.hidden = !focusIsTimed(item);
  elements.stage.hidden = true;
  if (sitting.player) sitting.player.pauseVideo();
  if (focusIsTimed(item)) startFocusTimer(sitting, item);
  else stopFocusTimer(sitting);
}

/** Show a video in the player, or reload the iframe if the API never came. */
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

/** Show the next item, of whichever kind, and update the counts and links. */
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
