const TOKEN_KEY = "edith_token";
const HEALTH_LAST_SYNC_KEY = "edith_health_last_sync";

const tokenScreen = document.getElementById("token-screen");
const appShell = document.getElementById("app-shell");
const chatScreen = document.getElementById("chat-screen");
const tokenInput = document.getElementById("token-input");
const connectBtn = document.getElementById("connect-btn");
const tokenError = document.getElementById("token-error");
const statusEl = document.getElementById("status");
const messagesEl = document.getElementById("messages");
const textInput = document.getElementById("text-input");
const sendBtn = document.getElementById("send-btn");
const micBtn = document.getElementById("mic-btn");
const commandMenu = document.getElementById("command-menu");

let token = null;
let sessionId = null;
let voiceEnabled = false;
let mediaRecorder = null;
let recordedChunks = [];
let isRecording = false;

// Every slash command edith/commands.py handles, plus /talk (mic button does
// this on web, so it's not a typed command here). Keep this in sync with
// edith/commands.py and edith/bootstrap.py's WELCOME text.
const COMMANDS = [
  { name: "/afame", desc: "Save a fact about yourself, e.g. /afame I work as a PM at Allore" },
  { name: "/voice on", desc: "Speak Edith's typed replies aloud" },
  { name: "/voice off", desc: "Turn off spoken replies" },
  { name: "/google login", desc: "Connect Gmail, Drive, Calendar, Docs, Sheets" },
  { name: "/whatsapp login", desc: "Connect WhatsApp" },
  { name: "/health login", desc: "Connect Health Connect (steps, weight, calories, workouts) — Android app only" },
  { name: "/approve", desc: "List actions waiting for your confirmation" },
  { name: "/approve", desc: "Confirm and run a pending action, e.g. /approve 3", args: "<id>" },
  { name: "/reject", desc: "Decline a pending action, e.g. /reject 3", args: "<id>" },
  { name: "/new", desc: "Start a fresh conversation" },
  { name: "/facts", desc: "Show what Edith knows about you" },
  { name: "/history", desc: "Search past conversations", args: "<query>" },
  { name: "/exit", desc: "Disconnect" },
];

// --- Minimal markdown -> HTML for Edith's replies (bold/italic/code/lists/
// headers/links) so they render properly instead of showing literal **/#/-
// characters. Escapes HTML first and only ever wraps already-escaped text in
// our own template tags, so nothing in a reply (which can include fetched
// web/email content) can inject live HTML/scripts.

