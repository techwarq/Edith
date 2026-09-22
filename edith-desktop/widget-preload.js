// Preload for the island widget. Runs in an isolated context with contextIsolation
// on and sandbox on, so it can only require the small allowed subset of electron
// (contextBridge + ipcRenderer). It exposes a minimal, typed surface — the
// renderer (widget.js) can do nothing the main process didn't explicitly grant.
//
// All networking lives on the main-process side of these channels (see main.js):
// the renderer's CSP is connect-src 'none', so this bridge is the ONLY way out.

const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("edith", {
  // POST /api/connect -> { ok, session_id, status }. Main owns the token.
  connect: () => ipcRenderer.invoke("edith:connect"),

  // Fire a voice turn (POST /api/audio, SSE). Results arrive via onTurn().
  sendAudio: (payload) => ipcRenderer.send("edith:audio", payload),

  // Fire a typed turn (POST /api/message, SSE). Results arrive via onTurn().
  sendText: (payload) => ipcRenderer.send("edith:message", payload),

  // Subscribe to streamed turn events: cb({ type, data }).
  onTurn: (cb) => ipcRenderer.on("edith:turn", (_e, ev) => cb(ev)),

  // Window chrome: grow/shrink + re-center the frameless window at the notch.
  expand: () => ipcRenderer.send("widget:expand"),
  collapse: () => ipcRenderer.send("widget:collapse"),

  // Open the full Edith dashboard (the original hosted web UI) in a normal window.
  openDashboard: () => ipcRenderer.send("widget:open-dashboard"),

  // Global-shortcut toggle relayed from main.
  onToggle: (cb) => ipcRenderer.on("widget:toggle", () => cb()),

  // Global "speak" shortcut relayed from main — start/stop a voice turn.
  onSpeak: (cb) => ipcRenderer.on("widget:speak", () => cb()),
});
