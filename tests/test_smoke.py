#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Smoke test: the exe starts, hooks the shell, accelerates a real window, and
stays inside its published resource profile.

This is the only test that touches a real Explorer window (a folder that is safe
to open and close), so it proves the event path end to end and not just the UI
text. It closes only the window it opened, stops its own instance and deletes
the log it asked for.

Run:  python tests/test_smoke.py
"""

import sys as _sys

# These suites print Chinese, Japanese and Korean. A Windows console defaults to
# a legacy code page, where print() raises UnicodeEncodeError and the suite fails
# for a reason that has nothing to do with the binary under test.
if hasattr(_sys.stdout, "reconfigure"):
    _sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import ctypes
import os
import subprocess
import sys
import time
from ctypes import wintypes

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
EXE = os.path.join(ROOT, "dist", "ExplorerF11.exe")
LOG = os.path.join(os.environ["TEMP"], "ExplorerF11.log")
TARGET = r"C:\Windows\System32\drivers"

# Published profile (docs/ARCHITECTURE.md): one idle thread, under 2 MB private,
# ~135 handles. The ceilings are generous on purpose - this catches leaks and
# runaway allocation, not a 200 KB regression.
MAX_PRIVATE_MB = 12.0
MAX_HANDLES = 300

results = []


def check(name, got, want):
    ok = got == want
    results.append(ok)
    print(("PASS  " if ok else "FAIL  ") + "%-44s got=%r want=%r" % (name, got, want))


def check_true(name, cond, detail=""):
    check(name + (("  [" + str(detail) + "]") if detail else ""), bool(cond), True)


u = ctypes.windll.user32
u.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
u.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
u.GetWindowLongPtrW.restype = ctypes.c_void_p
u.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]

CB = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
GWL_STYLE = -16
WS_CAPTION = 0x00C00000


def folder_windows():
    out = []

    def cb(h, lp):
        b = ctypes.create_unicode_buffer(64)
        u.GetClassNameW(h, b, 64)
        if b.value == "CabinetWClass":
            t = ctypes.create_unicode_buffer(260)
            u.GetWindowTextW(h, t, 260)
            style = u.GetWindowLongPtrW(h, GWL_STYLE) or 0
            out.append((h, t.value, bool(style & WS_CAPTION)))
        return True

    u.EnumWindows(CB(cb), 0)
    return out


if os.path.exists(LOG):
    os.remove(LOG)

subprocess.run(["taskkill", "/F", "/IM", "ExplorerF11.exe"], capture_output=True)
time.sleep(0.5)
subprocess.Popen([EXE, "--log"], cwd=os.path.dirname(EXE))
time.sleep(1.5)

print("1) 打开资源管理器窗口")
subprocess.Popen("explorer.exe " + TARGET, shell=True)
time.sleep(2.5)
wins = folder_windows()
for h, t, cap in wins:
    print("   hwnd=0x%08X caption=%-5s %r" % (h, cap, t))

print("\n2) 日志")
log = open(LOG, encoding="utf-8-sig").read().strip() if os.path.exists(LOG) else ""
print(log or "<no log>")
check_true("日志已生成", bool(log))
check_true("Shell 钩子注册成功", "started (tab hook ok)" in log)
check_true("确实加速了一个窗口", "accelerated:" in log, log.splitlines()[-1] if log else "")

print("\n3) 资源")
p = subprocess.run(["powershell", "-NoProfile", "-Command",
                    "$p=Get-Process -Name ExplorerF11 -EA SilentlyContinue;"
                    "if($p){'{0}|{1}|{2}' -f "
                    "[math]::Round($p.PrivateMemorySize64/1MB,2),$p.Threads.Count,$p.HandleCount}"],
                   capture_output=True, text=True)
mb, threads, handles = (p.stdout.strip().split("|") + ["", "", ""])[:3]
print("   private=%s MB   threads=%s   handles=%s" % (mb, threads, handles))
check_true("私有内存低于上限", mb and float(mb) < MAX_PRIVATE_MB, mb)
check_true("句柄数低于上限", handles and int(handles) < MAX_HANDLES, handles)
check_true("只有一个空闲线程组", threads and int(threads) <= 8, threads)

# Leave the desktop as we found it: close only the window this test opened,
# stop the instance, drop the log. A test that leaves state behind is a bug.
print("\n4) 收尾")
closed = 0
for h, t, cap in wins:
    cls = ctypes.create_unicode_buffer(64)
    u.GetClassNameW(h, cls, 64)
    if cls.value == "CabinetWClass" and "drivers" in t.lower():
        u.PostMessageW(h, 0x0010, 0, 0)      # WM_CLOSE
        closed += 1
time.sleep(0.8)
print("   关闭测试打开的窗口: %d" % closed)
check("关闭了测试打开的窗口", closed, 1)
subprocess.run(["taskkill", "/F", "/IM", "ExplorerF11.exe"], capture_output=True)
time.sleep(0.3)
if os.path.exists(LOG):
    os.remove(LOG)
print("   结束实例并删除日志")
check_true("日志已删除", not os.path.exists(LOG))

bad = results.count(False)
print("\n%s  %d/%d 通过" % ("ALL PASS" if not bad else "FAILURES",
                            len(results) - bad, len(results)))
sys.exit(1 if bad else 0)