function escapeHtml(str) {
  return str
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

// Groups consecutive "- item" / "1. item" lines into <ul>/<ol> blocks,
// leaving other lines untouched for the caller to handle.
function groupLists(text) {
  const lines = text.split("\n");
  const out = [];
  let listType = null;
  for (const line of lines) {
    const bullet = line.match(/^[-*]\s+(.*)$/);
    const numbered = line.match(/^\d+\.\s+(.*)$/);
    if (bullet || numbered) {
      const tag = bullet ? "ul" : "ol";
      if (listType !== tag) {
        if (listType) out.push(`</${listType}>`);
        out.push(`<${tag}>`);
        listType = tag;
      }
      out.push(`<li>${(bullet || numbered)[1]}</li>`);
    } else {
      if (listType) {
        out.push(`</${listType}>`);
        listType = null;
      }
      out.push(line);
    }
  }
  if (listType) out.push(`</${listType}>`);
  return out.join("\n");
}

// Wraps runs of plain text lines in <p>, joined by <br> — leaves lines that
// are already block-level (headers, list items/wrappers, code block
// placeholders) alone, flushing any pending paragraph first so a header or
// list right after a text line doesn't get swallowed into it.
function wrapParagraphs(text) {
  const blockLine = /^<(h1|h2|h3|ul|ol|\/ul|\/ol|li)|^@@CODEBLOCK\d+@@$/;
  const lines = text.split("\n");
  const out = [];
  let para = [];
  const flush = () => {
    if (para.length) out.push(`<p>${para.join("<br>")}</p>`);
    para = [];
  };
  for (const line of lines) {
    if (line.trim() === "") {
      flush();
    } else if (blockLine.test(line)) {
      flush();
      out.push(line);
    } else {
      para.push(line);
    }
  }
  flush();
  return out.join("");
}

function renderMarkdown(text) {
  let html = escapeHtml(text);

  // Fenced code blocks pulled out first so nothing inside them gets touched
  // by later rules (bold/lists/etc. shouldn't apply inside code).
  const codeBlocks = [];
  html = html.replace(/```[^\n]*\n?([\s\S]*?)```/g, (_, code) => {
    codeBlocks.push(code.replace(/\n$/, ""));
    return `@@CODEBLOCK${codeBlocks.length - 1}@@`;
  });

  html = html.replace(/^### (.+)$/gm, "<h3>$1</h3>");
  html = html.replace(/^## (.+)$/gm, "<h2>$1</h2>");
  html = html.replace(/^# (.+)$/gm, "<h1>$1</h1>");

  html = groupLists(html);

  html = html.replace(/`([^`\n]+)`/g, "<code>$1</code>");
  html = html.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  html = html.replace(/(?<!\*)\*([^*\n]+)\*(?!\*)/g, "<em>$1</em>");
  html = html.replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');

  html = wrapParagraphs(html);

  html = html.replace(/@@CODEBLOCK(\d+)@@/g, (_, i) => `<pre><code>${codeBlocks[i]}</code></pre>`);

  return html;
}

function addMessage(role, content) {
  const div = document.createElement("div");
  div.className = "msg " + role;
  if (role === "edith") {
    div.innerHTML = renderMarkdown(content);
  } else {
    div.textContent = content;
  }
  messagesEl.appendChild(div);
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

// Live "what is Edith doing" indicator — shown the instant a turn is sent
// (label "Working"), not just once a "status" SSE event names a specific
// tool ("Searching the web") — otherwise a turn with no tool calls (or one
// that's just slow to start) shows nothing at all between send and reply.
// One element/timer reused across the whole turn (label can change, the
// elapsed-seconds count doesn't reset), removed once the real reply lands.
let liveStatusEl = null;
let liveStatusLabelEl = null;
let liveStatusStartedAt = null;
let liveStatusInterval = null;

function _formatLiveStatus(label) {
  const elapsed = Math.max(0, Math.round((Date.now() - liveStatusStartedAt) / 1000));
  return `${label} for ${elapsed}s`;
}

function startLiveStatus(label = "Working") {
  liveStatusStartedAt = Date.now();
  if (!liveStatusEl) {
    liveStatusEl = document.createElement("div");
    liveStatusEl.className = "msg status";
    liveStatusEl.innerHTML =
      '<span class="status-dots">' + "<span></span>".repeat(9) + '</span><span class="status-label"></span>';
    liveStatusLabelEl = liveStatusEl.querySelector(".status-label");
    messagesEl.appendChild(liveStatusEl);
  }
  liveStatusEl.dataset.label = label;
  liveStatusLabelEl.textContent = _formatLiveStatus(label);
  messagesEl.scrollTop = messagesEl.scrollHeight;
  if (!liveStatusInterval) {
    liveStatusInterval = setInterval(() => {
      if (liveStatusLabelEl) liveStatusLabelEl.textContent = _formatLiveStatus(liveStatusEl.dataset.label);
    }, 1000);
  }
}

// Called on "status" SSE events to swap in what Edith's actually doing
// (e.g. "Searching the web") without resetting the elapsed-time count —
// unlike startLiveStatus (only called once, at the top of a turn), this must
// NOT touch liveStatusStartedAt, or every tool call would restart the clock.
function showLiveStatus(content) {
  if (!liveStatusEl) {
    startLiveStatus(content);
    return;
  }
  liveStatusEl.dataset.label = content;
  liveStatusLabelEl.textContent = _formatLiveStatus(content);
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

function clearLiveStatus() {
  if (liveStatusInterval) {
    clearInterval(liveStatusInterval);
    liveStatusInterval = null;
  }
  if (liveStatusEl) {
    liveStatusEl.remove();
    liveStatusEl = null;
    liveStatusLabelEl = null;
  }
}

// Reads a text/event-stream response body and calls onEvent(eventType, data)
// for each "event: ...\ndata: ...\n\n" block. Used instead of EventSource
// because EventSource only supports GET with no request body — each turn
// here needs to POST the message/audio payload and get a short-lived stream
// back, not a long-lived GET connection.
async function postSSE(url, body, onEvent) {
  const resp = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!resp.ok) {
    let message = `Request failed (${resp.status})`;
    try {
      message = (await resp.json()).error || message;
    } catch {
      // response wasn't JSON; keep the generic message
    }
    throw new Error(message);
  }
  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let idx;
    while ((idx = buffer.indexOf("\n\n")) !== -1) {
      const rawEvent = buffer.slice(0, idx);
      buffer = buffer.slice(idx + 2);
      const eventMatch = rawEvent.match(/^event: (.+)$/m);
      const dataMatch = rawEvent.match(/^data: (.+)$/m);
      if (dataMatch) onEvent(eventMatch ? eventMatch[1] : "message", JSON.parse(dataMatch[1]));
    }
  }
}

async function connect(candidateToken) {
  try {
    const resp = await fetch("/api/connect", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ token: candidateToken }),
    });
    if (!resp.ok) {
      const err = await resp.json().catch(() => ({}));
      tokenError.textContent = err.error === "unauthorized" ? "Invalid token." : "Connection failed — check your token.";
      return;
    }
    const data = await resp.json();
    token = candidateToken;
    sessionId = data.session_id;
    localStorage.setItem(TOKEN_KEY, token);
    tokenScreen.style.display = "none";
    appShell.style.display = "flex";
    statusEl.textContent = "connected";
    addMessage("system", "Edith is online.");
    switchTab("overview"); // land on the dashboard, not Chat, on every connect
    syncHealthData(); // fire-and-forget — no-op if not authorized yet or not running natively
    registerForPushNotifications(); // fire-and-forget — no-op if not running natively
    if (pendingNotificationTap) {
      pendingNotificationTap = false;
      handleNotificationTap(pendingNotificationType);
      pendingNotificationType = null;
    }
  } catch {
    tokenError.textContent = "Connection error.";
  }
}

// --- Health Connect (Android app only): sync-on-open, no true background sync.
// See edith/memory/health.py / POST /api/health-data on the backend. The plugin
// (@capgo/capacitor-health) is only usable inside the Capacitor WebView — it
// registers itself on window.Capacitor.Plugins.Health, callable directly from
// this plain script with no bundler/import needed. isNativePlatform() is false
// in a normal browser, which is what gates all of this off outside the APK.

const HEALTH_METRIC_TYPES = ["steps", "weight", "calories", "workouts"];

function getHealthPlugin() {
  const cap = window.Capacitor;
  if (!cap || !cap.isNativePlatform || !cap.isNativePlatform()) return null;
  return (cap.Plugins && cap.Plugins.Health) || null;
}

async function healthLogin() {
  const Health = getHealthPlugin();
  if (!Health) {
    addMessage("system", "Health Connect is only available in the Android app.");
    return;
  }
  try {
    const availability = await Health.isAvailable();
    if (!availability.available) {
      addMessage("system", "Health Connect isn't available on this device: " + (availability.reason || "unknown reason"));
      return;
    }
    await Health.requestAuthorization({ read: HEALTH_METRIC_TYPES });
    // requestAuthorization resolving doesn't guarantee the user actually granted
    // access (denying the permission sheet isn't treated as an error) — let
    // syncHealthData's own checkAuthorization call report the real outcome,
    // instead of blindly claiming success here.
    await syncHealthData(/* verbose */ true);
  } catch (err) {
    addMessage("system", "Health Connect login failed: " + err.message);
  }
}

// verbose=true (only from /health login) surfaces what actually happened as a
// system message — not-authorized, zero-new-data, and errors were previously
// silent no-ops, which made "why isn't my data updating" undiagnosable. The
// automatic sync-on-app-open call stays quiet (verbose=false) since it runs
// unprompted on every launch and shouldn't spam the chat.
async function syncHealthData(verbose = false) {
  const Health = getHealthPlugin();
  if (!Health || !sessionId) return;
  const report = (msg) => { if (verbose) addMessage("system", msg); };
  try {
    // Real shape is { readAuthorized: HealthDataType[], readDenied: [...], ... } —
    // NOT { read: { steps: true, ... } } as originally (wrongly) assumed here, which
    // meant this always reported "not authorized" regardless of the real state.
    const auth = await Health.checkAuthorization({ read: HEALTH_METRIC_TYPES });
    const authorized = new Set(auth.readAuthorized || []);
    if (authorized.size === 0) {
      report("Health Connect isn't authorized yet — grant the permission in the sheet, then run /health login again.");
      return;
    }

    const startDate = localStorage.getItem(HEALTH_LAST_SYNC_KEY) || new Date(Date.now() - 7 * 24 * 60 * 60 * 1000).toISOString();
    const endDate = new Date().toISOString();
    const metrics = [];

    if (authorized.has("steps")) {
      const { samples } = await Health.queryAggregated({ dataType: "steps", startDate, endDate, bucket: "day", aggregation: "sum" });
      for (const s of samples) metrics.push({ type: "steps", date: s.startDate.slice(0, 10), value: s.value, unit: s.unit || "count" });
    }

    if (authorized.has("calories")) {
      const { samples } = await Health.queryAggregated({ dataType: "calories", startDate, endDate, bucket: "day", aggregation: "sum" });
      for (const s of samples) metrics.push({ type: "calories", date: s.startDate.slice(0, 10), value: s.value, unit: s.unit || "kilocalorie" });
    }

    if (authorized.has("weight")) {
      const { samples } = await Health.readSamples({ dataType: "weight", startDate, endDate, limit: 50 });
      for (const s of samples) metrics.push({ type: "weight", date: (s.startDate || s.date).slice(0, 10), value: s.value, unit: s.unit || "kilogram" });
    }

    if (authorized.has("workouts")) {
      const { workouts } = await Health.queryWorkouts({ startDate, endDate, limit: 50 });
      for (const w of workouts) {
        const minutes = Math.round((new Date(w.endDate) - new Date(w.startDate)) / 60000);
        metrics.push({ type: "workouts", date: w.startDate.slice(0, 10), value: minutes, unit: "minutes" });
      }
    }

    if (metrics.length === 0) {
      report(
        "Health Connect is authorized, but no steps/weight/calories/workout data was found there. " +
        "Health Connect being installed doesn't mean Samsung Health is feeding it — check Samsung Health's " +
        "own settings for a \"sync with Health Connect\" option."
      );
      return;
    }

    await fetch("/api/health-data", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ token, session_id: sessionId, metrics }),
    });
    localStorage.setItem(HEALTH_LAST_SYNC_KEY, endDate);
    report(`Synced ${metrics.length} health data point(s) from Health Connect.`);
  } catch (err) {
    console.error("Health sync failed:", err); // background sync-on-open stays best-effort/silent
    report("Health Connect sync failed: " + err.message);
  }
}

// --- Push notifications (Android app only): register the device's FCM token
// with the backend on every connect so scheduled-job/alarm completions can be
// pushed. Same isNativePlatform() gating pattern as Health Connect above —
// (@capacitor/push-notifications) only exists inside the Capacitor WebView.

function getPushPlugin() {
  const cap = window.Capacitor;
  if (!cap || !cap.isNativePlatform || !cap.isNativePlatform()) return null;
  return (cap.Plugins && cap.Plugins.PushNotifications) || null;
}

let pushListenersRegistered = false;

// Set when a notification tap is handled before connect() has finished
// populating `token` (a real race on cold start: the OS can launch this
// script fresh from a killed state and deliver the tap event before the
// auto-connect(savedToken) call below resolves). connect() drains this once
// it succeeds.
let pendingNotificationTap = false;
let pendingNotificationType = null;

// Routes a tapped notification by its `data.type` payload (see edith/tools/notify.py's
// `kind` param): "checkin" notifications (routine/todo check-ins) open the chat so the
// user can reply — everything else falls back to the original "replay last job output"
// behavior.
function handleNotificationTap(type) {
  if (!token || !sessionId) {
    pendingNotificationTap = true;
    pendingNotificationType = type;
    return;
  }
  if (type === "checkin") {
    switchTab("chat");
  } else {
    handleJobNotificationTap();
  }
}

async function handleJobNotificationTap() {
  if (!token || !sessionId) {
    pendingNotificationTap = true;
    return;
  }
  try {
    const resp = await fetch("/api/jobs/latest", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ token }),
    });
    const data = await resp.json();
    if (!data.content) return;
    addMessage("edith", data.content);
    if (data.audio_base64) playAudio(data.audio_base64, data.mime_type || "audio/wav");
  } catch (err) {
    console.error("Failed to fetch latest job output for notification tap:", err);
  }
}

async function registerForPushNotifications() {
  const Push = getPushPlugin();
  if (!Push) return;

  if (!pushListenersRegistered) {
    pushListenersRegistered = true;
    Push.addListener("registration", async (result) => {
      try {
        await fetch("/api/register_device", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ token, device_token: result.value, platform: "android" }),
        });
      } catch (err) {
        console.error("Failed to register push device token with backend:", err);
      }
    });
    Push.addListener("registrationError", (err) => {
      console.error("Push notification registration failed:", err);
    });
    // Fires whether the app was backgrounded, foregrounded, or fully killed
    // when the user tapped the notification — Capacitor launches/resumes the
    // app first, then delivers this event once the plugin's ready.
    Push.addListener("pushNotificationActionPerformed", (action) => {
      const type = action && action.notification && action.notification.data && action.notification.data.type;
      handleNotificationTap(type);
    });
  }

  try {
    const perms = await Push.checkPermissions();
    if (perms.receive !== "granted") {
      const requested = await Push.requestPermissions();
      if (requested.receive !== "granted") return;
    }
    await Push.register();
  } catch (err) {
    console.error("Push notification setup failed:", err);
  }
}

connectBtn.addEventListener("click", () => {
  const candidateToken = tokenInput.value.trim();
  if (!candidateToken) return;
  tokenError.textContent = "";
  connect(candidateToken);
});

tokenInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter") connectBtn.click();
});

// Shared handler for events streamed back from /api/message and /api/audio.
function handleTurnEvent(eventType, data) {
  if (eventType === "status") {
    showLiveStatus(data.content); // e.g. "Searching the web" — cleared once the real reply lands
  } else if (eventType === "text") {
    clearLiveStatus();
    addMessage("edith", data.content);
  } else if (eventType === "transcript") {
    addMessage("user", data.content); // what the server heard you say
  } else if (eventType === "audio") {
    playAudio(data.data, data.mime_type || "audio/wav");
  } else if (eventType === "session") {
    sessionId = data.session_id;
  } else if (eventType === "voice_enabled") {
    voiceEnabled = data.voice_enabled;
  }
}

async function sendText() {
  const text = textInput.value.trim();
  if (!text || !sessionId) return;
  addMessage("user", text);
  textInput.value = "";
  closeCommandMenu();

  // /health login is a device-local action (it opens Health Connect's native
  // permission UI) — the backend can't do that, so it's handled entirely here
  // instead of being sent as a normal message like every other slash command.
  if (text.toLowerCase() === "/health login") {
    await healthLogin();
    return;
  }

  startLiveStatus();
  try {
    await postSSE("/api/message", { token, session_id: sessionId, text, voice_enabled: voiceEnabled }, handleTurnEvent);
  } catch (err) {
    clearLiveStatus();
    addMessage("system", "Error: " + err.message);
  }
}

sendBtn.addEventListener("click", sendText);

// On mobile, the on-screen keyboard shrinks the visible viewport — make sure
// the latest message and the input bar stay in view rather than getting
// hidden behind the keyboard.
textInput.addEventListener("focus", () => {
  setTimeout(() => {
    messagesEl.scrollTop = messagesEl.scrollHeight;
    textInput.scrollIntoView({ block: "end", behavior: "smooth" });
  }, 300); // let the keyboard finish animating in first
});

// --- Command palette: shows matching commands whenever the input starts with "/" ---

let menuItems = [];
let activeIndex = -1;

function closeCommandMenu() {
  commandMenu.classList.remove("open");
  commandMenu.innerHTML = "";
  menuItems = [];
  activeIndex = -1;
}

// Re-renders using the CURRENT menuItems/activeIndex — does not reset the
// selection, so arrow-key navigation can call this without losing its place.
function renderCommandMenu() {
  commandMenu.innerHTML = "";
  menuItems.forEach((cmd, i) => {
    const item = document.createElement("div");
    item.className = "cmd-item" + (i === activeIndex ? " active" : "");
    const label = cmd.args ? `${cmd.name} ${cmd.args}` : cmd.name;
    item.innerHTML = `<span class="cmd-name">${label}</span><span class="cmd-desc">${cmd.desc}</span>`;
    item.addEventListener("mousedown", (e) => {
      e.preventDefault(); // keep focus on textInput instead of the menu item
      selectCommand(cmd);
    });
    commandMenu.appendChild(item);
  });
  commandMenu.classList.toggle("open", menuItems.length > 0);
}

// New set of matches (from typing) — resets the selection to the first item.
function setCommandItems(filtered) {
  menuItems = filtered;
  activeIndex = filtered.length ? 0 : -1;
  renderCommandMenu();
}

function selectCommand(cmd) {
  textInput.value = cmd.name + " ";
  closeCommandMenu();
  textInput.focus();
}

function updateCommandMenu() {
  const value = textInput.value;
  if (!value.startsWith("/") || value.includes(" ")) {
    closeCommandMenu();
    return;
  }
  const query = value.toLowerCase();
  const filtered = COMMANDS.filter((c) => c.name.toLowerCase().startsWith(query));
  setCommandItems(filtered);
}

textInput.addEventListener("input", updateCommandMenu);

textInput.addEventListener("keydown", (e) => {
  const menuOpen = commandMenu.classList.contains("open");
  if (menuOpen && e.key === "ArrowDown") {
    e.preventDefault();
    activeIndex = Math.min(activeIndex + 1, menuItems.length - 1);
    renderCommandMenu();
    return;
  }
  if (menuOpen && e.key === "ArrowUp") {
    e.preventDefault();
    activeIndex = Math.max(activeIndex - 1, 0);
    renderCommandMenu();
    return;
  }
  if (menuOpen && e.key === "Escape") {
    closeCommandMenu();
    return;
  }
  if (menuOpen && e.key === "Enter" && activeIndex >= 0) {
    e.preventDefault();
    selectCommand(menuItems[activeIndex]);
    return;
  }
  if (e.key === "Enter") sendText();
});

document.addEventListener("click", (e) => {
  if (!commandMenu.contains(e.target) && e.target !== textInput) closeCommandMenu();
});

// --- Voice: tap mic to start recording, tap again to stop and send ---

// Tracks whatever's currently speaking so a new reply's audio can cut it off
// instead of playing on top of it — without this, sending a message while
// Edith is still talking through the previous one made both play at once.
let currentAudio = null;

function playAudio(base64Data, mimeType) {
  if (currentAudio) {
    currentAudio.pause();
    URL.revokeObjectURL(currentAudio.src);
    currentAudio = null;
  }

  const byteChars = atob(base64Data);
  const bytes = new Uint8Array(byteChars.length);
  for (let i = 0; i < byteChars.length; i++) bytes[i] = byteChars.charCodeAt(i);
  const blob = new Blob([bytes], { type: mimeType });
  const url = URL.createObjectURL(blob);
  const audio = new Audio(url);
  currentAudio = audio;
  audio.onended = () => {
    URL.revokeObjectURL(url);
    if (currentAudio === audio) currentAudio = null;
  };
  audio.play();
}

function blobToBase64(blob) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onloadend = () => resolve(reader.result.split(",")[1]);
    reader.onerror = reject;
    reader.readAsDataURL(blob);
  });
}

// Whisper hallucinates a short filler word ("No,", "Thank you.") when a clip
// opens with a beat of near-silence before speech starts — the mic starts
// capturing the instant the button is tapped, before you've actually begun
// talking. Trimming that lead-in (keeping a small pre-roll so the onset of
// the word isn't clipped) removes the hallucination trigger.
const SILENCE_RMS_THRESHOLD = 0.02;
const SILENCE_WINDOW_SECONDS = 0.02;
const PRE_ROLL_SECONDS = 0.15;
const MIN_TRIM_SECONDS = 0.1; // skip re-encoding if there's barely any lead-in to cut

async function trimLeadingSilence(blob) {
  try {
    const arrayBuffer = await blob.arrayBuffer();
    const audioCtx = new (window.AudioContext || window.webkitAudioContext)();
    const audioBuffer = await audioCtx.decodeAudioData(arrayBuffer);
    const sampleRate = audioBuffer.sampleRate;
    const length = audioBuffer.length;

    const channels = [];
    for (let c = 0; c < audioBuffer.numberOfChannels; c++) channels.push(audioBuffer.getChannelData(c));
    const mono = new Float32Array(length);
    for (let i = 0; i < length; i++) {
      let sum = 0;
      for (let c = 0; c < channels.length; c++) sum += channels[c][i];
      mono[i] = sum / channels.length;
    }

    const windowSize = Math.max(1, Math.round(sampleRate * SILENCE_WINDOW_SECONDS));
    let speechStart = -1;
    for (let start = 0; start < length; start += windowSize) {
      const end = Math.min(start + windowSize, length);
      let sumSq = 0;
      for (let i = start; i < end; i++) sumSq += mono[i] * mono[i];
      if (Math.sqrt(sumSq / (end - start)) > SILENCE_RMS_THRESHOLD) {
        speechStart = start;
        break;
      }
    }
    if (speechStart < 0) return blob; // no clear speech onset found — send the original untouched

    const trimStart = Math.max(0, speechStart - Math.round(sampleRate * PRE_ROLL_SECONDS));
    if (trimStart < sampleRate * MIN_TRIM_SECONDS) return blob; // negligible lead-in, not worth re-encoding

    return encodeWav(mono.subarray(trimStart), sampleRate);
  } catch (err) {
    console.error("Silence trimming failed, sending original clip:", err);
    return blob;
  }
}

function encodeWav(samples, sampleRate) {
  const buffer = new ArrayBuffer(44 + samples.length * 2);
  const view = new DataView(buffer);

  function writeString(offset, str) {
    for (let i = 0; i < str.length; i++) view.setUint8(offset + i, str.charCodeAt(i));
  }

  writeString(0, "RIFF");
  view.setUint32(4, 36 + samples.length * 2, true);
  writeString(8, "WAVE");
  writeString(12, "fmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true); // PCM
  view.setUint16(22, 1, true); // mono
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * 2, true); // byte rate (mono, 16-bit)
  view.setUint16(32, 2, true); // block align
  view.setUint16(34, 16, true); // bits per sample
  writeString(36, "data");
  view.setUint32(40, samples.length * 2, true);

  let offset = 44;
  for (let i = 0; i < samples.length; i++, offset += 2) {
    const s = Math.max(-1, Math.min(1, samples[i]));
    view.setInt16(offset, s < 0 ? s * 0x8000 : s * 0x7fff, true);
  }

  return new Blob([buffer], { type: "audio/wav" });
}

async function startRecording() {
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    mediaRecorder = new MediaRecorder(stream);
    recordedChunks = [];

    mediaRecorder.ondataavailable = (e) => {
      if (e.data.size > 0) recordedChunks.push(e.data);
    };

    mediaRecorder.onstop = async () => {
      stream.getTracks().forEach((t) => t.stop());
      const rawMimeType = mediaRecorder.mimeType || "audio/webm";
      const rawBlob = new Blob(recordedChunks, { type: rawMimeType });
      const blob = await trimLeadingSilence(rawBlob);
      const mimeType = blob.type || rawMimeType;
      const base64Data = await blobToBase64(blob);
      if (!sessionId) return;
      startLiveStatus();
      try {
        await postSSE(
          "/api/audio",
          { token, session_id: sessionId, data: base64Data, mime_type: mimeType },
          handleTurnEvent
        );
      } catch (err) {
        clearLiveStatus();
        addMessage("system", "Error: " + err.message);
      }
    };

    mediaRecorder.start();
    isRecording = true;
    micBtn.classList.add("recording");
  } catch (err) {
    addMessage("system", "Could not access microphone: " + err.message);
  }
}

function stopRecording() {
  if (mediaRecorder && isRecording) {
    mediaRecorder.stop();
    isRecording = false;
    micBtn.classList.remove("recording");
  }
}

micBtn.addEventListener("click", () => {
  if (!sessionId) return;
  if (isRecording) {
    stopRecording();
  } else {
    startRecording();
  }
});

// Auto-connect if we already have a saved token from a previous session.
const savedToken = localStorage.getItem(TOKEN_KEY);
if (savedToken) {
  tokenInput.value = savedToken;
  connect(savedToken);
}
