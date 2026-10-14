"""Local in-memory tab cache server.

Run with:  uvicorn main:app --host 127.0.0.1 --port 8765
"""

import logging
import time
from collections import deque
from typing import Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("tab-server")

app = FastAPI(title="Fast Browser Tabs cache")


class Tab(BaseModel):
    client: str = ""  # id of the extension install (browser/profile) that owns the tab
    tabId: int
    windowId: int
    title: str = ""
    url: str = ""
    favIconUrl: Optional[str] = None


class SyncRequest(BaseModel):
    client: str = ""
    browser: str = ""  # e.g. "Chrome", "Edge"
    label: str = ""  # user-set profile name from the extension's options page
    focusedWindowId: Optional[int] = None
    tabs: list[Tab]


class UpdateRequest(BaseModel):
    tab: Tab


class TabRef(BaseModel):
    client: str = ""
    tabId: int
    windowId: int


class FocusRequest(BaseModel):
    client: str = ""
    windowId: int


# Each browser/profile numbers its tabs and windows independently, so tabs are
# keyed by the extension's client id too.
# (client, windowId, tabId) -> (tab as dict, lowercased "title\nurl" haystack for search)
_tabs: dict[tuple[str, int, int], tuple[dict, str]] = {}
# client -> {"browser": ..., "label": ...}, from its latest /sync.
_client_info: dict[str, dict] = {}
# (client, windowId) -> monotonic time the window was last focused; search lists
# tabs from recently focused windows first.
_focused_at: dict[tuple[str, int], float] = {}
# Connected browser extensions, by client id.
_clients: dict[str, WebSocket] = {}
# Activations made while no extension was connected: (monotonic time, event).
_activations: deque[tuple[float, dict]] = deque(maxlen=20)
ACTIVATION_TTL = 5.0  # seconds; older queued activations are dropped


def _put(tab: Tab) -> None:
    data = tab.model_dump()
    _tabs[(tab.client, tab.windowId, tab.tabId)] = (data, f"{tab.title}\n{tab.url}".lower())


@app.post("/sync")
def sync(req: SyncRequest):
    # Replace only this client's tabs; other browsers keep theirs.
    _drop_client_tabs(req.client)
    _client_info[req.client] = {"browser": req.browser, "label": req.label}
    if req.focusedWindowId is not None:
        _focused_at[(req.client, req.focusedWindowId)] = time.monotonic()
    for tab in req.tabs:
        _put(tab.model_copy(update={"client": req.client}))
    log.info("sync %r: %d tabs (%d total)", req.client, len(req.tabs), len(_tabs))
    return {"ok": True, "count": len(req.tabs)}


def _drop_client_tabs(client: str) -> None:
    for key in [k for k in _tabs if k[0] == client]:
        del _tabs[key]


def _forget_client(client: str) -> None:
    _drop_client_tabs(client)
    _client_info.pop(client, None)
    for key in [k for k in _focused_at if k[0] == client]:
        del _focused_at[key]


@app.post("/focus")
def focus(req: FocusRequest):
    _focused_at[(req.client, req.windowId)] = time.monotonic()
    return {"ok": True}


@app.post("/update")
def update(req: UpdateRequest):
    _put(req.tab)
    return {"ok": True}


@app.post("/remove")
def remove(ref: TabRef):
    removed = _tabs.pop((ref.client, ref.windowId, ref.tabId), None) is not None
    return {"ok": True, "removed": removed}


@app.get("/search")
def search(q: str = ""):
    # Every whitespace-separated term must appear in the title or url.
    terms = q.lower().split()
    matches = [data for data, hay in _tabs.values() if all(t in hay for t in terms)]
    matches.sort(key=lambda d: -_focused_at.get((d["client"], d["windowId"]), 0.0))
    locations = _locations()
    return [{**d, "location": locations[(d["client"], d["windowId"])]} for d in matches]


def _locations() -> dict[tuple[str, int], str]:
    """Label each (client, window), e.g. "Edge · Work · Window 2".

    The browser/profile part appears only when several clients are connected, and
    the window number only when that client has several windows. Windows are
    numbered by age: Chrome's window ids increase over a session.
    """
    windows: dict[str, list[int]] = {}
    for client, window_id, _ in _tabs:
        ids = windows.setdefault(client, [])
        if window_id not in ids:
            ids.append(window_id)
    labels = {}
    for client, ids in windows.items():
        info = _client_info.get(client, {})
        source = [info.get("browser"), info.get("label")] if len(windows) > 1 else []
        for n, window_id in enumerate(sorted(ids), 1):
            parts = source + ([f"Window {n}"] if len(ids) > 1 else [])
            labels[(client, window_id)] = " · ".join(p for p in parts if p)
    return labels


@app.post("/activate")
async def activate(ref: TabRef):
    event = {"type": "activate", **ref.model_dump()}
    log.info("activate: client=%r windowId=%d tabId=%d", ref.client, ref.windowId, ref.tabId)
    delivered = await _send_to(ref.client, event)
    if not delivered:
        # Owning extension not connected; hold it briefly in case it is reconnecting.
        _activations.append((time.monotonic(), event))
    return {"ok": True, "delivered": delivered}


async def _send_to(client: str, event: dict) -> bool:
    ws = _clients.get(client)
    if ws is None:
        return False
    try:
        await ws.send_json(event)
        return True
    except Exception:
        if _clients.get(client) is ws:
            del _clients[client]
        return False


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket, client: str = ""):
    """Push channel to the browser extension. Only extension origins may connect."""
    origin = ws.headers.get("origin", "")
    if not origin.startswith(("chrome-extension://", "moz-extension://")):
        await ws.close(code=1008)
        return
    await ws.accept()
    _clients[client] = ws
    log.info("extension %r connected (%d total)", client, len(_clients))
    try:
        pending = list(_activations)
        _activations.clear()
        for queued_at, event in pending:
            if time.monotonic() - queued_at > ACTIVATION_TTL:
                continue
            if event["client"] == client:
                await ws.send_json(event)
            else:
                _activations.append((queued_at, event))
        while True:
            # Extension sends periodic pings to keep its service worker alive.
            if await ws.receive_text() == "ping":
                await ws.send_text("pong")
    except WebSocketDisconnect:
        pass
    finally:
        # A reconnect may already have replaced this socket; only clean up our own.
        if _clients.get(client) is ws:
            del _clients[client]
            # Browser closed (or worker died); it does a full sync when it reconnects.
            _forget_client(client)
        log.info("extension %r disconnected (%d total)", client, len(_clients))
