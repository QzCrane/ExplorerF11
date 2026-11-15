"""
Tests for the footprint report: --status, the tray window, and the two
languages.

What is proven here:
  1. the report tells the truth (verdict, exit code, item count, groups),
  2. merely LOOKING at it writes nothing (state before == state after),
  3. both languages render the same structure,

The clean button is only exercised in the already-clean case: a test must not
delete a real installation's settings as a side effect.

Run:  python tests/test_footprint_report.py
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
RUN = r"Software\Microsoft\Windows\CurrentVersion\Run"
APPROVED = r"Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run"
TRAY = r"Control Panel\NotifyIconSettings"
COMPAT = r"Software\Microsoft\Windows NT\CurrentVersion\AppCompatFlags\Compatibility Assistant\Store"
MUI = r"Software\Classes\Local Settings\Software\Microsoft\Windows\Shell\MuiCache"

IDM_STATUS = 1010
IDC_STATUS_TEXT = 2001
IDC_STATUS_CLEAN = 2003

ENV = dict(os.environ, EXPLORERF11_LANG="zh")

u = ctypes.windll.user32
u.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
u.FindWindowW.restype = wintypes.HWND
u.GetDlgItem.argtypes = [wintypes.HWND, ctypes.c_int]
u.GetDlgItem.restype = wintypes.HWND
u.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
u.SendMessageW.restype = ctypes.c_ssize_t
u.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
u.IsWindowVisible.argtypes = [wintypes.HWND]

results = []


def check(name, got, want):
    ok = got == want
    results.append((ok, name))
    print(("  PASS  " if ok else "  FAIL  ") + "%-52s got=%r want=%r" % (name, got, want))
    return ok


def check_true(name, cond, detail=""):
    return check(name + (("  [" + detail + "]") if detail else ""), bool(cond), True)


def kill():
    subprocess.run(["taskkill", "/F", "/IM", "ExplorerF11.exe"], capture_output=True)
    time.sleep(0.5)


def start():
    subprocess.Popen([EXE, "--lang", "zh"], cwd=os.path.dirname(EXE))
    time.sleep(1.4)


def hwnd(cls):
    return u.FindWindowW(cls, None)


def window_text(h):
    buf = ctypes.create_unicode_buffer(512)
    u.GetWindowTextW(h, buf, 512)
    return buf.value


def post_cmd(cmd_id):
    h = hwnd("ExplorerF11Window")
    if not h:
        return False
    u.PostMessageW(h, 0x0111, cmd_id, 0)   # WM_COMMAND
    time.sleep(0.7)
    return True


def run_status(extra=()):
    p = subprocess.run([EXE, "--status", *extra], capture_output=True, timeout=25, env=ENV)
    return p.returncode, p.stdout.decode("utf-8", "replace")


def val(path, name):
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path) as k:
            return winreg.QueryValueEx(k, name)[0]
    except OSError:
        return None


def key_exists(path):
    try:
        winreg.OpenKey(winreg.HKEY_CURRENT_USER, path).Close()
        return True
    except OSError:
        return False


def values_matching(path, needle):
    n = 0
    try:
        root = winreg.OpenKey(winreg.HKEY_CURRENT_USER, path)
    except OSError:
        return 0
    i = 0
    while True:
        try:
            name, _v, _t = winreg.EnumValue(root, i)
        except OSError:
            break
        i += 1
        if needle.lower() in name.lower():
            n += 1
    root.Close()
    return n


def tray_ours():
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


def log_path():
    return os.path.join(os.environ.get("TEMP", ""), "ExplorerF11.log")


def state():
    return {
        "cfg": key_exists(CFG),
        "run": val(RUN, "ExplorerF11"),
        "approved": val(APPROVED, "ExplorerF11"),
        "tray": tray_ours(),
        "compat": values_matching(COMPAT, "explorerf11.exe"),
        "mui": values_matching(MUI, "explorerf11.exe"),
        "log": os.path.exists(log_path()),
    }


def clipboard_text():
    k32 = ctypes.windll.kernel32
    k32.GlobalLock.argtypes = [wintypes.HGLOBAL]
    k32.GlobalLock.restype = ctypes.c_void_p
    k32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
    if not u.OpenClipboard(None):
        return ""
    try:
        h = u.GetClipboardData(13)          # CF_UNICODETEXT
        if not h:
            return ""
        p = k32.GlobalLock(h)
        if not p:
            return ""
        try:
            return ctypes.wstring_at(p)
        finally:
            k32.GlobalUnlock(h)
    finally:
        u.CloseClipboard()


def read_edit(win):
    edit = u.GetDlgItem(win, IDC_STATUS_TEXT)
    buf = ctypes.create_unicode_buffer(32768)
    u.SendMessageW(edit, 0x000D, 32768, ctypes.cast(buf, ctypes.c_void_p).value)
    return buf.value


print("\n==== 1. 报告与真实状态一致 ====")
kill()
before = state()
print("      state:", before)
code, out = run_status()
print("      --status exit =", code)
for line in out.strip().splitlines()[:5]:
    print("      " + line)

clean = "结论：干净" in out
check("退出码与结论一致", code, 0 if clean else 1)

print("\n==== 2. 结构：4 段、14 项、每项四行 ====")
sections = [l for l in out.splitlines() if l.startswith("── ")]
check("四段标题", len(sections), 4)
items = [l for l in out.splitlines() if l[:1] == "[" and "]" in l]
check("条目总数", len(items), 14)
check_true("每段编号都从 1 开始",
           [l.split("]")[0] + "]" for l in items].count("[1]") == 4,
           str([l.split("]")[0] + "]" for l in items].count("[1]")))
for field in ("谁写：", "位置：", "说明："):
    check("%s 行数 = 条目数" % field, out.count(field), 14)
check_true("程序本体注明不是残留", "不是残留" in out or "干净" in out)
check_true("Windows 记录有解释", "不是它写的" in out or "干净" in out)

print("\n==== 3. 英文版：同样的结构，没有中文 ====")
p = subprocess.run([EXE, "--status", "--lang", "en"], capture_output=True, timeout=25)
en = p.stdout.decode("utf-8", "replace")
check("英文版退出码一致", p.returncode, code)
check("英文版条目数一致", len([l for l in en.splitlines() if l[:1] == "[" and "]" in l]),
      len(items))
check_true("英文版没有中文字符",
           not any("\u4e00" <= ch <= "\u9fff" for ch in en))
check_true("英文版标题正确", en.startswith("ExplorerF11 "), en.splitlines()[0])
check_true("中文版标题正确", out.startswith("ExplorerF11 "), out.splitlines()[0])

print("\n==== 4. 只看不写 ====")
kill()
check("状态与测试前完全一致", state(), before)

print("\n==== 5. 托盘窗口 ====")
start()
check("隐藏窗口存在", bool(hwnd("ExplorerF11Window")), True)
post_cmd(IDM_STATUS)
win = hwnd("ExplorerF11StatusWindow")
check("足迹窗口已打开", bool(win), True)
if win:
    check("窗口可见", bool(u.IsWindowVisible(win)), True)
    text = read_edit(win).replace("\r\n", "\n")
    check("窗口里是同一份报告", len([l for l in text.splitlines() if l[:1] == "[" and "]" in l]),
          len(items))
    check_true("窗口内容与 --status 一致（前 80 字）", text[:80] == out[:80])
    check_true("标题正确", "足迹报告" in window_text(win), window_text(win))

    u.PostMessageW(win, 0x0111, 2002, 0)   # IDC_STATUS_COPY
    time.sleep(0.5)
    clip = clipboard_text()
    check_true("「复制全部」把报告放进剪贴板", clip.startswith("ExplorerF11 "), str(len(clip)))

    print("\n==== 6. 清理按钮（仅在本来就干净时执行）====")
    if clean:
        u.PostMessageW(win, 0x0111, IDC_STATUS_CLEAN, 0)
        time.sleep(1.0)
        check_true("面板仍然干净", "结论：干净" in read_edit(win))
        check_true("标题说明本来就干净", "干净" in window_text(win), window_text(win))
    else:
        print("      （当前有痕迹，跳过清理按钮：测试不替用户删东西）")

    u.PostMessageW(win, 0x0010, 0, 0)   # WM_CLOSE
    time.sleep(0.5)
    check("窗口已关闭", bool(hwnd("ExplorerF11StatusWindow")), False)

print("\n==== 7. 退出后状态不变 ====")
kill()
check("状态仍与测试前一致", state(), before)

bad = [r for r in results if not r[0]]
print("\n%s  %d/%d 通过" % ("ALL PASS" if not bad else "FAILURES",
                            len(results) - len(bad), len(results)))
sys.exit(1 if bad else 0)
