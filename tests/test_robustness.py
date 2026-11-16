#!/usr/bin/env python3
"""Regression pins for defects that have no cheap outside trigger.

    python tests/test_robustness.py

Every assertion here says which kind it is:

  BEHAVIOURAL  the real binary runs and its output is read. No source text.
  WHITE-BOX    the trigger cannot be produced from outside the process, so the
               guarantee is pinned where it is encoded. These assert a property
               - a call-site count, a forbidden pattern, an ordering between a
               check and the action it guards - never a formatted line, and
               never a literal that a rename would break.

The white-box ones cover four defects, each with the reason it cannot be driven:

  * a shell-hook re-registration failure that called RelaunchSelf() and then
    added a tray icon on the destroyed window. Producible only by making
    RegisterShellHookWindow fail, which no supported API allows. What *is*
    observable - the handler survives a TaskbarCreated and still delivers shell
    events afterwards - lives in tests/test_smoke.py.
  * a single-slot recovery queue that lost the first of two failures within
    500 ms, and trusted IsWindow() alone so a recycled HWND could be poked.
    Needs a window that accepts WM_KEYDOWN and then ignores F11; no such window
    exists on demand.
  * ConsoleOut() closing a handle it did not own. Observable only as a handle
    count inside a console-attached process; the CLI detaches early.
  * returning a system shared icon to a caller that destroys it. The corruption
    surfaces in unrelated windows minutes later.

Everything that used to be pinned here as "this exact line is in main.cpp" has
moved to a suite that can observe it:

    startup sweep, --no-initial, live window count, tray rebuild after an
    explorer restart ............................... tests/test_smoke.py
    UserAssist detection (ROT13 value names) ....... tests/test_residue_report.py
    report-window icon ............................. tests/test_smoke.py

The remaining behavioural and artefact checks are kept: --lang diagnostics, the
menu's count against the report's count, and the icon format contract.
"""

import sys as _sys

if hasattr(_sys.stdout, "reconfigure"):
    _sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import os
import re
import struct
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
EXE = os.path.join(ROOT, "dist", "ExplorerF11.exe")
MAIN = os.path.join(ROOT, "src", "main.cpp")
RESIDUE = os.path.join(ROOT, "src", "residue.cpp")

results = []


def check(name, got, want):
    ok = got == want
    results.append((ok, name))
    print(("  PASS  " if ok else "  FAIL  ") + "%-56s got=%r want=%r" % (name, got, want))
    return ok


def check_true(name, cond, detail=""):
    return check(name + (("  [" + detail + "]") if detail else ""), bool(cond), True)


def blocks(path, signature):
    """Every function body whose definition starts with the given signature.

    The brace after the signature matters: main.cpp forward-declares most of
    these, and a declaration is not a body.
    """
    text = open(path, encoding="utf-8").read()
    return [m.group(0) for m in
            re.finditer(r"(?ms)" + signature + r"\s*\{.*?\n\}", text)]


src = open(MAIN, encoding="utf-8").read()
src_res = open(RESIDUE, encoding="utf-8").read()

print("==== 1. 回收队列：多窗口 + token 校验（白盒，无法从外部触发）====")
# A second failure inside 500 ms used to overwrite the first entry, and the
# overwritten window's half-applied F11 stayed that way. One slot is the bug;
# the container is the fix. Then: a recycled HWND must be recognised, which is
# only possible by comparing the tick recorded with the entry. The tick check
# has to *precede* the poke - that ordering is the whole guarantee, so it is
# asserted as an ordering, not as a line.
check_true("已无单槽 g_risk（多窗口不再互相覆盖）",
           re.search(r"\bg_risk\s*=", src) is None)
check_true("待恢复项是 (hwnd, tick) 的容器",
           re.search(r"struct RiskEntry\s*\{\s*HWND\s+\w+;\s*ULONG_PTR\s+\w+;\s*\};"
                     r"\s*static std::vector<RiskEntry>\s+\w+;", src) is not None)
_guard = re.search(r"(?s)if\s*\(\s*!IsMarked\(\w+\)\s*\|\|\s*MarkedAt\(\w+\)\s*!=\s*\w+\.tick\s*\)"
                   r"\s*continue;(.{0,400}?)PostMessageW\(\w+,\s*WM_KEYDOWN", src)
check_true("token 不符的窗口在投递 F11 之前被跳过", _guard is not None)

