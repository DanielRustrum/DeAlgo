"use strict";
// Moving on: saying the item is finished, and showing the next.
//
// Part of Focus mode; see main.ts.
/** Nothing left: stop the timer and the player and say so. */
function finishFocusSitting(sitting) {
    stopFocusTimer(sitting);
    paintFocusQueue(sitting, []);
    const elements = sitting.elements;
    elements.root.classList.add("focus-done");
    elements.post.hidden = true;
    elements.timer.hidden = true;
    elements.title.textContent = "All caught up";
    elements.channel.textContent = "Nothing left unwatched";
    elements.remaining.textContent = "0";
    elements.count.textContent = "0";
    setFocusStatus(sitting, "");
    if (sitting.player)
        sitting.player.stopVideo();
}
/** The form the server is asked for the next item with. */
function focusAdvanceBody(sitting, markWatched) {
    const body = new URLSearchParams();
    body.set("order", sitting.order);
    body.set("playlist", sitting.playlist);
    body.set("watched", markWatched ? "1" : "0");
    body.set("skipped", sitting.passedOver.join(","));
    focusSeenFields(sitting, body);
    return body.toString();
}
/** markWatched=false means "skip": it stays unwatched but sits out this
 *  sitting. */
function advanceFocus(sitting, markWatched) {
    if (sitting.advancing)
        return;
    sitting.advancing = true;
    stopFocusTimer(sitting);
    setFocusStatus(sitting, markWatched ? "marking done…" : "skipping…");
    // A skipped item is remembered, so the server does not offer it again this sitting.
    if (!markWatched && !sitting.passedOver.includes(sitting.current.id)) {
        sitting.passedOver.push(sitting.current.id);
    }
    // The server says what comes next, so a queue left open cannot bring back something already done.
    fetch(`/focus/${sitting.current.id}/finished`, {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        body: focusAdvanceBody(sitting, markWatched),
    })
        .then((response) => {
        if (!response.ok)
            throw new Error(`HTTP ${response.status}`);
        return response.json();
    })
        .then((data) => {
        sitting.advancing = false;
        setFocusStatus(sitting, "");
        if (!data.next) {
            finishFocusSitting(sitting);
            return;
        }
        showFocusItem(sitting, data.next, data.remaining);
        paintFocusQueue(sitting, data.upcoming);
    })
        // Nothing advanced: say so, and give a timed item its time back.
        .catch(() => {
        sitting.advancing = false;
        setFocusStatus(sitting, "could not advance — check the connection");
        if (focusIsRead(sitting.current) && focusIsTimed(sitting.current)) {
            startFocusTimer(sitting, sitting.current);
        }
    });
}

"use strict";
// What Focus mode works with: an item, a sitting, and the page it runs in.
//
// Part of Focus mode; see main.ts.

"use strict";
// Finding the page's parts, and the status line under the player.
//
// Part of Focus mode; see main.ts.
/** An element the template always renders. Missing means the template
 *  changed, which is worth saying by name rather than half-wiring the page. */
function focusElement(id) {
    const found = document.getElementById(id);
    if (!found)
        throw new Error(`Focus mode: #${id} is missing from the page`);
    return found;
}
/** An element that is legitimately absent sometimes. */
function optionalFocusElement(id) {
    return document.getElementById(id);
}
/** Every element Focus mode updates, found once. */
function collectFocusElements(root) {
    return {
        root,
        stage: focusElement("focus-stage"),
        post: focusElement("focus-post"),
        tiles: focusElement("focus-tiles"),
        words: focusElement("focus-words"),
        postUrl: focusElement("focus-post-url"),
        timer: focusElement("focus-timer"),
        timerCount: focusElement("focus-timer-count"),
        timerWord: focusElement("focus-timer-word"),
        timerFill: focusElement("focus-timer-fill"),
        timerToggle: focusElement("focus-timer-toggle"),
        title: focusElement("focus-title"),
        channel: focusElement("focus-channel"),
        remaining: focusElement("focus-remaining"),
        status: focusElement("focus-status"),
        list: focusElement("focus-list"),
        count: focusElement("focus-count"),
        reload: focusElement("focus-reload"),
        next: focusElement("focus-next"),
        skip: focusElement("focus-skip"),
        frame: optionalFocusElement("focus-player"),
    };
}
/** The queue the server rendered into the page, or null if there is none. */
function readFocusQueue() {
    var _a;
    const script = document.getElementById("focus-queue");
    if (!script)
        return [];
    return JSON.parse((_a = script.textContent) !== null && _a !== void 0 ? _a : "[]");
}
/** Say something after the title, or clear it with an empty string. */
function setFocusStatus(sitting, message) {
    sitting.elements.status.textContent = message ? ` · ${message}` : "";
}

