// Edith desktop — a floating "Dynamic Island" voice widget that hugs the notch,
// plus the original full dashboard window on demand.
//
// The island (widget.html / widget.js) is a LOCAL, bundled UI — not the hosted
// web page — but it drives the exact same backend as the web/Android apps. To
// avoid CORS (a local file:// origin calling the Railway server) and any change
// to the web/server code, every network call is proxied through this main
// process over IPC: the renderer asks, Node fetches, results stream back. Only
// the mic runs in the renderer (getUserMedia needs a document; file:// is a
// secure context in Chromium so it's allowed once we grant the permission).
//
// The full dashboard window is unchanged: a BrowserWindow pointed at the real
// backend, same as a browser tab. Server URL is overridable without a rebuild
// via ~/.edith/desktop_config.json ("serverUrl" key), falling back to the same
// Railway URL the Android app uses.

const { app, BrowserWindow, ipcMain, session, globalShortcut, screen } = require("electron");
const fs = require("fs");
const os = require("os");
const path = require("path");

const DEFAULT_SERVER_URL = "https://edith-production-d100.up.railway.app";
const CONFIG_PATH = path.join(os.homedir(), ".edith", "desktop_config.json");
const ICON_PATH = path.join(__dirname, "build", "icon.icns");

// Collapsed = the notch pill; expanded = the conversation panel. The renderer
// asks main to switch between these via the widget:expand / widget:collapse IPC
// channels, and main re-centers the frameless window under the notch each time.
const COLLAPSED = { width: 260, height: 52 };
const EXPANDED = { width: 460, height: 600 };

function readConfig() {
  try {
    return JSON.parse(fs.readFileSync(CONFIG_PATH, "utf8"));
  } catch {
    // no config file, or malformed — callers fall back to defaults.
    return {};
  }
}

const CONFIG = readConfig();
const SERVER_URL = CONFIG.serverUrl || process.env.EDITH_DESKTOP_URL || DEFAULT_SERVER_URL;

// The backend requires a token on every call (public URL), but the USER
// shouldn't have to paste one — main resolves it once and injects it into every
// request, so the widget never shows a token prompt. Resolution order:
//   1. ~/.edith/desktop_config.json  ("token")
//   2. env EDITH_API_TOKEN
//   3. dev fallback: the sibling dashboard's .env.local, which already holds the
//      token for this exact server (only present when run from the repo; a
//      packaged .dmg falls back to 1/2).
function resolveToken() {
  if (CONFIG.token) return CONFIG.token;
  if (process.env.EDITH_API_TOKEN) return process.env.EDITH_API_TOKEN;
  try {
    const envLocal = fs.readFileSync(
      path.join(__dirname, "..", "edith-dashboard", ".env.local"),
      "utf8",
    );
    const match = envLocal.match(/^EDITH_API_TOKEN=(.+)$/m);
    if (match) return match[1].trim();
  } catch {
    // not running from the repo checkout — use config or env instead.
  }
  return "";
}

const API_TOKEN = resolveToken();

// Global shortcuts, both overridable via ~/.edith/desktop_config.json
// ("speakShortcut" / "toggleShortcut"):
//   speak  — bring the island up and start/stop listening (toggle-to-talk;
//            globalShortcut can't observe key-up, so hold-to-talk isn't possible)
//   toggle — show/hide + expand/collapse the panel
// Control+Option+Space (⌃⌥Space). A global hotkey needs a real key on top of
// the modifiers — a bare ⌃⌥ chord can't be registered without a native key tap.
const SPEAK_SHORTCUT = CONFIG.speakShortcut || "Control+Alt+Space";
const TOGGLE_SHORTCUT = CONFIG.toggleShortcut || "CommandOrControl+Shift+E";

let widgetWindow = null;
let dashboardWindow = null;

// ---------------------------------------------------------------- island window

// Place the frameless window centered under the notch. Uses workArea so it sits
// just below the menu bar rather than under it; on non-notch Macs it reads as a
// floating Dynamic Island at top-center.
function positionWidget(win, width, height) {
  if (!win || win.isDestroyed()) return;
  const { x, y, width: screenWidth } = screen.getPrimaryDisplay().workArea;
  const nx = Math.round(x + (screenWidth - width) / 2);
  const ny = y + 6;
  win.setBounds({ x: nx, y: ny, width, height });
}