print("\n==== 2. ConsoleOut 句柄所有权（白盒，句柄数在进程内不可见）====")
# The bug was closing a borrowed CONOUT$ handle. Ownership now travels with the
# handle, so the close can be conditional. Both halves are required: a flag that
# nothing reads would pass a single-line check.
check_true("ConsoleOut 报告句柄是否归自己",
           re.search(r"HANDLE\s+ConsoleOut\(\s*bool\s*\*\s*\w+\s*\)", src) is not None)
check_true("只有自有句柄才 CloseHandle",
           re.search(r"if\s*\(\s*\w+\s*\)\s*CloseHandle\(\s*\w+\s*\);", src) is not None)

print("\n==== 3. 系统共享图标不交给调用方销毁（白盒）====")
# The old fallback handed the shell's shared IDI_APPLICATION to callers that
# destroy what they get. Nothing observable changes at the moment of the bug -
# the damage appears in a different window, later - so the forbidden pattern is
# pinned instead: never return a shared icon handle as if it were private.
check_true("回退不再直接返回共享系统图标",
           re.search(r"return\s+\w+\s*\?\s*\w+\s*:\s*LoadIconW\(", src) is None)

print("\n==== 4. 托盘表面：一次推送，未变不发 IPC（白盒，IPC 不可计数）====")
# No API reports how many NIM_MODIFY round trips went to the shell, and the
# shell offers no read-back of a tooltip. What is checkable is the shape that
# makes the count true: one funnel, one call inside it, an early return when the
# freshly computed surface equals the last one, and bookkeeping only on success.
_on = blocks(MAIN, r"static void OnStateChanged\(\)")
check_true("OnStateChanged 存在", len(_on) == 1)
if _on:
    check("状态变化只经一个推送函数", _on[0].count("PushTraySurface("), 1)
    check("窗口快照每轮只取一次", _on[0].count("MarkedWindows()"), 1)
_push = blocks(MAIN, r"static void PushTraySurface\([^)]*\)")
check_true("PushTraySurface 存在", len(_push) == 1)
if _push:
    check("推送函数内只有一次 Shell_NotifyIconW", _push[0].count("Shell_NotifyIconW"), 1)
    check_true("未变的表面提前返回（不发 IPC）",
               re.search(r"if\s*\(\s*g_trayLive\s*&&\s*icon\s*==\s*g_lastIcon\s*"
                         r"&&\s*tip\s*==\s*g_lastTip\s*\)\s*return;", _push[0]) is not None)
    check_true("只有推送成功才记账",
               re.search(r"if\s*\(\s*Shell_NotifyIconW\(", _push[0]) is not None)
check_true("旧的两次往返入口已删除",
           re.search(r"static void UpdateTrayIcon\s*\(", src) is None)
# Removing the icon invalidates the bookkeeping, or the next push believes the
# shell still holds a surface that is gone and skips the NIM_ADD.
_rm = blocks(MAIN, r"static void RemoveTray\([^)]*\)")
check_true("删除托盘后失效记账", _rm and "g_trayLive = false;" in _rm[0])

print("\n==== 5. 标记集合只有一个写入点（白盒，集合与整桌扫描等价需活桌面）====")
# MarkedWindows keeps a set instead of re-enumerating every top-level window per
# state change. The set can only stay equal to the desktop if PROP_MARK has one
# writer; a second writer would silently desynchronise the count in the tray,
# the menu and the report. tools/verify_marks.cpp checks the same equivalence
# against a live desktop, which is not something a gate can do.
check("PROP_MARK 只有一个写入点",
      len(re.findall(r"SetPropW\(\s*\w+\s*,\s*PROP_MARK", src_res + src)), 1)
# Dropping the entry is only safe once the property is really gone: trusting the
# caller would let one mistaken unmark under-count for the rest of the process,
# and the read-side validation can remove an entry but never discover one.
_unmark = blocks(RESIDUE, r"void RecordWindowUnmark\([^)]*\)")
check_true("注销只剪掉属性确已消失的条目",
           _unmark and re.search(r"\{\s*(?://[^\n]*\n\s*)*if\s*\(\s*GetPropW\("
                                 r"\w+,\s*PROP_MARK\s*\)\s*\)\s*return;",
                                 _unmark[0]) is not None)

print("\n==== 6. --lang 缺值诊断（行为断言）====")
check_true("exe 存在", os.path.exists(EXE), EXE)
if os.path.exists(EXE):
    for tag in ("en", "zh"):
        # EXPLORERF11_LANG chooses the diagnostic language without supplying the
        # missing --lang value; --quiet keeps any no-console fallback silent.
        env = dict(os.environ, EXPLORERF11_LANG=tag)
        p = subprocess.run([EXE, "--lang", "--quiet"], capture_output=True,
                           timeout=20, env=env)
        out = p.stdout.decode("utf-8", "replace")
        check("末尾 --lang 退出码为 2 (%s)" % tag, p.returncode, 2)
        want = "requires a language tag" if tag == "en" else "缺少语言标签"
        check_true("--lang 缺值给出专门诊断 (%s)" % tag, want in out, out.strip()[:80])
        check_true("不再误报未知选项 (%s)" % tag,
                   "Unknown option" not in out and "未知选项" not in out)

