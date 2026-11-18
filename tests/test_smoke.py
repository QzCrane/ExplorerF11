#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Smoke test: the exe starts, hooks the shell, and keeps its window count
honest while windows come and go, across an explorer restart.

Everything asserted here is observed from outside the process: the log the
binary writes, the report window it draws, the handles the kernel reports. The
suite never reads src/, and never takes the binary's word for its own state.

The three behaviours it exists for, each of which had no external test before:

  * `--no-initial` skips the start-up sweep *and* leaves the stored setting
    alone. Observable because the sweep writes a log line of its own, and the
    report shows the mark count: with the flag there is no `initial sweep:` line
    and the count does not move; without it, `N applied` and the count goes up
    by the window this suite opened.
  * the marked-window set stays equal to the desktop while windows open and
    close. A set that is never re-enumerated can only be trusted if it is
    maintained, so the count must follow a second window up and back down, read
    from the already-open report - which also proves the report refreshes.
  * a `TaskbarCreated` broadcast (what explorer sends when it restarts) is
    survived: same pid, same window, hook re-registered, and shell events still
    arrive afterwards.

Counts are always compared as deltas against a baseline taken in the same run:
window marks live on the windows themselves and outlive the process, so a
machine that has been using the tool normally already has some.

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
import re
import subprocess
import sys
import time
from ctypes import wintypes


HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "tools"))
import win32util as winutil      # noqa: E402  shared stop/start/wait
EXE = os.path.join(ROOT, "dist", "ExplorerF11.exe")
LOG = os.path.join(os.environ["TEMP"], "ExplorerF11.log")
TARGET = os.environ.get("SYSTEMDRIVE", "C:") + r"\Windows\System32\drivers"
TARGET2 = os.path.join(ROOT, "docs")

# Published profile (docs/ARCHITECTURE.md): one idle thread, 1.76 MB private,
# 129 handles. The ceilings are generous on purpose - this catches leaks and
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
u.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
u.FindWindowW.restype = wintypes.HWND
u.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
u.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
u.SendMessageW.restype = ctypes.c_ssize_t
u.GetDlgItem.argtypes = [wintypes.HWND, ctypes.c_int]
u.GetDlgItem.restype = wintypes.HWND
u.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
u.RegisterWindowMessageW.argtypes = [wintypes.LPCWSTR]
u.RegisterWindowMessageW.restype = wintypes.UINT
u.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR,
                              wintypes.DWORD, ctypes.c_int, ctypes.c_int,
                              ctypes.c_int, ctypes.c_int, wintypes.HWND,
                              wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID]
u.CreateWindowExW.restype = wintypes.HWND
u.RegisterClassW.argtypes = [ctypes.c_void_p]
u.RegisterClassW.restype = wintypes.ATOM
u.SetPropW.argtypes = [wintypes.HWND, wintypes.LPCWSTR, wintypes.HANDLE]
u.DestroyWindow.argtypes = [wintypes.HWND]

CB = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)


_probe_wndproc = None   # module-level: a registered WNDCLASS keeps a raw pointer


class WNDCLASS(ctypes.Structure):
    _fields_ = [("style", wintypes.UINT), ("lpfnWndProc", ctypes.c_void_p),
                ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int),
                ("hInstance", wintypes.HINSTANCE), ("hIcon", wintypes.HICON),
                ("hCursor", wintypes.HANDLE), ("hbrBackground", wintypes.HANDLE),
                ("lpszMenuName", wintypes.LPCWSTR), ("lpszClassName", wintypes.LPCWSTR)]


def make_tab_probe(n=2):
    """A marked CabinetWClass frame with n ShellTabWindowClass tab children.

    Built before the app starts: the app's marked set is seeded from a desktop
    walk on first read, so a window marked afterwards would never be counted.
    Writing the two properties the tray writes avoids posting F11 to a real
    window; the tab children are what MarkedWindows() counts in brackets.
    """
    k32 = ctypes.windll.kernel32
    k32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
    k32.GetModuleHandleW.restype = wintypes.HINSTANCE
    u.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT,
                                 wintypes.WPARAM, wintypes.LPARAM]
    u.DefWindowProcW.restype = ctypes.c_ssize_t
    global _probe_wndproc
    if _probe_wndproc is None:
        proto = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT,
                                   wintypes.WPARAM, wintypes.LPARAM)

        def wnd_proc(h, m, wp, lp):
            return u.DefWindowProcW(h, m, wp, lp)

        # A registered window class stores the raw function pointer, not a
        # PyObject reference. Keeping the callback only in a local lets the GC
        # reclaim it on return; DestroyWindow then jumps to a freed thunk and
        # takes the whole test process down with STATUS_FATAL_USER_CALLBACK.
        _probe_wndproc = proto(wnd_proc)
    for cls in ("CabinetWClass", "ShellTabWindowClass"):
        wc = WNDCLASS()
        wc.lpfnWndProc = ctypes.cast(_probe_wndproc, ctypes.c_void_p)
        wc.hInstance = k32.GetModuleHandleW(None)
        wc.lpszClassName = cls
        u.RegisterClassW(ctypes.byref(wc))

    parent = u.CreateWindowExW(0, "CabinetWClass", "tab-refresh-probe", 0,
                               0, 0, 10, 10, None, None, None, None)
    children = []
    for i in range(n):
        children.append(u.CreateWindowExW(0, "ShellTabWindowClass", "tab",
                                          0x40000000, 0, 0, 5, 5,
                                          parent, None, None, None))
    u.SetPropW(parent, "ExplorerF11.Marked", 1)
    u.SetPropW(parent, "ExplorerF11.Tick", 1)
    return parent, children
