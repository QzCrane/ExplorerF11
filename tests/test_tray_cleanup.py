#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""--clean must be surgical: remove our tray bookkeeping, keep everyone else's.

A blunt "delete the whole NotifyIconSettings key" would silently destroy the
user's own icon preferences for other programs, so this plants one entry that
looks like ours and one that does not, runs --clean, and checks the survivor.

The suite restores the caller's Run value and settings afterwards, because
--clean really does remove them.

Run:  python tests/test_tray_cleanup.py
"""

import os
import subprocess
import sys
import winreg

TRAY = r"Control Panel\NotifyIconSettings"
RUN = r"Software\Microsoft\Windows\CurrentVersion\Run"
CFG = r"Software\ExplorerF11"
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
EXE = os.path.join(ROOT, "dist", "ExplorerF11.exe")

OURS = "{TEST-OURS}"
OTHER = "{TEST-OTHER}"

results = []


def check(name, got, want):
    ok = got == want
    results.append(ok)
    print(("  PASS  " if ok else "  FAIL  ") + "%-46s got=%r want=%r" % (name, got, want))


def check_true(name, cond, detail=""):
    check(name + (("  [" + str(detail) + "]") if detail else ""), bool(cond), True)


def val(path, name):
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path) as k:
            return winreg.QueryValueEx(k, name)[0]
    except OSError:
        return None


# --clean wipes everything by design, so remember what the caller had.
orig_run = val(RUN, "ExplorerF11")
orig_cfg = {}
try:
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, CFG) as k:
        i = 0
        while True:
            try:
                n, v, t = winreg.EnumValue(k, i)
            except OSError:
                break
            orig_cfg[n] = (v, t)
            i += 1
except OSError:
    pass

for sub, path in ((OURS, r"C:\somewhere\ExplorerF11.exe"),
                  (OTHER, r"C:\somewhere\notepad-like.exe")):
    k = winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, TRAY + "\\" + sub, 0, winreg.KEY_SET_VALUE)
    winreg.SetValueEx(k, "ExecutablePath", 0, winreg.REG_SZ, path)
    winreg.SetValueEx(k, "IsPromoted", 0, winreg.REG_DWORD, 0)
    winreg.CloseKey(k)


def count():
    ours = planted = 0
    root = winreg.OpenKey(winreg.HKEY_CURRENT_USER, TRAY)
    i = 0
    while True:
        try:
            s = winreg.EnumKey(root, i)
        except OSError:
            break
        i += 1
        try:
            with winreg.OpenKey(root, s) as sk:
                e = winreg.QueryValueEx(sk, "ExecutablePath")[0]
            if os.path.basename(e).lower() == "explorerf11.exe":
                ours += 1
            if s in (OURS, OTHER):
                planted += 1
        except OSError:
            pass
    root.Close()
    return ours, planted


print("==== 1. 造两条托盘记录 ====")
ours0, planted0 = count()
print("      ours=%d, planted=%d" % (ours0, planted0))
check("造的第两条都在", planted0, 2)
check_true("有一条属于本程序", ours0 >= 1, ours0)

print("\n==== 2. --clean 只删自己的那条 ====")
p = subprocess.run([EXE, "--clean", "--quiet"], timeout=20)
check("--clean 退出码 = 0", p.returncode, 0)
ours1, planted1 = count()
check("本程序的记录已清除", ours1, 0)
check("别人的记录仍在（1 条）", planted1, 1)

print("\n==== 3. 收尾：不留测试垃圾 ====")
for sub in (OURS, OTHER):
    try:
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, TRAY + "\\" + sub)
    except OSError:
        pass
check("测试键已删除", count()[1], 0)

with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, RUN, 0, winreg.KEY_SET_VALUE) as k:
    if orig_run is not None:
        winreg.SetValueEx(k, "ExplorerF11", 0, winreg.REG_SZ, orig_run)
    else:
        try:
            winreg.DeleteValue(k, "ExplorerF11")
        except OSError:
            pass
if orig_cfg:
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, CFG, 0, winreg.KEY_SET_VALUE) as k:
        for name, (v, t) in orig_cfg.items():
            winreg.SetValueEx(k, name, 0, t, v)
check("调用者的自启项已还原", val(RUN, "ExplorerF11"), orig_run)

bad = results.count(False)
print("\n%s  %d/%d 通过" % ("ALL PASS" if not bad else "FAILURES",
                            len(results) - bad, len(results)))
sys.exit(1 if bad else 0)
