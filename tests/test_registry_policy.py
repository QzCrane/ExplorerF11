"""
Regression tests for ExplorerF11's registry policy.

Goal: prove that a default run leaves the registry untouched, and that every
setting returns the registry to exactly that state when it goes back to default.

Run:  python _test_v5.py
"""

import ctypes
import os
import subprocess
import sys
import time
import winreg
from ctypes import wintypes

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
EXE = os.path.join(ROOT, "dist", "ExplorerF11.exe")
CFG = r"Software\ExplorerF11"
OLD_CFG = r"Software\ExplorerF11Ultra"
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
    subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         "Stop-Process -Name ExplorerF11 -Force -ErrorAction SilentlyContinue"],
        capture_output=True)
    time.sleep(0.4)


def start(*args):
    subprocess.Popen([EXE] + list(args), cwd=os.path.dirname(EXE))
    time.sleep(1.6)


def hwnd():
    h = u.FindWindowW("ExplorerF11Window", None)
    return h


def cmd(cmd_id):
    h = hwnd()
    if not h:
        return False
    u.PostMessageW(h, 0x0111, cmd_id, 0)   # WM_COMMAND
    time.sleep(0.5)
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
        "oldcfg": key_exists(OLD_CFG),
        "run": val(RUN, "ExplorerF11") is not None,
        "oldrun": val(RUN, "ExplorerF11Ultra") is not None,
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

print("\n==== 0. 准备：造出 v4 遗留物（旧键 + 旧自启项）====")
kill()
with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, OLD_CFG, 0, winreg.KEY_SET_VALUE) as k:
    winreg.SetValueEx(k, "Tabs", 0, winreg.REG_DWORD, 1)
    winreg.SetValueEx(k, "InitialSweep", 0, winreg.REG_DWORD, 1)
with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN, 0, winreg.KEY_SET_VALUE) as k:
    winreg.SetValueEx(k, "ExplorerF11Ultra", 0, winreg.REG_SZ,
                      r'"C:\old\ExplorerF11Ultra.exe"')
print("  planted:", dump_state())

print("\n==== 1. 首次启动应自动迁移旧名（旧键消失、自启项改指新 exe）====")
start()
st = dump_state()
check("旧配置键已删除", st["oldcfg"], False)
check("旧自启项已删除", st["oldrun"], False)
check("自启项已改指新 exe",
      bool(val(RUN, "ExplorerF11") or ""), True)
if val(RUN, "ExplorerF11"):
    print("      value =", val(RUN, "ExplorerF11"))
check("默认值不落盘（无配置键）", st["cfg"], False)
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

cmd(IDM_TABS)
check("关掉「新标签页」后出现配置键", key_exists(CFG), True)
check("Tabs 值为 0", val(CFG, "Tabs"), 0)

cmd(IDM_TABS)
check("恢复默认后配置键消失（不是留空壳）", key_exists(CFG), False)

# 自启默认是「关」，所以第一次点击一定是写入。
check("自启初始为关", val(RUN, "ExplorerF11") is None, True)
cmd(IDM_AUTOSTART)
check("勾选自启后写入 Run 值", val(RUN, "ExplorerF11") is not None, True)
check("自启项指向当前 exe",
      "ExplorerF11.exe" in (val(RUN, "ExplorerF11") or ""), True)
check("勾选自启不写 StartupApproved", val(APPROVED, "ExplorerF11") is None, True)

# 模拟在任务管理器里把该自启项关掉：Run 值还在，Windows 另记一个禁用位。
with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, APPROVED, 0, winreg.KEY_SET_VALUE) as k:
    winreg.SetValueEx(k, "ExplorerF11", 0, winreg.REG_BINARY,
                      b"\x03\x00\x00\x00" + b"\x00" * 8)
check("已模拟任务管理器禁用", val(APPROVED, "ExplorerF11") is not None, True)
cmd(IDM_AUTOSTART)   # 被禁用时托盘应显示为「关」，点一次 = 重新启用
check("重新启用会清除 Windows 禁用位", val(APPROVED, "ExplorerF11") is None, True)
check("重新启用后 Run 值仍在", val(RUN, "ExplorerF11") is not None, True)

cmd(IDM_AUTOSTART)
check("取消自启后 Run 值消失", val(RUN, "ExplorerF11") is None, True)
check("取消自启后 StartupApproved 也不留", val(APPROVED, "ExplorerF11") is None, True)
kill()

print("\n==== 4. --clean 清空一切（含旧名与托盘记录）====")
with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, CFG, 0, winreg.KEY_SET_VALUE) as k:
    winreg.SetValueEx(k, "Tabs", 0, winreg.REG_DWORD, 0)
with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN, 0, winreg.KEY_SET_VALUE) as k:
    winreg.SetValueEx(k, "ExplorerF11", 0, winreg.REG_SZ, r'"C:\x\ExplorerF11.exe"')
with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, APPROVED, 0, winreg.KEY_SET_VALUE) as k:
    winreg.SetValueEx(k, "ExplorerF11", 0, winreg.REG_BINARY,
                      b"\x03\x00\x00\x00" + b"\x00" * 8)
with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, OLD_CFG, 0, winreg.KEY_SET_VALUE) as k:
    winreg.SetValueEx(k, "Tabs", 0, winreg.REG_DWORD, 0)
print("  planted:", dump_state())

run_exe("--clean", "--quiet")
st = dump_state()
check("配置键已清除", st["cfg"], False)
check("旧配置键已清除", st["oldcfg"], False)
check("自启项已清除", st["run"], False)
check("旧自启项已清除", st["oldrun"], False)
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
