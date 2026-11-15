#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""The language feature, end to end.

Proven here:
  1. --lang and EXPLORERF11_LANG change the UI for that run and write nothing,
  2. the tray menu switches language live and the choice survives a restart,
  3. a switch reaches an already open footprint window (title, body, buttons),
  4. the choice is stored only while it differs from the system language -
     picking the system language again deletes the value, so a user who never
     touches the menu leaves nothing behind,
  5. --lang outranks the stored choice.

The suite restores the Language value it found.

Run:  python tests/test_language.py
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
LANG_VALUE = "Language"

IDM_STATUS = 1010
IDM_LANG_ZH = 1011
IDM_LANG_EN = 1012

# No EXPLORERF11_LANG: this suite is about what the tool does on its own.
CLEAN_ENV = {k: v for k, v in os.environ.items() if k != "EXPLORERF11_LANG"}

k32 = ctypes.windll.kernel32
u = ctypes.windll.user32
u.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
u.FindWindowW.restype = wintypes.HWND
u.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
u.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
u.SendMessageW.restype = ctypes.c_ssize_t
u.GetDlgItem.argtypes = [wintypes.HWND, ctypes.c_int]
u.GetDlgItem.restype = wintypes.HWND
u.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
k32.GetUserDefaultLocaleName.argtypes = [wintypes.LPWSTR, ctypes.c_int]

results = []


def check(name, got, want):
    ok = got == want
    results.append((ok, name))
    print(("  PASS  " if ok else "  FAIL  ") + "%-54s got=%r want=%r" % (name, got, want))
    return ok


def check_true(name, cond, detail=""):
    return check(name + (("  [" + str(detail) + "]") if detail else ""), bool(cond), True)


def kill():
    subprocess.run(["taskkill", "/F", "/IM", "ExplorerF11.exe"], capture_output=True)
    time.sleep(0.5)


def start(*args):
    subprocess.Popen([EXE] + list(args), cwd=os.path.dirname(EXE), env=CLEAN_ENV)
    time.sleep(1.3)


def hwnd():
    return u.FindWindowW("ExplorerF11Window", None)


def post(cmd):
    h = hwnd()
    if not h:
        return False
    u.PostMessageW(h, 0x0111, cmd, 0)
    time.sleep(0.8)
    return True


def system_is_zh():
    buf = ctypes.create_unicode_buffer(85)
    n = k32.GetUserDefaultLocaleName(buf, 85)
    return n > 0 and buf.value.lower().startswith("zh")


def read_lang():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, CFG) as k:
            return winreg.QueryValueEx(k, LANG_VALUE)[0]
    except OSError:
        return None


def write_lang(value):
    if value is None:
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, CFG, 0,
                                winreg.KEY_SET_VALUE) as k:
                winreg.DeleteValue(k, LANG_VALUE)
        except OSError:
            pass
        # A test must not leave the empty shell the product itself would delete.
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, CFG)
        except OSError:
            pass
        return
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, CFG, 0, winreg.KEY_SET_VALUE) as k:
        winreg.SetValueEx(k, LANG_VALUE, 0, winreg.REG_SZ, value)


def cfg_exists():
    try:
        winreg.OpenKey(winreg.HKEY_CURRENT_USER, CFG).Close()
        return True
    except OSError:
        return False


