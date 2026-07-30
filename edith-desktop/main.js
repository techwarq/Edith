// Edith desktop — thin native wrapper around the hosted web UI (edith/web/),
// same "just load the hosted URL" pattern as edith-android's Capacitor
// server.url (see capacitor.config.json there). No local copy of the web
// assets is bundled; this is a BrowserWindow pointed at the real backend,
// same as a browser tab would be.
//
// Server URL is overridable without a rebuild via ~/.edith/desktop_config.json
// (a JSON file with a "serverUrl" key) — falls back to the same Railway URL
// the Android app uses if that file doesn't exist. Useful for pointing a dev
// build at http://localhost:8000 during local testing.

const { app, BrowserWindow } = require("electron");
const fs = require("fs");
const os = require("os");
const path = require("path");

const DEFAULT_SERVER_URL = "https://edith-production-d100.up.railway.app";
const CONFIG_PATH = path.join(os.homedir(), ".edith", "desktop_config.json");

function resolveServerUrl() {
  try {
    const raw = fs.readFileSync(CONFIG_PATH, "utf8");
    const config = JSON.parse(raw);
    if (config.serverUrl) return config.serverUrl;
  } catch {
    // no config file, or it's malformed — fall back to the default silently,
    // same as every other optional-config path in this project (see
    // edith/config.py's pattern for Qdrant/Temporal/Firebase)
  }
  return process.env.EDITH_DESKTOP_URL || DEFAULT_SERVER_URL;
}

// electron-builder reads build.mac.icon from package.json for the packaged
// .dmg; that config doesn't apply to `npm start` (plain `electron .`), so the
// dock/window icon needs to be set explicitly here too for dev runs.
const ICON_PATH = path.join(__dirname, "build", "icon.icns");

function createWindow() {
  const win = new BrowserWindow({
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
  win.loadURL(resolveServerUrl());
}

app.whenReady().then(() => {
  // Best-effort only: a bad/missing icon path must never block the window
  // from opening (it did exactly that once, silently, when build/icon.icns
  // wasn't yet listed in package.json's build.files and this threw before
  // createWindow() ran).
  try {
    if (process.platform === "darwin" && app.dock) app.dock.setIcon(ICON_PATH);
  } catch (err) {
    console.error("Failed to set dock icon:", err);
  }
  createWindow();
  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") app.quit();
});
