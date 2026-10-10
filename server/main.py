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
    tabId: int
    windowId: int
    title: str = ""
    url: str = ""
    favIconUrl: Optional[str] = None


class SyncRequest(BaseModel):
    tabs: list[Tab]


class UpdateRequest(BaseModel):
    tab: Tab


class TabRef(BaseModel):
    tabId: int
    windowId: int


# (windowId, tabId) -> (tab as dict, lowercased "title\nurl" haystack for search)
_tabs: dict[tuple[int, int], tuple[dict, str]] = {}
# Connected browser extensions.
_clients: set[WebSocket] = set()
# Activations made while no extension was connected: (monotonic time, event).
_activations: deque[tuple[float, dict]] = deque(maxlen=20)
ACTIVATION_TTL = 5.0  # seconds; older queued activations are dropped


def _put(tab: Tab) -> None:
    data = tab.model_dump()
    _tabs[(tab.windowId, tab.tabId)] = (data, f"{tab.title}\n{tab.url}".lower())


@app.post("/sync")
def sync(req: SyncRequest):
    _tabs.clear()
    for tab in req.tabs:
        _put(tab)
    log.info("sync: %d tabs", len(_tabs))
    return {"ok": True, "count": len(_tabs)}


@app.post("/update")
def update(req: UpdateRequest):
    _put(req.tab)
    return {"ok": True}


@app.post("/remove")
def remove(ref: TabRef):
    removed = _tabs.pop((ref.windowId, ref.tabId), None) is not None
    return {"ok": True, "removed": removed}


@app.get("/search")
def search(q: str = ""):
    # Every whitespace-separated term must appear in the title or url.
    terms = q.lower().split()
    if not terms:
        return [data for data, _ in _tabs.values()]
    return [data for data, hay in _tabs.values() if all(t in hay for t in terms)]


@app.post("/activate")
async def activate(ref: TabRef):
    event = {"type": "activate", **ref.model_dump()}
    log.info("activate: windowId=%d tabId=%d", ref.windowId, ref.tabId)
    delivered = await _broadcast(event)
    if not delivered:
        # No extension connected; hold it briefly in case one is reconnecting.
        _activations.append((time.monotonic(), event))
    return {"ok": True, "delivered": delivered}


async def _broadcast(event: dict) -> int:
    delivered = 0
    for ws in list(_clients):
        try:
            await ws.send_json(event)
            delivered += 1
        except Exception:
            _clients.discard(ws)
    return delivered


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    """Push channel to the browser extension. Only extension origins may connect."""
    origin = ws.headers.get("origin", "")
    if not origin.startswith(("chrome-extension://", "moz-extension://")):
        await ws.close(code=1008)
        return
    await ws.accept()
    _clients.add(ws)
    log.info("extension connected (%d total)", len(_clients))
    try:
        while _activations:
            queued_at, event = _activations.popleft()
            if time.monotonic() - queued_at <= ACTIVATION_TTL:
                await ws.send_json(event)
        while True:
            # Extension sends periodic pings to keep its service worker alive.
            if await ws.receive_text() == "ping":
                await ws.send_text("pong")
    except WebSocketDisconnect:
        pass
    finally:
        _clients.discard(ws)
        log.info("extension disconnected (%d total)", len(_clients))
