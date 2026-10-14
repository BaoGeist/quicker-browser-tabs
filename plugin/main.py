"""Fast Browser Tabs: Flow Launcher plugin (JSON-RPC v2, "Language": "Python_v2").

Flow starts this process once and keeps it running, exchanging newline-delimited
JSON-RPC 2.0 messages over stdin/stdout. Anything written to stderr is shown as a
plugin error, and a crashed process is not restarted, so every handler is guarded.
"""

import json
import os
import sys
import urllib.parse
import urllib.request

PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PLUGIN_DIR)

from focus import focus_browser_window  # noqa: E402

SERVER = "http://127.0.0.1:8765"
TIMEOUT = 0.4  # seconds
ICON = "Images/app.png"


def _get(path):
    with urllib.request.urlopen(SERVER + path, timeout=TIMEOUT) as resp:
        return json.load(resp)


def _post(path, payload):
    req = urllib.request.Request(
        SERVER + path,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return json.load(resp)


def query(q, settings=None):
    search = q.get("search", "")
    try:
        tabs = _get("/search?q=" + urllib.parse.quote(search.strip()))
    except OSError:
        # Under the global (*) keyword this runs on every search; stay quiet there.
        if q.get("actionKeyword", "*") == "*":
            return {"result": []}
        return {"result": [{
            "title": "Local tab server not running on port 8765",
            "subTitle": "Start it with: uvicorn main:app --port 8765",
            "icoPath": ICON,
        }]}

    return {"result": [
        {
            "title": tab.get("title") or tab.get("url", ""),
            "subTitle": tab.get("url", ""),
            "icoPath": ICON,
            "jsonRPCAction": {
                "method": "activate_tab",
                "parameters": [tab["tabId"], tab["windowId"], tab.get("title", ""), tab.get("client", "")],
            },
        }
        for tab in tabs
    ]}


def activate_tab(*args):
    # Flow passes the result's "parameters" list as a single argument
    # (optionally followed by settings), not spread out.
    if args and isinstance(args[0], list):
        args = args[0]
    tab_id, window_id, title, client = (list(args) + ["", ""])[:4]
    try:
        _post("/activate", {"client": client, "tabId": tab_id, "windowId": window_id})
    except OSError:
        return {"hide": True}
    # Chrome can't raise its own window past Windows' foreground lock.
    focus_browser_window(title)
    return {"hide": True}


HANDLERS = {
    "initialize": lambda context: {},
    "query": query,
    "activate_tab": activate_tab,
}


def _send(out, message):
    out.write(json.dumps(message).encode() + b"\n")
    out.flush()


def main():
    stdin, stdout = sys.stdin.buffer, sys.stdout.buffer
    # Stray warnings on stderr would surface as plugin errors.
    sys.stderr = open(os.devnull, "w")

    for line in stdin:
        try:
            message = json.loads(line)
        except ValueError:
            continue
        if "id" not in message:
            continue  # notifications, e.g. $/cancelRequest
        method = message.get("method")
        if method == "close":
            _send(stdout, {"jsonrpc": "2.0", "id": message["id"], "result": None})
            return

        handler = HANDLERS.get(method)
        if handler is None:
            error = {"code": -32601, "message": f"Method not found: {method}"}
            _send(stdout, {"jsonrpc": "2.0", "id": message["id"], "error": error})
            continue
        try:
            result = handler(*message.get("params", []))
            _send(stdout, {"jsonrpc": "2.0", "id": message["id"], "result": result})
        except Exception as exc:
            error = {"code": -32603, "message": repr(exc)}
            _send(stdout, {"jsonrpc": "2.0", "id": message["id"], "error": error})


if __name__ == "__main__":
    main()
