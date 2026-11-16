"""
Regression tests for ExplorerF11's registry policy.

Goal: prove that a default run leaves the registry untouched, and that every
setting returns the registry to exactly that state when it goes back to default.

Run:  python _test_v5.py
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
import winreg
from ctypes import wintypes

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "tools"))
import win32util as winutil      # noqa: E402  shared stop/start/wait
EXE = os.path.join(ROOT, "dist", "ExplorerF11.exe")
CFG = r"Software\ExplorerF11"
RUN = r"Software\Microsoft\Windows\CurrentVersion\Run"
APPROVED = r"Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run"
TRAY = r"Control Panel\NotifyIconSettings"

IDM_AUTOSTART = 1005
IDM_TABS = 1007

u = ctypes.windll.user32
u.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
u.FindWindowW.restype = wintypes.HWND
u.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]

results = []


def check(name, got, want):
    ok = got == want
    results.append((ok, name, got, want))
    print(("  PASS  " if ok else "  FAIL  ") + "%-44s got=%r want=%r" % (name, got, want))
    return ok


def kill():
    winutil.terminate()


def start(*args):
    winutil.launch(EXE, args)


def hwnd():
    h = u.FindWindowW("ExplorerF11Window", None)
    return h


def cmd(cmd_id, until=None):
    """Post a menu command, then wait for the state it is supposed to change.

    The old version slept 0.5 s and hoped. The handler writes the registry on
    the app's own thread, so the write is the observable: polling it finishes
    in about a millisecond and cannot fail on a slow machine the way a fixed
    sleep can.
    """
    h = hwnd()
    if not h:
        return False
    u.PostMessageW(h, 0x0111, cmd_id, 0)   # WM_COMMAND
    if until is not None:
        return winutil.wait_until(until, timeout=5.0)
    return True


def run_exe(*args, wait=True):
    p = subprocess.Popen([EXE] + list(args), cwd=os.path.dirname(EXE))
    if wait:
        p.wait(timeout=20)
    return p


def key_exists(path):
    try:
        winreg.OpenKey(winreg.HKEY_CURRENT_USER, path).Close()
        return True
    except OSError:
        return False


def val(path, name):
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path) as k:
            return winreg.QueryValueEx(k, name)[0]
    except OSError:
        return None


def our_tray_entries():
    n = 0
    try:
        root = winreg.OpenKey(winreg.HKEY_CURRENT_USER, TRAY)
    except OSError:
        return 0
    i = 0
    while True:
        try:
            sub = winreg.EnumKey(root, i)
        except OSError:
            break
        i += 1
        try:
            with winreg.OpenKey(root, sub) as sk:
                exe = winreg.QueryValueEx(sk, "ExecutablePath")[0]
            if os.path.basename(exe).lower() == "explorerf11.exe":
                n += 1
        except OSError:
            pass
    root.Close()
    return n


def dump_state():
    return {
        "cfg": key_exists(CFG),
        "run": val(RUN, "ExplorerF11") is not None,
        "approved": val(APPROVED, "ExplorerF11") is not None,
        "tray": our_tray_entries(),
    }


# Remember the caller's real state: the tests below destroy it on purpose, and
# a test suite must not silently turn the user's autostart off.
ORIG_RUN = val(RUN, "ExplorerF11")
ORIG_CFG = {}
try:
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, CFG) as k:
        i = 0
        while True:
            try:
                n, v, t = winreg.EnumValue(k, i)
            except OSError:
                break
            ORIG_CFG[n] = (v, t)
            i += 1
except OSError:
    pass

print("\n==== 0. 准备：从干净状态开始 ====")
kill()
run_exe("--clean", "--quiet")
before = dump_state()
print("      baseline:", before)

print("\n==== 1. 默认启动：注册表零写入 ====")
start()
st = dump_state()
check("默认值不落盘（无配置键）", st["cfg"], False)
check("不写自启项", st["run"], False)
check("启动后状态与启动前一致", st, before)
kill()

print("\n==== 2. 默认启动：注册表零写入 ====")
kill()
run_exe("--clean", "--quiet")          # 从干净状态开始，否则上一步迁移出的自启项还在
before = dump_state()
print("      baseline:", before)
start()
st = dump_state()
check("配置键未创建", st["cfg"], False)
check("自启项未创建", st["run"], False)
check("状态与启动前完全一致", st, before)
print("      tray 记录数 =", st["tray"])
kill()

print("\n==== 3. 设置偏离默认 -> 写入；回到默认 -> 自动清除 ====")
kill()
run_exe("--clean", "--quiet")
start()
check("能定位到隐藏窗口", bool(hwnd()), True)

cmd(IDM_TABS, until=lambda: key_exists(CFG))
check("关掉「新建选项卡时重新加速窗口」后出现配置键", key_exists(CFG), True)
check("Tabs 值为 0", val(CFG, "Tabs"), 0)

cmd(IDM_TABS, until=lambda: not key_exists(CFG))
check("恢复默认后配置键消失（不是留空壳）", key_exists(CFG), False)

# 自启默认是「关」，所以第一次点击一定是写入。
check("自启初始为关", val(RUN, "ExplorerF11") is None, True)
cmd(IDM_AUTOSTART, until=lambda: val(RUN, "ExplorerF11") is not None)
check("勾选自启后写入 Run 值", val(RUN, "ExplorerF11") is not None, True)
check("自启项指向当前 exe",
      "ExplorerF11.exe" in (val(RUN, "ExplorerF11") or ""), True)
check("勾选自启不写 StartupApproved", val(APPROVED, "ExplorerF11") is None, True)

# 模拟在任务管理器里把该自启项关掉：Run 值还在，Windows 另记一个禁用位。
with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, APPROVED, 0, winreg.KEY_SET_VALUE) as k:
    winreg.SetValueEx(k, "ExplorerF11", 0, winreg.REG_BINARY,
                      b"\x03\x00\x00\x00" + b"\x00" * 8)
check("已模拟任务管理器禁用", val(APPROVED, "ExplorerF11") is not None, True)
# 被禁用时托盘应显示为「关」，点一次 = 重新启用
cmd(IDM_AUTOSTART, until=lambda: val(APPROVED, "ExplorerF11") is None)
check("重新启用会清除 Windows 禁用位", val(APPROVED, "ExplorerF11") is None, True)
check("重新启用后 Run 值仍在", val(RUN, "ExplorerF11") is not None, True)

cmd(IDM_AUTOSTART, until=lambda: val(RUN, "ExplorerF11") is None)
check("取消自启后 Run 值消失", val(RUN, "ExplorerF11") is None, True)
check("取消自启后 StartupApproved 也不留", val(APPROVED, "ExplorerF11") is None, True)
kill()

print("\n==== 4. --clean 清空一切（含托盘记录）====")
with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, CFG, 0, winreg.KEY_SET_VALUE) as k:
    winreg.SetValueEx(k, "Tabs", 0, winreg.REG_DWORD, 0)
with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN, 0, winreg.KEY_SET_VALUE) as k:
    winreg.SetValueEx(k, "ExplorerF11", 0, winreg.REG_SZ, r'"C:\x\ExplorerF11.exe"')
with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, APPROVED, 0, winreg.KEY_SET_VALUE) as k:
    winreg.SetValueEx(k, "ExplorerF11", 0, winreg.REG_BINARY,
                      b"\x03\x00\x00\x00" + b"\x00" * 8)

run_exe("--clean", "--quiet")
st = dump_state()
check("配置键已清除", st["cfg"], False)
check("自启项已清除", st["run"], False)
check("启动开关记录已清除", st["approved"], False)
check("托盘图标记录已清除", st["tray"], 0)

print("\n==== 5. 清理后再启动仍为零写入 ====")
start()
st = dump_state()
check("仍然没有配置键", st["cfg"], False)
check("仍然没有自启项", st["run"], False)
check("仍然没有启动开关记录", st["approved"], False)
kill()

print("\n==== 6. 还原测试前状态 ====")
with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, RUN, 0, winreg.KEY_SET_VALUE) as k:
    if ORIG_RUN is None:
        try:
            winreg.DeleteValue(k, "ExplorerF11")
        except OSError:
            pass
    else:
        winreg.SetValueEx(k, "ExplorerF11", 0, winreg.REG_SZ, ORIG_RUN)
if ORIG_CFG:
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, CFG, 0, winreg.KEY_SET_VALUE) as k:
        for name, (v, t) in ORIG_CFG.items():
            winreg.SetValueEx(k, name, 0, t, v)
check("自启项已还原", val(RUN, "ExplorerF11"), ORIG_RUN)
check("配置键已还原", bool(ORIG_CFG), key_exists(CFG))

bad = [r for r in results if not r[0]]
print("\n%s  %d/%d 通过" % ("ALL PASS" if not bad else "FAILURES", len(results) - len(bad), len(results)))
sys.exit(1 if bad else 0)
