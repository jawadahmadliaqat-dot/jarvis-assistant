/* Jarvis web HUD — frontend logic.
   Polls the local server every second; no websockets, no external
   services. Voice input uses the browser SpeechRecognition API when
   available (Chrome/Edge); otherwise it says so and falls back to typing.
*/

(function () {
  "use strict";

  var $ = function (id) { return document.getElementById(id); };

  var state = { serverState: "IDLE", muted: false, logSeen: 0, busy: false };
  var mouth = $("mouth");
  var waveform = $("waveform");
  var bars = [];
  var i;
  for (i = 0; i < 36; i++) {
    var bar = document.createElement("div");
    bar.className = "bar";
    waveform.appendChild(bar);
    bars.push(bar);
  }

  /* ---------- clock ---------- */
  function tickClock() {
    var now = new Date();
    var p = function (n) { return (n < 10 ? "0" : "") + n; };
    $("clock").textContent =
      p(now.getHours()) + ":" + p(now.getMinutes()) + ":" + p(now.getSeconds());
  }
  tickClock();
  setInterval(tickClock, 1000);

  /* ---------- helpers ---------- */
  function fmtUptime(seconds) {
    if (seconds === null || seconds === undefined) return "—";
    var h = Math.floor(seconds / 3600);
    var m = Math.floor((seconds % 3600) / 60);
    var s = seconds % 60;
    var p = function (n) { return (n < 10 ? "0" : "") + n; };
    return p(h) + ":" + p(m) + ":" + p(s);
  }

  function setGauge(id, value) {
    var panel = $(id);
    var fill = panel.querySelector(".gauge-fill");
    var val = panel.querySelector(".gauge-val");
    if (value === null || value === undefined) {
      fill.style.width = "0%";
      fill.classList.remove("hot");
      val.textContent = "N/A";
      return;
    }
    fill.style.width = Math.max(0, Math.min(100, value)) + "%";
    fill.classList.toggle("hot", value >= 80);
    val.textContent = value + "%";
  }

  function esc(text) {
    return String(text)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }

  /* ---------- polling ---------- */
  function renderState(data) {
    state.serverState = data.state || "IDLE";
    document.body.dataset.state = state.serverState;
    $("state-badge").textContent = state.serverState;
    $("face-state").textContent = "JARVIS — " + state.serverState;
    $("provider-label").textContent = "Provider: " + (data.provider || "?");
    setGauge("gauge-cpu", data.cpu);
    setGauge("gauge-memory", data.memory);
    setGauge("gauge-disk", data.disk);
    setGauge("gauge-gpu", data.gpu);
    $("stat-uptime").textContent = fmtUptime(data.uptime);
    $("stat-processes").textContent =
      data.processes === null || data.processes === undefined ? "—" : data.processes;
    $("stat-platform").textContent = data.platform || "—";
    $("stat-engine").textContent = data.provider || "—";
    $("stat-voice").textContent = data.voice_muted ? "Muted" : "On";
    state.muted = !!data.voice_muted;
    $("btn-mute").textContent = state.muted ? "🔊 Unmute voice" : "🔇 Mute voice";
    renderTasks(data.tasks || []);
  }

  function renderTasks(tasks) {
    var list = $("task-list");
    if (!tasks.length) {
      list.innerHTML = '<li class="dim">No background tasks.</li>';
      return;
    }
    list.innerHTML = tasks.map(function (t) {
      return "<li>" + esc(t.description || t.id) +
        '<span class="task-status">' + esc(t.status || "") + "</span></li>";
    }).join("");
  }

  function renderLog(lines) {
    var log = $("comms-log");
    for (; state.logSeen < lines.length; state.logSeen++) {
      var line = lines[state.logSeen];
      var div = document.createElement("div");
      div.className = "log-line";
      div.innerHTML =
        '<span class="t">' + esc(line.time) + "</span>" +
        '<span class="tag-' + esc(line.tag.toLowerCase()) + '">' +
        esc(line.tag) + "</span> " + esc(line.text);
      log.appendChild(div);
    }
    log.scrollTop = log.scrollHeight;
  }

  function poll() {
    fetch("/api/state")
      .then(function (r) { return r.json(); })
      .then(renderState)
      .catch(function () { /* server away; keep last values */ });
    fetch("/api/log")
      .then(function (r) { return r.json(); })
      .then(function (d) { renderLog(d.log || []); })
      .catch(function () { /* same */ });
  }
  poll();
  setInterval(poll, 1000);

  /* ---------- commands ---------- */
  function sendCommand(text) {
    text = (text || "").trim();
    if (!text || state.busy) return;
    state.busy = true;
    $("btn-send").disabled = true;
    fetch("/api/command", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: text })
    })
      .then(function (r) { return r.json(); })
      .then(function () { poll(); })
      .catch(function () { /* reply will surface via the log poll */ })
      .finally(function () {
        state.busy = false;
        $("btn-send").disabled = false;
        $("command-input").focus();
      });
  }

  $("btn-send").addEventListener("click", function () {
    sendCommand($("command-input").value);
    $("command-input").value = "";
  });

  $("command-input").addEventListener("keydown", function (e) {
    if (e.key === "Enter") {
      sendCommand(e.target.value);
      e.target.value = "";
    }
  });

  /* ---------- controls ---------- */
  $("btn-briefing").addEventListener("click", function () {
    fetch("/api/briefing", { method: "POST" })
      .then(function () { poll(); });
  });

  $("btn-tasks").addEventListener("click", function () {
    var panel = $("tasks");
    panel.classList.remove("flash");
    void panel.offsetWidth; /* restart the animation */
    panel.classList.add("flash");
    panel.scrollIntoView({ behavior: "smooth", block: "nearest" });
    poll();
  });

  $("btn-mute").addEventListener("click", function () {
    fetch("/api/mute", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ muted: !state.muted })
    }).then(function () { poll(); });
  });

  /* ---------- hold to talk ---------- */
  var SpeechRecognition =
    window.SpeechRecognition || window.webkitSpeechRecognition;
  var talkBtn = $("btn-talk");

  if (!SpeechRecognition) {
    talkBtn.disabled = true;
    $("mic-note").hidden = false;
  } else {
    var recognition = new SpeechRecognition();
    recognition.lang = "en-US";
    recognition.interimResults = false;
    recognition.maxAlternatives = 1;
    var listening = false;

    recognition.onresult = function (event) {
      var transcript = event.results[0][0].transcript;
      if (transcript) sendCommand(transcript);
    };
    recognition.onend = function () {
      listening = false;
      talkBtn.classList.remove("armed");
      fetch("/api/listen", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ active: false })
      }).then(function () { poll(); });
    };
    recognition.onerror = function () {
      listening = false;
      talkBtn.classList.remove("armed");
    };

    function startTalk(e) {
      if (e) e.preventDefault();
      if (listening) return;
      listening = true;
      talkBtn.classList.add("armed");
      fetch("/api/listen", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ active: true })
      });
      try { recognition.start(); } catch (err) { listening = false; }
    }
    function stopTalk() {
      if (!listening) return;
      try { recognition.stop(); } catch (err) { /* already stopped */ }
    }
    talkBtn.addEventListener("pointerdown", startTalk);
    talkBtn.addEventListener("pointerup", stopTalk);
    talkBtn.addEventListener("pointerleave", stopTalk);
  }

  /* ---------- face + waveform animation ---------- */
  var amp = 0; /* smoothed amplitude, 0..1 */
  var last = performance.now();

  function animate(now) {
    var dt = Math.min(0.1, (now - last) / 1000);
    last = now;
    var speaking = state.serverState === "SPEAKING";
    var listening = state.serverState === "LISTENING";
    var t = now / 1000;
    var target;
    if (speaking) {
      target = 0.55 + 0.45 * Math.abs(Math.sin(t * 7.3)) * Math.abs(Math.sin(t * 3.1));
    } else if (listening) {
      target = 0.25 + 0.15 * Math.sin(t * 2.0);
    } else {
      target = 0.06 + 0.04 * Math.sin(t * 0.8); /* idle breathing */
    }
    amp += (target - amp) * Math.min(1, dt * 10);

    var mouthH = 5 + amp * 26;
    mouth.setAttribute("height", mouthH.toFixed(1));
    mouth.setAttribute("y", (288 - mouthH / 2).toFixed(1));

    for (var j = 0; j < bars.length; j++) {
      var wobble = Math.abs(Math.sin(t * 5 + j * 1.35)) * 0.7 +
                   Math.abs(Math.sin(t * 9.1 + j * 0.6)) * 0.3;
      var h = 4 + amp * 34 * wobble;
      bars[j].style.height = h.toFixed(1) + "px";
    }
    requestAnimationFrame(animate);
  }
  requestAnimationFrame(animate);
})();
