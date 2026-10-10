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
| POST | `/sync` | `{"tabs": [Tab, ...]}` | Replace the whole tab set |
| POST | `/update` | `{"tab": Tab}` | Upsert one tab |
| POST | `/remove` | `{"tabId": 101, "windowId": 1}` | Remove a closed tab |
| GET | `/search?q=...` | | Tabs whose title/url contain every term in `q` (case-insensitive); all tabs if `q` is empty |
| POST | `/activate` | `{"tabId": 101, "windowId": 1}` | Push an activation to connected extensions (held for 5s if none are connected) |
| WS | `/ws` | | Push channel to the extension; only `chrome-extension://` / `moz-extension://` origins accepted |

`Tab` = `{"tabId": int, "windowId": int, "title": str, "url": str, "favIconUrl": str | null}`

```sh
curl -X POST localhost:8765/update -H 'Content-Type: application/json' \
  -d '{"tab":{"tabId":101,"windowId":1,"title":"GitHub - Pull Requests","url":"https://github.com/pulls"}}'
curl 'localhost:8765/search?q=github'
curl -X POST localhost:8765/remove -H 'Content-Type: application/json' -d '{"tabId":101,"windowId":1}'
```

## Plugin

Copy `plugin/` into Flow Launcher's plugins folder (`%APPDATA%\FlowLauncher\Plugins\FastBrowserTabs`) and vendor its dependency:

```sh
pip install -r requirements.txt -t lib
```

Restart Flow Launcher, then type `tabs <query>`. Selecting a result calls `POST /activate`. If the server is not reachable within 400 ms, the plugin shows a single "Local tab server not running on port 8765" result.

## Extension

Open `chrome://extensions` (or `edge://extensions`), enable Developer mode, click **Load unpacked**, and pick `extension/`. Requires Chrome 116+.

- Sends tab creates/navigations/closes to the server, and does a full `/sync` whenever it (re)connects, since the server's store is in-memory only.
- Holds a WebSocket to `/ws` and pings every 20s, which keeps the MV3 service worker alive. A 30s alarm reconnects it if Chrome suspends the worker anyway.
- On an `activate` message, focuses the tab and its window.