function createWidgetWindow() {
  if (widgetWindow && !widgetWindow.isDestroyed()) {
    widgetWindow.show();
    widgetWindow.focus();
    return widgetWindow;
  }

  widgetWindow = new BrowserWindow({
    width: COLLAPSED.width,
    height: COLLAPSED.height,
    frame: false,
    transparent: true,
    hasShadow: false, // the glass draws its own shadow; a window shadow around
    // transparent pixels looks wrong
    resizable: false,
    movable: true,
    maximizable: false,
    minimizable: false,
    fullscreenable: false,
    skipTaskbar: true,
    alwaysOnTop: true,
    title: "Edith",
    webPreferences: {
      preload: path.join(__dirname, "widget-preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });

  // Float above normal windows and stay visible across Spaces / fullscreen apps,
  // like a real menu-bar accessory.
  widgetWindow.setAlwaysOnTop(true, "screen-saver");
  widgetWindow.setVisibleOnAllWorkspaces(true, { visibleOnFullScreen: true });

  positionWidget(widgetWindow, COLLAPSED.width, COLLAPSED.height);
  widgetWindow.loadFile(path.join(__dirname, "widget.html"));

  widgetWindow.on("closed", () => {
    widgetWindow = null;
  });
  return widgetWindow;
}

// ---------------------------------------------------------------- dashboard window

// The original full app — the hosted web UI in a normal resizable window.
function createDashboardWindow() {
  if (dashboardWindow && !dashboardWindow.isDestroyed()) {
    dashboardWindow.show();
    dashboardWindow.focus();
    return dashboardWindow;
  }
  dashboardWindow = new BrowserWindow({
    width: 1280,
    height: 860,
    minWidth: 720,
    minHeight: 560,
    title: "Edith",
    icon: ICON_PATH,
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });
  dashboardWindow.loadURL(SERVER_URL);
  dashboardWindow.on("closed", () => {
    dashboardWindow = null;
  });
  return dashboardWindow;
}

// ---------------------------------------------------------------- IPC: API proxy

// Consume an SSE ("event: X\ndata: {json}\n\n") stream from the backend and
// forward each parsed block to the renderer as { type, data } on `channel`.
// Mirrors the postSSE parser in edith/web/app.js, but runs in Node (no CORS).
async function streamSSE(url, payload, sender, channel) {
  let resp;
  try {
    resp = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  } catch (err) {
    safeSend(sender, channel, { type: "error", data: { message: err.message } });
    return;
  }
  if (!resp.ok || !resp.body) {
    let message = `Request failed (${resp.status})`;
    try {
      message = (await resp.json()).error || message;
    } catch {
      // response wasn't JSON; keep the generic message
    }
    safeSend(sender, channel, { type: "error", data: { message } });
    return;
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
      if (dataMatch) {
        safeSend(sender, channel, {
          type: eventMatch ? eventMatch[1] : "message",
          data: JSON.parse(dataMatch[1]),
        });
      }
    }
  }
  safeSend(sender, channel, { type: "_done" });
}

// The widget window can close mid-stream; don't throw on a dead webContents.
function safeSend(sender, channel, msg) {
  if (sender && !sender.isDestroyed()) sender.send(channel, msg);
}

ipcMain.handle("edith:connect", async () => {
  if (!API_TOKEN) return { ok: false, status: 0, error: "no token configured" };
  try {
    const resp = await fetch(`${SERVER_URL}/api/connect`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ token: API_TOKEN }),
    });
    if (!resp.ok) return { ok: false, status: resp.status };
    const data = await resp.json();
    return { ok: true, session_id: data.session_id };
  } catch (err) {
    return { ok: false, status: 0, error: err.message };
  }
});

// Main owns the token — inject it so the renderer never has to know it.
ipcMain.on("edith:audio", (event, payload) => {
  streamSSE(`${SERVER_URL}/api/audio`, { ...payload, token: API_TOKEN }, event.sender, "edith:turn");
});

ipcMain.on("edith:message", (event, payload) => {
  streamSSE(`${SERVER_URL}/api/message`, { ...payload, token: API_TOKEN }, event.sender, "edith:turn");
});

// ---------------------------------------------------------------- IPC: window chrome

ipcMain.on("widget:expand", (event) => {
  positionWidget(BrowserWindow.fromWebContents(event.sender), EXPANDED.width, EXPANDED.height);
});

ipcMain.on("widget:collapse", (event) => {
  positionWidget(BrowserWindow.fromWebContents(event.sender), COLLAPSED.width, COLLAPSED.height);
});

ipcMain.on("widget:open-dashboard", () => {
  createDashboardWindow();
});

// ---------------------------------------------------------------- app lifecycle

app.whenReady().then(() => {
  // Grant microphone access to our own local widget (getUserMedia). The check
  // handler covers the synchronous permission query MediaRecorder makes.
  session.defaultSession.setPermissionRequestHandler((_wc, permission, callback) => {
    callback(permission === "media");
  });
  session.defaultSession.setPermissionCheckHandler((_wc, permission) => permission === "media");

  createWidgetWindow();

  // Show/hide + expand/collapse the island.
  const okToggle = globalShortcut.register(TOGGLE_SHORTCUT, () => {
    if (!widgetWindow || widgetWindow.isDestroyed()) {
      createWidgetWindow();
    } else if (widgetWindow.isVisible()) {
      widgetWindow.webContents.send("widget:toggle");
    } else {
      widgetWindow.show();
    }
  });
  if (!okToggle) console.error("Could not register toggle shortcut:", TOGGLE_SHORTCUT);

  // Speak from anywhere: bring the island up and start/stop listening. If the
  // window was just created its renderer isn't loaded yet, so wait for the load
  // before sending — otherwise the message is dropped.
  const okSpeak = globalShortcut.register(SPEAK_SHORTCUT, () => {
    const fresh = !widgetWindow || widgetWindow.isDestroyed();
    const win = fresh ? createWidgetWindow() : widgetWindow;
    if (!win.isVisible()) win.show();
    if (fresh) {
      win.webContents.once("did-finish-load", () => win.webContents.send("widget:speak"));
    } else {
      win.webContents.send("widget:speak");
    }
  });
  if (!okSpeak) console.error("Could not register speak shortcut:", SPEAK_SHORTCUT);

  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) createWidgetWindow();
  });
});

app.on("will-quit", () => {
  globalShortcut.unregisterAll();
});

// Keep running in the background on macOS even with no visible window (the
// island is a menu-bar-style accessory). On other platforms, quit as usual.
app.on("window-all-closed", () => {
  if (process.platform !== "darwin") app.quit();
});
