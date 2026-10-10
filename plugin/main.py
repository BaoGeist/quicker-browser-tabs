import json
import os
import sys
import urllib.parse
import urllib.request

# Flow Launcher plugins ship their dependencies in ./lib (pip install -r requirements.txt -t lib).
PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [PLUGIN_DIR, os.path.join(PLUGIN_DIR, "lib")]

from flowlauncher import FlowLauncher  # noqa: E402

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


class FastBrowserTabs(FlowLauncher):
    def query(self, param):
        try:
            tabs = _get("/search?q=" + urllib.parse.quote(param.strip()))
        except OSError:
            # With a global (*) keyword this runs on every search, so only
            # show the warning when the keyword is typed on its own.
            if param.strip():
                return []
            return [{
                "Title": "Local tab server not running on port 8765",
                "SubTitle": "Start it with: uvicorn main:app --port 8765",
                "IcoPath": ICON,
            }]

        return [
            {
                "Title": tab.get("title") or tab.get("url", ""),
                "SubTitle": tab.get("url", ""),
                "IcoPath": ICON,
                "JsonRPCAction": {
                    "method": "activate_tab",
                    "parameters": [tab["tabId"], tab["windowId"]],
                },
            }
            for tab in tabs
        ]

    def activate_tab(self, tabId, windowId):
        try:
            _post("/activate", {"tabId": tabId, "windowId": windowId})
        except OSError:
            pass


if __name__ == "__main__":
    FastBrowserTabs()