GWL_STYLE = -16
WS_CAPTION = 0x00C00000
IDM_STATUS = 1010
WM_COMMAND = 0x0111
WM_GETTEXT = 0x000D
WM_CLOSE = 0x0010
WM_GETICON = 0x007F
ICON_SMALL, ICON_BIG = 0, 1


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


def open_folder(path, timeout=25.0):
    """Open a folder in a window of its own; return its hwnd.

    /n forces a new window: without it Windows 11 may add a tab to an existing
    one, and a tab is exactly what this suite must not mistake for a window.
    The window has to be visible and restored before it counts - the tool skips
    iconic windows, and a window caught mid-creation would make the sweep look
    like it did nothing.
    """
    before = {h for h, _t, _c in folder_windows()}
    subprocess.Popen('explorer.exe /n,"%s"' % path, shell=True)
    found = {}

    def appeared():
        for h, t, _c in folder_windows():
            if h not in before and u.IsWindowVisible(h) and not u.IsIconic(h):
                found["h"] = h
                return True
        return False

    winutil.wait_until(appeared, timeout=timeout)
    return found.get("h")


def close_window(h, timeout=10.0):
    u.PostMessageW(h, WM_CLOSE, 0, 0)
    winutil.wait_until(lambda: not u.IsWindow(h), timeout=timeout)


def read_log():
    if not os.path.exists(LOG):
        return ""
    try:
        return open(LOG, encoding="utf-8-sig").read()
    except OSError:                 # the app appends while we read
        return ""


def hidden_of(pid):
    """This process's hidden window. A dying instance can still answer
    FindWindow for a moment, and a message posted to it is lost."""
    h = u.FindWindowW("ExplorerF11Window", None)
    if not h:
        return 0
    got = wintypes.DWORD()
    u.GetWindowThreadProcessId(h, ctypes.byref(got))
    return h if got.value == pid else 0


def open_report(app, timeout=10.0):
    """Ask the instance for its report window; return the hwnd, or 0.

    The command is posted again on each poll until the window shows up, so a
    message that lands during start-up is not a failure.
    """
    state = {"h": 0, "posted": 0.0}

    def up():
        state["h"] = u.FindWindowW("ExplorerF11StatusWindow", None)
        if state["h"]:
            return True
        now = time.time()
        h = hidden_of(app.pid)
        if h and now - state["posted"] > 0.2:
            u.PostMessageW(h, WM_COMMAND, IDM_STATUS, 0)
            state["posted"] = now
        return False

    winutil.wait_until(up, timeout=timeout, interval=0.02)
    return state["h"]


def report_body(win):
    edit = u.GetDlgItem(win, 2001) if win else 0
    if not edit:
        return ""
    buf = ctypes.create_unicode_buffer(65536)
    u.SendMessageW(edit, WM_GETTEXT, 65536, ctypes.cast(buf, ctypes.c_void_p).value)
    return buf.value


def marked_windows(win):
    """Window count from the report's own row; 0 when the row reads absent."""
    m = re.search(r"what:\s+(\d+) windows? accelerated", report_body(win))
    return int(m.group(1)) if m else 0


def marked_tabs(win):
    """Tab count in brackets on the report's window-marks row; 0 when absent."""
    m = re.search(r"what:\s+\d+ windows? accelerated \((\d+) tabs?\)", report_body(win))
    return int(m.group(1)) if m else 0


def wait_tabs(win, want, timeout=10.0):
    state = {"n": -1}

    def hit():
        state["n"] = marked_tabs(win)
        return state["n"] == want

    winutil.wait_until(hit, timeout=timeout)
    return state["n"]


