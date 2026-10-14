# Fast Browser Tabs

Instant browser-tab search for [Flow Launcher](https://www.flowlauncher.com/), backed by a local in-memory cache instead of UI Automation scans.

```
extension/ ──HTTP: tab changes──▶ server/ (127.0.0.1:8765) ◀──HTTP: search/activate── plugin/
           ◀──WebSocket: activate──┘
```

| Directory | What it is |
|-----------|------------|
| `server/` | FastAPI cache server holding open tabs in memory |
| `plugin/` | Flow Launcher Python plugin (`tabs` action keyword) |
| `extension/` | Chrome/Edge MV3 extension that pushes tab changes and switches tabs |

## Server

```sh
cd server
pip install -r requirements.txt
uvicorn main:app --host 127.0.0.1 --port 8765
```

**Run at Windows login:** `powershell -ExecutionPolicy Bypass -File server\install-windows-startup.ps1` copies the server to `%LOCALAPPDATA%\FastBrowserTabs\server`, creates a venv there, and adds a hidden launcher to the Startup folder (logs in `server.log` next to `main.py`). Re-run it after changing `main.py`.

| Method | Path | Body | Purpose |
|--------|------|------|---------|
| POST | `/sync` | `{"client": "...", "tabs": [Tab, ...]}` | Replace that client's tabs (other clients' tabs are kept) |
| POST | `/update` | `{"tab": Tab}` | Upsert one tab |
| POST | `/remove` | `{"client": "...", "tabId": 101, "windowId": 1}` | Remove a closed tab |
| GET | `/search?q=...` | | Tabs whose title/url contain every term in `q` (case-insensitive); all tabs if `q` is empty |
| POST | `/activate` | `{"client": "...", "tabId": 101, "windowId": 1}` | Push an activation to the owning extension (held for 5s if it isn't connected) |
| WS | `/ws?client=...` | | Push channel to the extension; only `chrome-extension://` / `moz-extension://` origins accepted. A client's tabs are dropped when it disconnects |

`Tab` = `{"client": str, "tabId": int, "windowId": int, "title": str, "url": str, "favIconUrl": str | null}`

```sh
curl -X POST localhost:8765/update -H 'Content-Type: application/json' \
  -d '{"tab":{"client":"demo","tabId":101,"windowId":1,"title":"GitHub - Pull Requests","url":"https://github.com/pulls"}}'
curl 'localhost:8765/search?q=github'
curl -X POST localhost:8765/remove -H 'Content-Type: application/json' -d '{"client":"demo","tabId":101,"windowId":1}'
```

## Plugin

Uses Flow Launcher's JSON-RPC v2 protocol (`"Language": "Python_v2"`): Flow starts `main.py` once and keeps it running, sending newline-delimited JSON-RPC over stdin/stdout. That avoids a ~90 ms Python startup per keystroke; queries take a few ms. No third-party dependencies.

Copy `plugin/` into Flow Launcher's plugins folder (`%APPDATA%\FlowLauncher\Plugins\FastBrowserTabs`) and restart Flow Launcher, then type `tabs <query>` (or set the action keyword to `* t` for global results). Selecting a result calls `POST /activate` and raises the browser window. If the server is unreachable, the plugin shows a "Local tab server not running on port 8765" result when invoked by keyword, and nothing in global search.

Note: Flow doesn't restart the plugin process if it crashes, and treats any stderr output as an error, so handlers are guarded and stderr is silenced.

## Extension

Open `chrome://extensions` (or `edge://extensions`), enable Developer mode, click **Load unpacked**, and pick `extension/`. Requires Chrome 116+.

Load it in every browser or profile you want searchable (Chrome profiles, Edge, Brave, ...). Each install generates a random client id, stored in `chrome.storage.local`, so tab ids from different browsers don't collide and activations go only to the browser that owns the tab.

- Sends tab creates/navigations/closes to the server, and does a full `/sync` whenever it (re)connects, since the server's store is in-memory only.
- Holds a WebSocket to `/ws` and pings every 20s, which keeps the MV3 service worker alive. A 30s alarm reconnects it if Chrome suspends the worker anyway.
- On an `activate` message, focuses the tab and its window.
