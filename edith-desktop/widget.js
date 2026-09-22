// Renderer for the Edith desktop island widget.
//
// This file NEVER talks to the network directly — the CSP forbids it
// (connect-src 'none'). Everything goes through window.edith, the IPC bridge
// exposed by widget-preload.js, which does the HTTP from the Node main process
// (so there's no CORS and no web/server changes). The mic still runs here:
// getUserMedia + MediaRecorder need the renderer, and file:// is a secure
// context in Chromium so the mic is allowed.
//
// The audio/SSE contract mirrors edith/web/app.js exactly:
// (main owns the token and injects it — the renderer never sends one)
//   window.edith.connect() -> { ok, session_id }
//   window.edith.sendAudio({ session_id, data, mime_type })   (voice turn)
//   window.edith.sendText({ session_id, text, voice_enabled }) (typed turn)
//   window.edith.onTurn(cb) -> cb({ type, data })  where type is one of
//     status | transcript | text | audio | session | voice_enabled | error | _done

const htmlEl = document.documentElement;
const pillOpen = document.getElementById("pill-open");
const pillMic = document.getElementById("pill-mic");
const panel = document.getElementById("panel");
const collapseBtn = document.getElementById("collapse-btn");
const dashboardBtn = document.getElementById("dashboard-btn");
const transcriptEl = document.getElementById("transcript");
const statusEl = document.getElementById("status");
const statusTextEl = statusEl.querySelector(".status-text");
const micBtn = document.getElementById("mic");
const textInput = document.getElementById("text");
const sendBtn = document.getElementById("send");

let sessionId = null;
let isRecording = false;
let mediaRecorder = null;
let recordedChunks = [];
let currentAudio = null;

// ---------------------------------------------------------------- UI helpers

function addMessage(role, content) {
  const div = document.createElement("div");
  div.className = "bubble " + role;
  div.textContent = content;
  transcriptEl.appendChild(div);
  transcriptEl.scrollTop = transcriptEl.scrollHeight;
  return div;
}

function setStatus(text, busy) {
  statusTextEl.textContent = text || "";
  statusEl.classList.toggle("busy", !!busy);
}

// -------------------------------------------------------------- expand/collapse

function expand() {
  htmlEl.setAttribute("data-state", "expanded");
  window.edith.expand(); // ask main to grow + re-center the window at the notch
  setTimeout(() => textInput.focus(), 60);
}

function collapse() {
  if (isRecording) stopRecording();
  htmlEl.setAttribute("data-state", "collapsed");
  window.edith.collapse();
}

// Tap the island's voice control: open the panel AND start listening in one go,
// so you can talk to Edith straight from the notch without hunting for the mic.
function speakFromIsland() {
  if (htmlEl.getAttribute("data-state") !== "expanded") expand();
  if (isRecording) stopRecording();
  else startRecording();
}

pillOpen.addEventListener("click", expand);
pillMic.addEventListener("click", (e) => {
  e.stopPropagation();
  speakFromIsland();
});
collapseBtn.addEventListener("click", collapse);
dashboardBtn.addEventListener("click", () => window.edith.openDashboard());

// Global shortcut (registered in main) toggles the whole thing.
window.edith.onToggle(() => {
  if (htmlEl.getAttribute("data-state") === "expanded") collapse();
  else expand();
});

// Global "speak" shortcut: open the panel + start/stop listening — same as
// tapping the island's mic, but from anywhere.
window.edith.onSpeak(() => speakFromIsland());

// ---------------------------------------------------------------- connection

// No token prompt — main injects the token. Just connect and be ready.
async function connect() {
  const res = await window.edith.connect();
  if (!res || !res.ok) {
    const msg =
      res && res.status === 401
        ? "Token rejected by the server — check EDITH_API_TOKEN."
        : res && res.error === "no token configured"
          ? "No token configured. Add one to ~/.edith/desktop_config.json."
          : "Couldn't reach Edith.";
    addMessage("system", msg);
    return false;
  }
  sessionId = res.session_id;
  if (!transcriptEl.childElementCount) {
    addMessage("system", "Edith is online. Tap the mic or press ⌃⌥Space to talk.");
  }
  return true;
}