def wait_marks(win, want, timeout=10.0):
    state = {"n": -1}

    def hit():
        state["n"] = marked_windows(win)
        return state["n"] == want

    winutil.wait_until(hit, timeout=timeout)
    return state["n"]


def menu_row(fragment):
    env = dict(os.environ, EXPLORERF11_LANG="en")
    p = subprocess.run([EXE, "--menu"], capture_output=True, env=env, timeout=20)
    out = p.stdout.decode("utf-8", "replace")
    return next((l for l in out.splitlines() if fragment in l), "")


u.GetPropW.argtypes = [wintypes.HWND, wintypes.LPCWSTR]
u.GetPropW.restype = wintypes.HANDLE


def marked(h):
    """Is this window accelerated? The mark is a window property, which is where
    the tool says it keeps it and what the report reads; asking the window
    itself is the one answer that does not go through the tool's own accounting."""
    return bool(u.GetPropW(h, "ExplorerF11.Marked"))


def sweep_count():
    m = re.search(r"initial sweep: (\d+) applied", read_log())
    return int(m.group(1)) if m else -1


if os.path.exists(LOG):
    os.remove(LOG)

print("1) 先开一个文件夹窗口（下面几节都要用它）")
winutil.terminate()
w1 = open_folder(TARGET)
check_true("已打开一个可见的资源管理器窗口", bool(w1), "0x%08X" % (w1 or 0))
tick_before = menu_row("Start with Windows")
check_true("菜单里有自启行", bool(tick_before), tick_before)

print("\n2) --no-initial：不扫桌面，也不改持久设置")
winutil.terminate()
if os.path.exists(LOG):
    os.remove(LOG)
app = winutil.launch(EXE, ["--log", "--no-initial", "--lang", "en"])
winutil.wait_until(lambda: "started (" in read_log(), timeout=20)
# No settle needed: the sweep is posted from WM_CREATE and runs before the
# message loop returns to idle, and WaitForInputIdle inside launch() waits for
# exactly that. If it had run, "initial sweep:" would already be in the log.
log = read_log()
check_true("已注册 shell 钩子", "started (tab hook ok)" in log, log.strip()[:60])
check("没有扫桌面（无 initial sweep 行）", sweep_count(), -1)
report = open_report(app)
check_true("报告窗口已打开", bool(report), "0x%08X" % (report or 0))
base = marked_windows(report)
print("   baseline marked windows = %d" % base)
check_true("--no-initial 没有标记已开的窗口", not marked(w1))
check_true("启动开关的勾选未被本次运行改动", menu_row("Start with Windows") == tick_before,
           "%r -> %r" % (tick_before, menu_row("Start with Windows")))
# The report window carries the product icon; the shell keeps what WM_SETICON
# put there, so this is the only external proof that both sizes were set.
check_true("报告窗口的大图标已设置",
           bool(u.SendMessageW(report, WM_GETICON, ICON_BIG, 0)))
check_true("报告窗口的小图标已设置",
           bool(u.SendMessageW(report, WM_GETICON, ICON_SMALL, 0)))
winutil.terminate()

print("\n3) 默认启动：扫桌面，把已开的窗口也加速")
if os.path.exists(LOG):
    os.remove(LOG)
app = winutil.launch(EXE, ["--log", "--lang", "en"])
winutil.wait_until(lambda: "initial sweep:" in read_log(), timeout=20)
check_true("日志已生成", bool(read_log()))
check_true("扫描确实执行且至少命中 1 个窗口", sweep_count() >= 1,
           "applied=%d" % sweep_count())
report = open_report(app)
check_true("报告窗口已打开", bool(report), "0x%08X" % (report or 0))
check_true("扫描把已开的窗口标记了", marked(w1))
check("计数比基线多 1（本次打开的窗口被标记）", wait_marks(report, base + 1), base + 1)

print("\n4) 窗口开关时计数跟随（集合被维护，而不是每次重枚举）")
w2 = open_folder(TARGET2)
check_true("已打开第二个窗口", bool(w2), "0x%08X" % (w2 or 0))
check("再开一个 -> 计数 +1", wait_marks(report, base + 2), base + 2)
close_window(w2)
check("关掉一个 -> 计数 -1", wait_marks(report, base + 1), base + 1)
check_true("还是同一份报告（没有换窗口）", bool(u.IsWindow(report)))

