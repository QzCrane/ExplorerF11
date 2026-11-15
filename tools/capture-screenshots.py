#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Regenerate the documentation screenshots from the real UI.

The images in docs/images are captures of the running binary, not mockups: this
script starts the exe, asks it to open its own surfaces through the same messages
the tray icon sends, grabs the exact window rectangles, and writes PNGs. Run it
after any change to the menu or the report, so the documentation cannot show a
build that no longer exists.

    python tools/capture-screenshots.py [zh|en]

Requires Pillow. Windows only (it drives real windows).
"""

import ctypes
import os
import subprocess
import sys
import time
from ctypes import wintypes

from PIL import ImageGrab

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
EXE = os.path.join(ROOT, "dist", "ExplorerF11.exe")
OUT = os.path.join(ROOT, "docs", "images")

LANG = sys.argv[1] if len(sys.argv) > 1 else "zh"
SUFFIX = ".zh-CN" if LANG == "zh" else ".en"
MARGIN = 0                       # exact window rect: never photograph what is behind
MENU_MARGIN = 0

IDM_STATUS = 1010
TRAY_ID = 1001
WM_COMMAND = 0x0111
WM_TRAYICON = 0x0401             # WM_USER + 1 in main.cpp
WM_RBUTTONUP = 0x0205
WM_CLOSE = 0x0010
VK_ESCAPE = 0x1B

u = ctypes.windll.user32
u.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
u.FindWindowW.restype = wintypes.HWND
u.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
u.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
u.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
u.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                           ctypes.c_int, ctypes.c_int, ctypes.c_uint]

SWP_NOMOVE = 0x0002
SWP_NOSIZE = 0x0001
HWND_TOPMOST = wintypes.HWND(-1)
HWND_NOTOPMOST = wintypes.HWND(-2)

# Without this the process is DPI-unaware and every rectangle comes back scaled.
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)   # per-monitor aware
except OSError:
    pass


def raise_window(hwnd):
    """Screen captures show whatever is on top, so force the window up first."""
    u.ShowWindow(hwnd, 9)                                   # SW_RESTORE
    u.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE)
    u.SetForegroundWindow(hwnd)
    time.sleep(0.45)


def visible_rect(hwnd):
    """The window as the eye sees it.

    GetWindowRect includes the invisible resize border DWM reserves for the drop
    shadow (about 8 px on each side), and a screen grab of that rectangle picks up
    whatever is behind it. DWMWA_EXTENDED_FRAME_BOUNDS excludes that border.
    """
    r = wintypes.RECT()
    if ctypes.windll.dwmapi.DwmGetWindowAttribute(
            hwnd, 9, ctypes.byref(r), ctypes.sizeof(r)) == 0 and r.right > r.left:
        return r
    if not u.GetWindowRect(hwnd, ctypes.byref(r)):
        raise SystemExit("GetWindowRect failed for %r" % hwnd)
    return r


def grab(hwnd, path, margin=MARGIN):
    r = visible_rect(hwnd)
    box = (r.left - margin, r.top - margin, r.right + margin, r.bottom + margin)
    img = ImageGrab.grab(bbox=box, all_screens=True)
    img.save(path)
    print("  %-46s %dx%d" % (os.path.relpath(path, ROOT), img.width, img.height))


def wait_window(cls, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        h = u.FindWindowW(cls, None)
        if h:
            return h
        time.sleep(0.05)
    return None


def main():
    if not os.path.exists(EXE):
        raise SystemExit("build first: %s is missing" % EXE)
    os.makedirs(OUT, exist_ok=True)
    subprocess.run(["taskkill", "/F", "/IM", "ExplorerF11.exe"], capture_output=True)
    time.sleep(0.6)
    # TEMP is overridden so the report prints a neutral log path instead of the
    # account name of whoever took the screenshot.
    env = dict(os.environ, TEMP=r"C:\Temp", TMP=r"C:\Temp")
    subprocess.Popen([EXE, "--lang", LANG], cwd=os.path.dirname(EXE), env=env)
    time.sleep(1.6)

    hidden = u.FindWindowW("ExplorerF11Window", None)
    if not hidden:
        raise SystemExit("the tool did not start")

    print("report window")
    u.PostMessageW(hidden, WM_COMMAND, IDM_STATUS, 0)
    report = wait_window("ExplorerF11StatusWindow")
    if not report:
        raise SystemExit("report window did not open")
    time.sleep(0.7)                      # let the edit control paint the body
    raise_window(report)
    grab(report, os.path.join(OUT, "footprint-report" + SUFFIX + ".png"))
    u.SetWindowPos(report, HWND_NOTOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE)
    u.PostMessageW(report, WM_CLOSE, 0, 0)
    time.sleep(0.4)

    print("tray menu")
    u.SetCursorPos(520, 240)             # room below and to the right of the menu
    u.PostMessageW(hidden, WM_TRAYICON, TRAY_ID, WM_RBUTTONUP)
    menu = wait_window("#32768")         # the class Windows uses for popup menus
    if not menu:
        raise SystemExit("the menu window did not appear")
    time.sleep(0.5)
    grab(menu, os.path.join(OUT, "tray-menu" + SUFFIX + ".png"), MENU_MARGIN)
    u.keybd_event(VK_ESCAPE, 0, 0, 0)    # dismiss; TrackPopupMenu is waiting for it
    u.keybd_event(VK_ESCAPE, 0, 2, 0)
    time.sleep(0.3)
    subprocess.run(["taskkill", "/F", "/IM", "ExplorerF11.exe"], capture_output=True)


if __name__ == "__main__":
    main()