// ------------------------------------------------------------ streamed events

window.edith.onTurn(({ type, data }) => {
  if (type === "status") {
    setStatus(data.content, true);
  } else if (type === "transcript") {
    addMessage("user", data.content);
  } else if (type === "text") {
    setStatus("", false);
    addMessage("edith", data.content);
  } else if (type === "audio") {
    playAudio(data.data, data.mime_type || "audio/wav");
  } else if (type === "session") {
    sessionId = data.session_id;
  } else if (type === "error") {
    setStatus("", false);
    addMessage("system", "Error: " + (data.message || "something went wrong"));
  } else if (type === "_done") {
    setStatus("", false);
  }
});

// ---------------------------------------------------------------- typed turns

async function sendText() {
  const text = textInput.value.trim();
  if (!text || !sessionId) return;
  addMessage("user", text);
  textInput.value = "";
  setStatus("Thinking", true);
  // voice_enabled: true — the whole point of the widget is that she speaks back.
  window.edith.sendText({ session_id: sessionId, text, voice_enabled: true });
}
sendBtn.addEventListener("click", sendText);
textInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter") sendText();
});

// ------------------------------------------------------------------- playback

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

// -------------------------------------------------------- mic (voice control)

function blobToBase64(blob) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onloadend = () => resolve(reader.result.split(",")[1]);
    reader.onerror = reject;
    reader.readAsDataURL(blob);
  });
}

// Whisper hallucinates filler words when a clip opens with silence; trim the
// lead-in (keeping a small pre-roll). Ported verbatim from edith/web/app.js so
// the widget behaves identically to the main app's mic.
const SILENCE_RMS_THRESHOLD = 0.02;
const SILENCE_WINDOW_SECONDS = 0.02;
const PRE_ROLL_SECONDS = 0.15;
const MIN_TRIM_SECONDS = 0.1;

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
    if (speechStart < 0) return blob;
    const trimStart = Math.max(0, speechStart - Math.round(sampleRate * PRE_ROLL_SECONDS));
    if (trimStart < sampleRate * MIN_TRIM_SECONDS) return blob;
    return encodeWav(mono.subarray(trimStart), sampleRate);
  } catch (err) {
    console.error("Silence trimming failed, sending original clip:", err);
    return blob;
  }
}

function encodeWav(samples, sampleRate) {
  const buffer = new ArrayBuffer(44 + samples.length * 2);
  const view = new DataView(buffer);
  const writeString = (offset, str) => {
    for (let i = 0; i < str.length; i++) view.setUint8(offset + i, str.charCodeAt(i));
  };
  writeString(0, "RIFF");
  view.setUint32(4, 36 + samples.length * 2, true);
  writeString(8, "WAVE");
  writeString(12, "fmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, 1, true);
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * 2, true);
  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true);
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
  if (!sessionId) {
    addMessage("system", "Not connected yet.");
    return;
  }
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
      setStatus("Thinking", true);
      window.edith.sendAudio({ session_id: sessionId, data: base64Data, mime_type: mimeType });
    };
    mediaRecorder.start();
    isRecording = true;
    micBtn.classList.add("recording");
    micBtn.textContent = "⏹";
    pillMic.classList.add("recording");
    setStatus("Listening…", false);
  } catch (err) {
    addMessage("system", "Could not access microphone: " + err.message);
  }
}

function stopRecording() {
  if (mediaRecorder && isRecording) {
    mediaRecorder.stop();
    isRecording = false;
    micBtn.classList.remove("recording");
    micBtn.textContent = "🎙️";
    pillMic.classList.remove("recording");
  }
}

micBtn.addEventListener("click", () => {
  if (isRecording) stopRecording();
  else startRecording();
});

// --------------------------------------------------------------------- boot

connect();
