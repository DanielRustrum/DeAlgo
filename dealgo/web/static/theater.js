// Theater mode: play the queue through, marking each video watched as it ends.
//
// Advancing asks the server for the next video rather than walking the list it
// was given, so a queue left open overnight cannot resurrect something watched
// or removed in the meantime. The embedded list is only a preview.
(function () {
  var root = document.getElementById("theater");
  if (!root) return;

  var queue = JSON.parse(document.getElementById("theater-queue").textContent);
  if (!queue.length) return;

  var order = root.dataset.order;
  var playlist = root.dataset.playlist;
  var current = queue[0];
  var player = null;
  var advancing = false;

  var titleEl = document.getElementById("theater-title");
  var channelEl = document.getElementById("theater-channel");
  var remainingEl = document.getElementById("theater-remaining");
  var statusEl = document.getElementById("theater-status");
  var listEl = document.getElementById("theater-list");
  var countEl = document.getElementById("theater-count");

  function say(message) {
    statusEl.textContent = message ? " · " + message : "";
  }

  function show(video, remaining) {
    current = video;
    titleEl.textContent = video.title;
    channelEl.textContent = video.channel;
    remainingEl.textContent = remaining;
    // The preview list is one behind now; drop the row we just started.
    var row = listEl.querySelector('[data-video="' + video.id + '"]');
    if (row) row.remove();
    countEl.textContent = Math.max(0, remaining - 1);
  }

  function finished() {
    root.classList.add("theater-done");
    titleEl.textContent = "All caught up";
    channelEl.textContent = "Nothing left unwatched";
    remainingEl.textContent = "0";
    countEl.textContent = "0";
    say("");
    if (player && player.stopVideo) player.stopVideo();
  }

  // markWatched=false means "skip": it stays unwatched but sits out this sitting.
  function advance(markWatched) {
    if (advancing) return;
    advancing = true;
    say(markWatched ? "marking watched…" : "skipping…");

    var body = new URLSearchParams();
    body.set("order", order);
    body.set("playlist", playlist);
    body.set("watched", markWatched ? "1" : "0");

    fetch("/watch/" + current.id + "/finished", {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: body.toString(),
    })
      .then(function (response) {
        if (!response.ok) throw new Error("HTTP " + response.status);
        return response.json();
      })
      .then(function (data) {
        advancing = false;
        say("");
        if (!data.next) return finished();
        show(data.next, data.remaining);
        if (player && player.loadVideoById) player.loadVideoById(data.next.video_id);
      })
      .catch(function () {
        advancing = false;
        say("could not advance — check the connection");
      });
  }

  document.getElementById("theater-next").addEventListener("click", function () {
    advance(true);
  });
  document.getElementById("theater-skip").addEventListener("click", function () {
    advance(false);
  });

  // Point our own iframe at the first video, with the origin of the page the
  // viewer actually loaded.
  var frame = document.getElementById("theater-player");
  frame.src = frame.dataset.src + "&origin=" + encodeURIComponent(window.location.origin);

  window.onYouTubeIframeAPIReady = function () {
    // Attaching to the existing iframe keeps our allow list. Letting the API
    // build its own would re-add the pop-out button over fullscreen.
    player = new YT.Player("theater-player", {
      events: {
        onStateChange: function (event) {
          if (event.data === YT.PlayerState.ENDED) advance(true);
        },
        onError: function () {
          // Private, deleted or not embeddable: do not strand the queue on it.
          say("this one would not play — skipping");
          advance(false);
        },
      },
    });
  };

  // If YouTube's script never arrives, say so instead of showing a blank stage.
  // If YouTube's API script never arrives the video still plays — it just will
  // not advance by itself, so say so rather than leaving it a mystery.
  setTimeout(function () {
    if (!player) say("auto-advance unavailable — use Watched · next");
  }, 8000);
})();
