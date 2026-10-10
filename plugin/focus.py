"""Bring a browser window to the foreground on Windows.

The extension can activate a tab, but Windows' foreground lock stops Chrome
from raising its own window when another app (e.g. a terminal) is in front.
So after the tab is activated, we find the browser window by its title
("<tab title> - Google Chrome") and raise it from here.
"""

import sys
import time

BROWSER_WINDOW_CLASS = "Chrome_WidgetWin_1"  # Chrome, Edge, Brave, Vivaldi


def focus_browser_window(tab_title, timeout=1.0):
    """Wait for a browser window whose title starts with tab_title, then raise it."""
    if sys.platform != "win32" or not tab_title:
        return False
    deadline = time.monotonic() + timeout
    while True:
        hwnd = _find_window(tab_title)
        if hwnd:
            _raise(hwnd)
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.03)


if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    _EnumProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    SW_RESTORE = 9
    VK_MENU = 0x12
    KEYEVENTF_KEYUP = 0x2

    def _text(hwnd, getter, size=512):
        buf = ctypes.create_unicode_buffer(size)
        getter(hwnd, buf, size)
        return buf.value

    def _find_window(tab_title):
        found = []

        def visit(hwnd, _):
            if (
                user32.IsWindowVisible(hwnd)
                and _text(hwnd, user32.GetClassNameW) == BROWSER_WINDOW_CLASS
                and _text(hwnd, user32.GetWindowTextW).startswith(tab_title)
            ):
                found.append(hwnd)
                return False
            return True

        user32.EnumWindows(_EnumProc(visit), 0)
        return found[0] if found else None

    def _raise(hwnd):
        if user32.IsIconic(hwnd):
            user32.ShowWindow(hwnd, SW_RESTORE)
        # A synthetic Alt tap counts as user input, which lifts the
        # foreground lock so SetForegroundWindow is honored.
        user32.keybd_event(VK_MENU, 0, 0, 0)
        user32.keybd_event(VK_MENU, 0, KEYEVENTF_KEYUP, 0)
        user32.SetForegroundWindow(hwnd)