print("\n==== 7. 菜单计数 = 报告计数（行为断言）====")
# The menu label reads a presence-only scan, the report reads the full one.
# Same rows, same rules, so the two numbers must agree; this is the check that
# keeps a future probe edit from making the menu lie about how dirty it is.


def _cli(*args):
    p = subprocess.run([EXE] + list(args) + ["--quiet"], capture_output=True,
                       timeout=30)
    return p.stdout.decode("utf-8", "replace")


_menu = _cli("--menu", "--lang", "en")
_report = _cli("--status", "--lang", "en")
_label = [l for l in _menu.splitlines() if "Residue report (" in l]
_m = re.search(r"\((\d+) items?\)", _label[0]) if _label else None
_menu_n = int(_m.group(1)) if _m else 0
_r = re.search(r"Verdict: (\d+) items? to remove", _report)
_report_n = int(_r.group(1)) if _r else 0
check_true("菜单里有残留报告行", bool(_label), str(len(_label)))
check("菜单项数 = 报告项数", _menu_n, _report_n)
check_true("两处都用同一套行（干净时同样读 0）",
           ("clean" in _label[0]) == (_report_n == 0) if _label else False,
           str(_menu_n) + "/" + str(_report_n))

print("\n==== 8. 图标的小尺寸必须是未压缩 DIB（构件断言）====")
# Windows decodes a PNG-compressed icon through WIC, and that one call loads
# WindowsCodecs.dll into the process: 2.3 MB of code pages and ~100 KB of private
# commit for a 16x16 tray bitmap. The fix is to store the sizes the program
# itself loads (16-48, i.e. every DPI a tray and a title bar ask for) as
# uncompressed DIB, while the large sizes stay PNG for Explorer's thumbnail
# views - Explorer decodes those in its own process, so they cost this program
# nothing. This check fails if anyone saves the small sizes back as PNG.


def _icon_formats(path):
    data = open(path, "rb").read()
    reserved, kind, count = struct.unpack_from("<HHH", data, 0)
    if reserved != 0 or kind != 1:
        raise ValueError("not an icon: " + path)
    out = []
    for i in range(count):
        w, h, _c, _r, _p, _bpp, size, off = struct.unpack_from(
            "<BBBBHHII", data, 6 + i * 16)
        blob = data[off:off + 8]
        fmt = "png" if blob[:8] == b"\x89PNG\r\n\x1a\n" else "dib"
        out.append(((w or 256, h or 256), fmt, size))
    return out


for name in ("ExplorerF11.ico", "ExplorerF11-paused.ico"):
    path = os.path.join(ROOT, "src", name)
    try:
        fmt = dict((sz, f) for sz, f, _s in _icon_formats(path))
    except Exception as exc:                       # noqa: BLE001 - report, don't crash
        check_true(name + " 可解析", False, str(exc))
        continue
    small = [sz for sz in fmt if sz[0] <= 48]
    check_true(name + " 含 16/32/48", all(s in fmt for s in ((16, 16), (32, 32), (48, 48))),
               str(sorted(fmt)))
    bad_small = [sz for sz in small if fmt[sz] == "png"]
    check_true(name + " 的 16-48 全是 DIB（否则加载 WIC）", not bad_small, str(bad_small))
    check_true(name + " 保留 256 供资源管理器用", (256, 256) in fmt, str(sorted(fmt)))

print("\n==== 9. 图标重写工具可复现（构件断言）====")
# The rewrite that produced those icons is a script in tools/, not a manual
# edit, so it can be re-run and audited. It must prove pixel equality itself.
_mk = os.path.join(ROOT, "tools", "make_ico_bmp.py")
check_true("tools/make_ico_bmp.py 存在", os.path.exists(_mk), _mk)
if os.path.exists(_mk):
    _tool = open(_mk, encoding="utf-8").read()
    check_true("工具会比对转换前后的像素", "pixels identical" in _tool)
    check_true("工具不静默放过像素差异", "pixel mismatch" in _tool)

bad = [r for r in results if not r[0]]
print("\n%s  %d/%d 通过" % ("ALL PASS" if not bad else "FAILURES",
                            len(results) - len(bad), len(results)))
sys.exit(1 if bad else 0)