"use strict";
// The built-in "youtube" player (registry PLAYERS), and waiting for its API.
//
// Part of Focus mode; see main.ts.
/** Attach YouTube's player to the existing iframe, once, when the API is here. */
function buildFocusPlayer(sitting) {
    const api = window.YT;
    if (sitting.player || !sitting.elements.frame || !api || !api.Player)
        return;
    // Attaching to the existing iframe keeps our allow list. Letting the API
    // build its own would re-add the pop-out button over fullscreen.
    sitting.player = new api.Player("focus-player", {
        events: {
            onReady: () => {
                sitting.ready = true;
                setFocusStatus(sitting, "");
                // Opened on a post: the player is loaded but must stay quiet.
                if (focusIsRead(sitting.current) && sitting.player)
                    sitting.player.pauseVideo();
            },
            onStateChange: (event) => {
                // Stopping and starting again is what engagement is counted from.
                if (event.data === api.PlayerState.PLAYING)
                    sitting.seen.playing = true;
                if (event.data === api.PlayerState.PAUSED && sitting.seen.playing) {
                    sitting.seen.pauses += 1;
                    sitting.seen.playing = false;
                }
                noteFocusPosition(sitting);
                if (event.data === api.PlayerState.ENDED && !focusIsRead(sitting.current)) {
                    advanceFocus(sitting, true);
                }
            },
            onError: () => {
                // Private, deleted or not embeddable: do not strand the queue on it.
                if (focusIsRead(sitting.current))
                    return;
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
function awaitYouTubeApi(sitting) {
    if (!sitting.elements.frame)
        return;
    let waited = 0;
    const waiting = window.setInterval(() => {
        buildFocusPlayer(sitting);
        waited += 200;
        if (sitting.player || waited > 15000)
            window.clearInterval(waiting);
    }, 200);
    const earlier = window.onYouTubeIframeAPIReady;
    window.onYouTubeIframeAPIReady = () => {
        if (typeof earlier === "function")
            earlier();
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

"use strict";
// The up-next list.
//
// Part of Focus mode; see main.ts.
/** One row of the up-next list. */
function buildQueueRow(item) {
    const row = document.createElement("li");
    row.dataset["video"] = String(item.id);
    const title = document.createElement("span");
    title.className = "queue-title";
    if (focusIsRead(item)) {
        const tag = document.createElement("span");
        tag.className = "pill pill-post";
        tag.textContent = item.kind === "post" ? "post" : item.source.toLowerCase();
        title.appendChild(tag);
        title.appendChild(document.createTextNode(" "));
    }
    title.appendChild(document.createTextNode(item.title));
    const meta = document.createElement("span");
    meta.className = "meta";
    meta.textContent = queueRowMeta(item);
    row.appendChild(title);
    row.appendChild(meta);
    return row;
}
/** The line under a queue row's title: source, feed, and length for a video. */
function queueRowMeta(item) {
    let line = item.channel;
    if (item.playlist)
        line += ` · ${item.playlist}`;
    if (item.kind === "video" && item.duration && item.duration !== "—") {
        line += ` · ${item.duration}`;
    }
    return line;
}
/** Rebuilt from the server's own queue rather than by deleting rows, so the
 *  list cannot drift away from what actually plays next. */
function paintFocusQueue(sitting, items) {
    const list = sitting.elements.list;
    list.textContent = "";
    if (items.length === 0) {
        const none = document.createElement("li");
        none.className = "empty";
        none.textContent = "Nothing after this one.";
        list.appendChild(none);
        return;
    }
    items.forEach((item) => {
        list.appendChild(buildQueueRow(item));
    });
}

"use strict";
// Showing one item: a video in the player, or a post on its own.
//
// Part of Focus mode; see main.ts.
/** The privacy-enhanced embed address for a video, set to autoplay. */
function focusEmbedUrl(videoId) {
    const origin = encodeURIComponent(window.location.origin);
    return `https://www.youtube-nocookie.com/embed/${videoId}?enablejsapi=1&autoplay=1&rel=0&origin=${origin}`;
}
/** One picture from a post, linking to itself. */
function buildFocusTile(url) {
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
function focusIsRead(item) {
    return item.player !== "youtube";
}
/** Whether this one is on the clock at all.
 *
 *  Only what came through a Decay box. Everything else sits there until you
 *  say you are done with it: a countdown nobody asked for is a countdown
 *  that hurries you for no reason, and the box is how you ask. */
function focusIsTimed(item) {
    return item !== null && item.seconds !== null;
}
/** Show a post: its pictures and words, with its timer if it has one. */
function showFocusPost(sitting, item) {
    const elements = sitting.elements;
    elements.tiles.textContent = "";
    item.images.forEach((url) => {
        elements.tiles.appendChild(buildFocusTile(url));
    });
    elements.words.textContent = item.body;
    elements.postUrl.href = item.url;
    elements.postUrl.textContent = `Open it on ${item.source} ↗`;
    elements.post.hidden = false;
    elements.timer.hidden = !focusIsTimed(item);
    elements.stage.hidden = true;
    if (sitting.player)
        sitting.player.pauseVideo();
    if (focusIsTimed(item))
        startFocusTimer(sitting, item);
    else
        stopFocusTimer(sitting);
}
/** Show a video in the player, or reload the iframe if the API never came. */
function showFocusVideo(sitting, item) {
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
    if (elements.frame)
        elements.frame.src = focusEmbedUrl(item.video_id);
}
/** Show the next item, of whichever kind, and update the counts and links. */
function showFocusItem(sitting, item, remaining) {
    const elements = sitting.elements;
    sitting.current = item;
    sitting.seen = freshFocusSeen(sitting.seen.pickedId);
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
    if (focusIsRead(item))
        showFocusPost(sitting, item);
    else
        showFocusVideo(sitting, item);
}

"use strict";
// The reading timer: how long you get with one item.
//
// Part of Focus mode; see main.ts.
/** Draw the seconds left and the bar. */
function paintFocusTimer(sitting) {
    const seconds = Math.max(0, Math.ceil(sitting.msLeft / 1000));
    sitting.elements.timerCount.textContent = sitting.held ? "held" : `${seconds}s`;
    const share = (sitting.msLeft / (sitting.allowed * 1000)) * 100;
    sitting.elements.timerFill.style.width = `${share}%`;
}
/** Stop the countdown. */
function stopFocusTimer(sitting) {
    if (sitting.timerId !== null)
        window.clearInterval(sitting.timerId);
    sitting.timerId = null;
}
/** Start counting down an item's time: its Decay time, or the account's default. */
function startFocusTimer(sitting, item) {
    var _a;
    stopFocusTimer(sitting);
    sitting.held = false;
    // What a Decay box gave you with this one, if anything did. The account's
    // own setting is what everything else gets.
    sitting.allowed = (_a = item === null || item === void 0 ? void 0 : item.seconds) !== null && _a !== void 0 ? _a : sitting.postSeconds;
    sitting.locked = (item === null || item === void 0 ? void 0 : item.locked) === true;
    sitting.msLeft = sitting.allowed * 1000;
    sitting.elements.timerWord.textContent = sitting.locked
        ? "until the next one — cannot be paused"
        : "until the next one";
    paintFocusTimer(sitting);
    sitting.timerId = window.setInterval(() => tickFocusTimer(sitting), 100);
}
/** One tenth of a second off; moves on when the time is up, unless paused. */
function tickFocusTimer(sitting) {
    if (sitting.held)
        return;
    sitting.msLeft -= 100;
    paintFocusTimer(sitting);
    if (sitting.msLeft > 0)
        return;
    stopFocusTimer(sitting);
    advanceFocus(sitting, true);
}
/** Hold the timer where it is, for a post still being read.
 *
 *  Unless a Lock piece said otherwise. The point of a locked stretch is one
 *  that runs whether you are looking or not, so it refuses rather than
 *  quietly doing nothing. */
function toggleFocusTimer(sitting) {
    if (sitting.locked) {
        setFocusStatus(sitting, "this one cannot be paused");
        return;
    }
    sitting.held = !sitting.held;
    sitting.elements.timerWord.textContent = sitting.held
        ? "paused — click to resume"
        : "until the next one";
    paintFocusTimer(sitting);
}

"use strict";
// Focus mode: go through the queue, marking each item done as it finishes.
//
// Two sorts of thing arrive in the same queue. A video finishes on its own and
// the player says so. Everything else — a community post, an item from a feed
// somewhere else — is read, and has no end of its own, so reading time is the
// only thing that can advance it: hence the timer, and hence the pause, since
// something you are still reading should not slide out from under you.
//
// Advancing asks the server for the next item rather than walking the list it
// was given, so a queue left open overnight cannot resurrect something watched
// or removed in the meantime. The embedded list is only a preview.
//
// Structure: top-level `function` declarations, and one call at the bottom of
// this file. The parts in this folder are joined into the one focus.js the page
// loads (`make js`, ops/join_scripts.py), a plain script that htmx re-runs
// each time it swaps the Focus page in, and a top-level `const` or `class` would throw "already declared"
// on the second visit. Everything a sitting needs to remember therefore lives
// in one FocusSitting object, passed explicitly rather than captured.
/** Load the first video, with the origin the page is actually served from. */
function pointFrameAtFirstVideo(sitting) {
    var _a;
    const frame = sitting.elements.frame;
    if (!frame)
        return;
    // The origin has to be the host actually browsed to, not whatever
    // PAMPHLETS_PUBLIC_URL happens to say.
    const source = (_a = frame.dataset["src"]) !== null && _a !== void 0 ? _a : "";
    frame.src = `${source}&origin=${encodeURIComponent(window.location.origin)}`;
}
/** Wire up Next, Skip and the timer's pause button. */
function bindFocusControls(sitting) {
    sitting.elements.next.addEventListener("click", () => advanceFocus(sitting, true));
    sitting.elements.skip.addEventListener("click", () => advanceFocus(sitting, false));
    sitting.elements.timerToggle.addEventListener("click", () => toggleFocusTimer(sitting));
}
/** A player that never reports ready is the failure people actually hit: say
 *  so, and name the way out, rather than leaving a blank rectangle. */
function warnIfPlayerNeverWakes(sitting) {
    window.setTimeout(() => {
        if (sitting.ready)
            return;
        setFocusStatus(sitting, sitting.player
            ? "the player is not responding — try Reload"
            : "auto-advance is unavailable — Done · next still works");
    }, 8000);
}
/** A fresh sitting on the page, opening on its first item. */
function newFocusSitting(root, opening) {
    var _a, _b, _c, _d;
    return {
        elements: collectFocusElements(root),
        order: (_a = root.dataset["order"]) !== null && _a !== void 0 ? _a : "oldest",
        playlist: (_b = root.dataset["playlist"]) !== null && _b !== void 0 ? _b : "",
        postSeconds: parseInt((_c = root.dataset["postSeconds"]) !== null && _c !== void 0 ? _c : "", 10) || 30,
        allowed: parseInt((_d = root.dataset["postSeconds"]) !== null && _d !== void 0 ? _d : "", 10) || 30,
        locked: false,
        current: opening,
        passedOver: [],
        player: null,
        ready: false,
        advancing: false,
        timerId: null,
        msLeft: 0,
        held: false,
        seen: freshFocusSeen(focusPickedId(opening)),
    };
}
/** The item a sitting was opened on by clicking its card — a feed card or a
 *  pamphlet story says `picked=1` — rather than reached in turn or reloaded. */
function focusPickedId(opening) {
    const asked = new URLSearchParams(window.location.search);
    return asked.get("picked") === "1" ? opening.id : null;
}
/** A clean slate for the item just shown. */
function freshFocusSeen(pickedId) {
    return { shownAt: Date.now(), pauses: 0, reached: 0, duration: 0, playing: false, pickedId };
}
/** Read how far the player got, while it can still be asked. */
function noteFocusPosition(sitting) {
    const player = sitting.player;
    if (player === null || focusIsRead(sitting.current))
        return;
    try {
        sitting.seen.reached = Math.max(sitting.seen.reached, player.getCurrentTime() || 0);
        sitting.seen.duration = player.getDuration() || sitting.seen.duration;
    }
    catch (_a) {
        // A player not ready yet has nothing to say.
    }
}
/** How the open item went, as form fields. */
function focusSeenFields(sitting, body) {
    noteFocusPosition(sitting);
    const seen = sitting.seen;
    body.set("seconds", ((Date.now() - seen.shownAt) / 1000).toFixed(1));
    body.set("pauses", String(seen.pauses));
    body.set("clicked", seen.pickedId === sitting.current.id ? "1" : "0");
    if (!focusIsRead(sitting.current)) {
        body.set("reached", seen.reached.toFixed(1));
        body.set("duration", seen.duration.toFixed(1));
    }
}
/** Leaving the page with something open still says how it went. */
function sayFocusSeenOnLeaving(sitting) {
    window.addEventListener("pagehide", () => {
        if (sitting.elements.root.classList.contains("focus-done"))
            return;
        const body = new URLSearchParams();
        focusSeenFields(sitting, body);
        navigator.sendBeacon(`/focus/${sitting.current.id}/seen`, body);
    }, { once: true });
}
/** Focus mode's entry point: start a sitting if this is the Focus page and there is a queue. */
function initFocusMode() {
    const root = document.getElementById("focus");
    if (!root)
        return; // every other page
    const opening = readFocusQueue()[0];
    if (!opening)
        return; // nothing left to go through
    const sitting = newFocusSitting(root, opening);
    bindFocusControls(sitting);
    sayFocusSeenOnLeaving(sitting);
    pointFrameAtFirstVideo(sitting);
    awaitYouTubeApi(sitting);
    if (focusIsRead(sitting.current) && focusIsTimed(sitting.current)) {
        startFocusTimer(sitting, sitting.current);
    }
    else if (!focusIsRead(sitting.current)) {
        warnIfPlayerNeverWakes(sitting);
    }
}
initFocusMode();