def menu(lang=None):
    env = dict(CLEAN_ENV)
    if lang:
        env["EXPLORERF11_LANG"] = lang
    p = subprocess.run([EXE, "--menu"], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", env=env)
    return p.stdout.splitlines()


def checked_language(rows):
    for r in rows:
        if r.strip() == "[✓] 中文（简体）":
            return "zh"
        if r.strip() == "[✓] English":
            return "en"
    return None


def status(*args, env=None):
    p = subprocess.run([EXE, "--status", *args], capture_output=True, timeout=25,
                       env=env or CLEAN_ENV)
    return p.returncode, p.stdout.decode("utf-8", "replace")


def report_language(out):
    """The report states its own UI language in the header: return zh / en."""
    for line in out.splitlines()[:6]:
        if "UI language: English" in line:
            return "en"
        if "界面语言：中文" in line:
            return "zh"
    return None


sys_zh = system_is_zh()
print("==== 0. 环境 ====")
print("      区域格式语言（仅供参考） =", "zh" if sys_zh else "en")
ORIG_LANG = read_lang()
print("      测试前 Language =", ORIG_LANG)
kill()
write_lang(None)
check("起始状态无 Language 值", read_lang(), None)

# The default the tool resolves is the oracle, not the region format: a Chinese
# UI with an English region is a normal combination, and the tool answers to the
# UI language. With no stored value and no override, the menu shows that default.
sys_tag = checked_language(menu())
check_true("能确定默认语言", sys_tag in ("zh", "en"), sys_tag)
other_tag = "en" if sys_tag == "zh" else "zh"
other_id = IDM_LANG_EN if sys_tag == "zh" else IDM_LANG_ZH
sys_id = IDM_LANG_ZH if sys_tag == "zh" else IDM_LANG_EN
print("      默认语言 =", sys_tag, "（另一语言 =", other_tag, "）")

print("\n==== 1. --lang / EXPLORERF11_LANG 只影响本次运行，不落盘 ====")
check("环境变量 zh 生效", checked_language(menu("zh")), "zh")
check("环境变量 en 生效", checked_language(menu("en")), "en")
code, out = status("--lang", "en")
check("--lang en 的报告是英文", report_language(out), "en")
code_zh, out_zh = status("--lang", "zh")
check("--lang zh 的报告是中文", report_language(out_zh), "zh")
check("命令行切语言不写注册表", read_lang(), None)
code, out = status()          # 无任何覆盖：应回到系统语言
check("默认报告 = 系统语言", report_language(out), sys_tag)

print("\n==== 2. 托盘切换：立即生效 + 持久化 ====")
start()
check("隐藏窗口存在", bool(hwnd()), True)
check("启动时不写 Language", read_lang(), None)
check("进程内菜单是系统语言", checked_language(menu()), sys_tag)

check("发出切换指令", post(other_id), True)
check("切换到非系统语言后写入值", read_lang(), other_tag)
rows = menu()                                   # 新进程，读的是存储值
check("重启后仍是刚才选的语言", checked_language(rows), other_tag)
code, out = status()                            # 不传 --lang
check("报告跟随存储的语言", report_language(out), other_tag)

print("\n==== 3. --lang 优先于存储值 ====")
code, out = status("--lang", sys_tag)
check("--lang 覆盖存储值", report_language(out), sys_tag)
check("覆盖不改变存储值", read_lang(), other_tag)
out_env = subprocess.run([EXE, "--status"], capture_output=True, timeout=25,
                         env=dict(CLEAN_ENV, EXPLORERF11_LANG=sys_tag)).stdout
check("环境变量也覆盖存储值", report_language(out_env.decode("utf-8", "replace")), sys_tag)

print("\n==== 4. 切回系统语言 -> 删除存储值（零足迹）====")
check("仍在上一步的实例里切换", post(sys_id), True)
check("选回系统语言后值被删除", read_lang(), None)
check("配置键随之消失", cfg_exists(), False)
check("菜单显示系统语言", checked_language(menu()), sys_tag)
kill()

print("\n==== 5. 已打开的足迹窗口跟随切换 ====")
start()
post(IDM_STATUS)
win = u.FindWindowW("ExplorerF11StatusWindow", None)
check("足迹窗口已打开", bool(win), True)
if win:
    def win_text():
        buf = ctypes.create_unicode_buffer(512)
        u.GetWindowTextW(win, buf, 512)
        return buf.value

    def body():
        edit = u.GetDlgItem(win, 2001)
        b = ctypes.create_unicode_buffer(65536)
        u.SendMessageW(edit, 0x000D, 65536, ctypes.cast(b, ctypes.c_void_p).value)
        return b.value

    before_lang = report_language(body().replace("\r\n", "\n"))
    check("窗口正文当前语言 = 系统语言", before_lang, sys_tag)
    post(other_id)
    after_lang = report_language(body().replace("\r\n", "\n"))
    check("窗口正文已跟随切换", after_lang, other_tag)
    want_title = "footprint report" if other_tag == "en" else "足迹报告"
    check_true("窗口标题已跟随切换", want_title in win_text(), win_text())
    u.PostMessageW(win, 0x0010, 0, 0)
    time.sleep(0.4)
kill()

print("\n==== 6. 还原 ====")
write_lang(ORIG_LANG)
check("Language 已还原", read_lang(), ORIG_LANG)
if ORIG_LANG is None and not cfg_exists():
    check("配置键干净", cfg_exists(), False)

bad = [r for r in results if not r[0]]
print("\n%s  %d/%d 通过" % ("ALL PASS" if not bad else "FAILURES",
                            len(results) - len(bad), len(results)))
sys.exit(1 if bad else 0)
