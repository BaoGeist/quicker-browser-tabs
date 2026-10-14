// Pushes tab state to the local cache server and switches tabs on its request.

const SERVER = "http://127.0.0.1:8765";
const WS_URL = "ws://127.0.0.1:8765/ws";
const PING_MS = 20_000; // < 30s so the open WebSocket keeps this service worker alive

let ws = null;
let connecting = false; // getClientId() is async, so guard against overlapping connects
let pingTimer = null;

// Identifies this browser/profile to the server, since tab and window ids are
// only unique within one browser. Persisted so it survives worker restarts.
let clientIdPromise = null;
function getClientId() {
  clientIdPromise ??= chrome.storage.local.get("clientId").then(async ({ clientId }) => {
    if (!clientId) {
      clientId = crypto.randomUUID();
      await chrome.storage.local.set({ clientId });
    }
    return clientId;
  });
  return clientIdPromise;
}

function toPayload(tab, client) {
  return {
    client,
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
  const [client, tabs] = await Promise.all([getClientId(), chrome.tabs.query({})]);
  await post("/sync", { client, tabs: tabs.map((tab) => toPayload(tab, client)) });
}

async function postTab(tab) {
  await post("/update", { tab: toPayload(tab, await getClientId()) });
}

async function postRemove(tabId, windowId) {
  await post("/remove", { client: await getClientId(), tabId, windowId });
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

async function connect() {
  if (connecting || ws) return;

  connecting = true;
  try {
    ws = new WebSocket(`${WS_URL}?client=${encodeURIComponent(await getClientId())}`);
  } finally {
    connecting = false;
  }

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

chrome.tabs.onCreated.addListener(postTab);

chrome.tabs.onUpdated.addListener((tabId, change, tab) => {
  if ("title" in change || "url" in change || "favIconUrl" in change) {
    postTab(tab);
  }
});

chrome.tabs.onRemoved.addListener((tabId, info) => postRemove(tabId, info.windowId));

// Moving a tab between windows changes its (windowId, tabId) key.
chrome.tabs.onDetached.addListener((tabId, info) => postRemove(tabId, info.oldWindowId));
chrome.tabs.onAttached.addListener(async (tabId) => postTab(await chrome.tabs.get(tabId)));

// Prerendered/discarded tabs can swap ids.
chrome.tabs.onReplaced.addListener(() => fullSync());

// --- Lifecycle ---

// If the worker was suspended (e.g. server was down), the alarm wakes it to reconnect.
chrome.alarms.create("reconnect", { periodInMinutes: 0.5 });
chrome.alarms.onAlarm.addListener((alarm) => alarm.name === "reconnect" && connect());

chrome.runtime.onStartup.addListener(connect);
chrome.runtime.onInstalled.addListener(connect);
connect();
