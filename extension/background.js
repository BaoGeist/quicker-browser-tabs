// Pushes tab state to the local cache server and switches tabs on its request.

const SERVER = "http://127.0.0.1:8765";
const WS_URL = "ws://127.0.0.1:8765/ws";
const PING_MS = 20_000; // < 30s so the open WebSocket keeps this service worker alive

let ws = null;
let pingTimer = null;

function toPayload(tab) {
  return {
    tabId: tab.id,
    windowId: tab.windowId,
    title: tab.title || "",
    url: tab.url || tab.pendingUrl || "",
    favIconUrl: tab.favIconUrl || null,
  };
}

async function post(path, body) {
  try {
    await fetch(SERVER + path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  } catch {
    // Server offline; the next successful connect does a full sync.
  }
}

async function fullSync() {
  const tabs = await chrome.tabs.query({});
  await post("/sync", { tabs: tabs.map(toPayload) });
}

async function activate(tabId, windowId) {
  try {
    await chrome.tabs.update(tabId, { active: true });
    await chrome.windows.update(windowId, { focused: true });
  } catch (err) {
    // Tab may have closed since the result was shown; resync to drop it.
    console.warn("activate failed", tabId, windowId, err);
    fullSync();
  }
}

function connect() {
  if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) return;

  ws = new WebSocket(WS_URL);

  ws.onopen = () => {
    // The server keeps tabs only in memory, so resync on every (re)connect.
    fullSync();
    pingTimer = setInterval(() => ws.readyState === WebSocket.OPEN && ws.send("ping"), PING_MS);
  };

  ws.onmessage = (msg) => {
    if (msg.data === "pong") return;
    const event = JSON.parse(msg.data);
    if (event.type === "activate") activate(event.tabId, event.windowId);
  };

  ws.onclose = () => {
    clearInterval(pingTimer);
    ws = null;
    setTimeout(connect, 2000);
  };
}

// --- Tab events -> server ---

chrome.tabs.onCreated.addListener((tab) => post("/update", { tab: toPayload(tab) }));

chrome.tabs.onUpdated.addListener((tabId, change, tab) => {
  if ("title" in change || "url" in change || "favIconUrl" in change) {
    post("/update", { tab: toPayload(tab) });
  }
});

chrome.tabs.onRemoved.addListener((tabId, info) => post("/remove", { tabId, windowId: info.windowId }));

// Moving a tab between windows changes its (windowId, tabId) key.
chrome.tabs.onDetached.addListener((tabId, info) => post("/remove", { tabId, windowId: info.oldWindowId }));
chrome.tabs.onAttached.addListener(async (tabId) => post("/update", { tab: toPayload(await chrome.tabs.get(tabId)) }));

// Prerendered/discarded tabs can swap ids.
chrome.tabs.onReplaced.addListener(() => fullSync());

// --- Lifecycle ---

// If the worker was suspended (e.g. server was down), the alarm wakes it to reconnect.
chrome.alarms.create("reconnect", { periodInMinutes: 0.5 });
chrome.alarms.onAlarm.addListener((alarm) => alarm.name === "reconnect" && connect());

chrome.runtime.onStartup.addListener(connect);
chrome.runtime.onInstalled.addListener(connect);
connect();