print("\n5) explorer 重启：钩子重注册，事件仍然到达")
pid_before = app.pid
msg = u.RegisterWindowMessageW("TaskbarCreated")
check_true("TaskbarCreated 已注册", msg != 0, msg)
winutil.wait_until(lambda: hidden_of(pid_before) != 0, timeout=5)
u.PostMessageW(hidden_of(pid_before), msg, 0, 0)
winutil.wait_until(lambda: "shell hook re-registered" in read_log(), timeout=10)
check_true("钩子已重注册", "shell hook re-registered" in read_log())
check("进程号未变（没有自我重启）", app.pid, pid_before)
check_true("隐藏窗口仍存活", bool(hidden_of(pid_before)))
w3 = open_folder(TARGET)
check_true("重启后仍加速新窗口", bool(w3), "0x%08X" % (w3 or 0))
check("重启后计数仍跟随（+1）", wait_marks(report, base + 2), base + 2)
close_window(w3)
check("关闭后回到基线 +1", wait_marks(report, base + 1), base + 1)

print("\n6) 收尾：先关掉本节打开的窗口")
if report and u.IsWindow(report):
    u.PostMessageW(report, WM_CLOSE, 0, 0)
    winutil.wait_until(lambda: not u.IsWindow(report), timeout=5)
if w1:
    close_window(w1)
check_true("测试打开的窗口已关闭", not any(u.IsWindow(h) for h in (w1, w2, w3) if h))

print("\n7) 资源（空闲托盘进程，与文档里的画像同一状态）")
# The published profile - 1.77 MB, 129 handles - describes the idle tray
# process. The instance this suite exercised has opened a report window and
# three folder windows, and its private commit keeps ~0.5 MB of that after the
# windows close (freed to the heap, still committed), so measuring it would
# describe a state the numbers were never about. A fresh process is launched for
# this, measured, and stopped again.
winutil.terminate()
idle = winutil.launch(EXE)
winutil.wait_until(lambda: hidden_of(idle.pid) != 0, timeout=10)
# Wait for the number to stop moving rather than for a stopwatch: start-up work
# is posted, so the first samples still include the sweep's allocations.
seen = {"last": -1.0, "still": 0}


def stable():
    cur = winutil.stats(idle.pid)[0]
    seen["still"] = seen["still"] + 1 if abs(cur - seen["last"]) < 0.01 else 0
    seen["last"] = cur
    return seen["still"] >= 4


winutil.wait_until(stable, timeout=6.0, interval=0.05)
private_mb, threads, handles = winutil.stats(idle.pid)
mb = "%.2f" % private_mb
print("   private=%s MB   threads=%d   handles=%d" % (mb, threads, handles))
check_true("私有内存低于上限", private_mb < MAX_PRIVATE_MB, mb)
check_true("句柄数低于上限", handles < MAX_HANDLES, handles)
check_true("只有一个空闲线程组", threads <= 8, threads)

winutil.terminate()
if os.path.exists(LOG):
    os.remove(LOG)
check_true("日志已删除", not os.path.exists(LOG))

print("\n8) 关掉标签页：浮窗与菜单共用的状态必须跟随 tab 数下降")
# The tray tooltip is a shell-owned surface with no read-back, but it is pushed
# by OnStateChanged from the same WindowMarks snapshot the report renders. So
# the report's bracketed tab count is an observable proxy for that push: if a
# closed tab leaves it stale, the tooltip is stale too and the menu - rebuilt
# on every open - disagrees with both.
# A synthetic marked frame with two tabs is created BEFORE the app starts, so
# the first MarkedWindows() seed picks it up. Destroy one tab child: that fires
# EVENT_OBJECT_DESTROY (no shell-hook message, the frame stays alive), and only
# the DESTROY branch of WinEventProc can make the count drop.
probe, probe_tabs = make_tab_probe(2)
check("合成窗口有两个 tab 子窗口", len(probe_tabs), 2)
app = winutil.launch(EXE, ["--log", "--lang", "en"])
winutil.wait_until(lambda: "started (" in read_log(), timeout=20)
report = open_report(app)
check_true("报告窗口已打开（tab 刷新测试）", bool(report), "0x%08X" % (report or 0))
base_tabs = marked_tabs(report)
print("   baseline tabs = %d" % base_tabs)
check_true("合成窗口的两个 tab 已计入", base_tabs >= 2, str(base_tabs))
u.DestroyWindow(probe_tabs[1])
check("关掉一个 tab -> 报告 tab 数 -1", wait_tabs(report, base_tabs - 1), base_tabs - 1)
u.DestroyWindow(probe)
winutil.terminate()

bad = results.count(False)
print("\n%s  %d/%d 通过" % ("ALL PASS" if not bad else "FAILURES",
                            len(results) - bad, len(results)))
sys.exit(1 if bad else 0)
