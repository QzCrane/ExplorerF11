#!/usr/bin/env python3
"""Regression tests for the robustness defects found in the 1.0.0 audit.

    python tests/test_robustness.py

These defects were invisible to CI and to the existing suites:

  1. On explorer restart, a failed shell-hook re-registration called
     RelaunchSelf() (synchronous DestroyWindow) and then still added a tray
     icon on the dead HWND -> an orphan, unclickable tray icon.
  2. The partial-F11 recovery used a single g_risk slot; a second failure
     within 500 ms overwrote the first, whose stuck fullscreen stayed stuck.
  3. That recovery trusted IsWindow() alone, so a recycled HWND could be
     poked with F11 and have its marks stripped, corrupting another window.
  4. ConsoleOut()'s CONOUT$ handle was never closed (owned/borrowed confused).
  5. A bare trailing `--lang` was misreported as an unknown option.

  6. app.rc bumped only the StringFileInfo strings to 1.0.1, leaving the
     binary VS_FIXEDFILEINFO block at 1.0.0.0 (see test_icons.py Raw asserts).
  7. The tray-residue line always printed " entries", so one record read
     "1 entries" in English.

For (1)-(4) the observable behaviour needs live shell events that cannot be
driven deterministically, so the guarantee is asserted where it is encoded:
the source contracts. (5) is asserted behaviourally through the real CLI.
(6)-(7) are asserted in test_icons.py / test_residue_report.py where those
artefacts are read.
"""

import sys as _sys

if hasattr(_sys.stdout, "reconfigure"):
    _sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
EXE = os.path.join(ROOT, "dist", "ExplorerF11.exe")
MAIN = os.path.join(ROOT, "src", "main.cpp")

results = []


def check(name, got, want):
    ok = got == want
    results.append((ok, name))
    print(("  PASS  " if ok else "  FAIL  ") + "%-56s got=%r want=%r" % (name, got, want))
    return ok


def check_true(name, cond, detail=""):
    return check(name + (("  [" + detail + "]") if detail else ""), bool(cond), True)


src = open(MAIN, encoding="utf-8").read()
src_res = open(os.path.join(ROOT, "src", "residue.cpp"), encoding="utf-8").read()

print("==== 1. explorer 重启自愈：失败分支不得再碰已销毁的 h ====")
check_true("单槽 g_risk 已移除（不再有 g_risk =）",
           re.search(r"\bg_risk\s*=", src) is None)
check_true("RelaunchSelf 与 AddTray(h) 不在同一失败路径",
           "RelaunchSelf();\n        }\n        return 0;" in src,
           "")
check_true("成功分支仍重建托盘（AddTray 保留）", "AddTray(h);" in src)
# The dead-HWND pattern that caused the bug: RelaunchSelf immediately followed
# by RemoveTray/AddTray with no return in between.
check_true("无 'RelaunchSelf() 后继续 AddTray(h)' 模式",
           re.search(r"RelaunchSelf\(\);\s*\n\s*(?:RemoveTray|AddTray)\(h\)", src) is None)

print("\n==== 2+3. 恢复机制：多窗口 + token 校验 ====")
check_true("待恢复窗口是容器而非单槽", "std::vector<RiskEntry> g_risks" in src)
check_true("RiskEntry 同时记录 hwnd 与 tick",
           re.search(r"struct RiskEntry\s*\{\s*HWND hwnd;\s*ULONG_PTR tick;", src) is not None)
check_true("入队前按 (hwnd,tick) 去重",
           "if (!tracked) g_risks.push_back({h, tick});" in src)
check_true("恢复时用 MarkedAt 校验 token", "MarkedAt(r) != e.tick" in src)
check_true("token 不符则跳过（不 poke、不 RemoveProp）",
           re.search(r"if \(!IsMarked\(r\) \|\| MarkedAt\(r\) != e\.tick\) continue;", src) is not None)
check_true("遍历全部待恢复窗口", "for (const RiskEntry &e : pending)" in src)
check_true("批量处理用 swap 清空队列", "pending.swap(g_risks)" in src)

print("\n==== 4. ConsoleOut 句柄所有权 ====")
check_true("ConsoleOut 带 owned 输出参数", "static HANDLE ConsoleOut(bool *owned)" in src)
check_true("每条返回路径都设置 owned",
           src.count("*owned = ") >= 2, str(src.count("*owned = ")))
check_true("仅 owned 句柄被 CloseHandle", "if (owned) CloseHandle(out);" in src)
check_true("Emit 使用 owned 局部变量", "bool owned = false;\n    HANDLE out = ConsoleOut(&owned);" in src)

print("\n==== 5. 系统共享图标不被误销毁 ====")
check_true("回退不再直接返回共享图标给调用方销毁",
           "return h ? h : LoadIconW(NULL, IDI_APPLICATION);" not in src)
check_true("回退走 DuplicateIcon 取私有副本", "DuplicateIcon(GetModuleHandleW(NULL), sys)" in src)

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

print("\n==== 7. 托盘表面：一次推送，且只在字节变化时发 IPC ====")
# Every state change (create/destroy/restore/tab/pause/apply/apply-all/
# recovery/sweep) funnels through OnStateChanged. It used to issue two
# NIM_MODIFY round trips (icon, then tip); 1.0.3 merged them into one. This
# suite pins the follow-up: one push function, one IPC, and no IPC at all when
# the freshly computed surface equals what the shell already holds.
_on_state = re.search(r"(?ms)static void OnStateChanged\(\) \{.*?\n\}", src)
check_true("OnStateChanged 存在", _on_state is not None)
if _on_state:
    body = _on_state.group(0)
    check_true("状态变化只经一个推送函数",
               body.count("PushTraySurface(") == 1, str(body.count("PushTraySurface(")))
    check_true("窗口快照仍只取一次", body.count("MarkedWindows()") == 1,
               str(body.count("MarkedWindows()")))
_push = re.search(r"(?ms)static void PushTraySurface\(.*?\n\}", src)
check_true("推送函数存在", _push is not None)
if _push:
    pb = _push.group(0)
    check_true("只发一次 NIM_MODIFY", pb.count("Shell_NotifyIconW") == 1,
               str(pb.count("Shell_NotifyIconW")))
    check_true("单次 NIM_MODIFY 携带 icon+tip+showtip 三个 flag",
               "NIF_ICON | NIF_TIP | NIF_SHOWTIP" in pb)
    check_true("NIF_SHOWTIP 仍与 NIF_TIP 同行（不丢悬浮提示）",
               "NIF_TIP | NIF_SHOWTIP" in pb)
    check_true("表面与上次相同时不发 IPC",
               "icon == g_lastIcon && tip == g_lastTip) return;" in pb)
    check_true("只有推送成功才记账（失败下次重试）",
               "if (Shell_NotifyIconW(NIM_MODIFY, &nid)) {" in pb)
check_true("UpdateTrayIcon 双调用已消除（无残留定义）",
           re.search(r"static void UpdateTrayIcon\s*\(", src) is None)
check_true("UpdateTrayTip 保留供 hover/language 单独刷新",
           "static void UpdateTrayTip(const WindowMarks &m)" in src
           and "static void UpdateTrayTip()" in src)
check_true("托盘删除后失效记账（下次必须重建）", "g_trayLive = false;" in src)

print("\n==== 8. 报告刷新合并 / 复制复用 ====")
# A full report rebuild re-probes eleven locations (~1.3 ms). A burst of shell
# events used to run it once per event; now the event marks the report dirty
# and posts one refresh, which still reads live state.
_ref = re.search(r"(?ms)static void RefreshStatusIfOpen\(.*?\n\}", src)
check_true("刷新先标记再投递", _ref is not None and "g_statusDirty = true;" in _ref.group(0))
check_true("投递只排队一次", _ref is not None and "!g_refreshPosted" in _ref.group(0))
_h = re.search(r"(?ms)case WM_APP_REFRESH:.*?return 0;", src)
check_true("合并消息处理器存在且清脏标记",
           _h is not None and "g_statusDirty = false;" in _h.group(0))
_copy = re.search(r"(?ms)case IDC_STATUS_COPY:(.*?)break;", src)
check_true("复制复用编辑框内容（不重复扫描注册表）",
           _copy is not None and "GetWindowTextLengthW" in _copy.group(1))

print("\n==== 9. --no-initial 只影响本次运行 ====")
# The flag was parsed and then overwritten by the registry read two statements
# later, so it had never suppressed anything. It now has its own run-scoped
# flag: the sweep is skipped, the persisted setting (and the menu tick) is not.
check_true("--no-initial 有独立的运行期开关",
           "static bool  g_skipInitial       = false;" in src)
check_true("--no-initial 不再写 g_initial",
           re.search(r"--no-initial\"\) == 0\) g_initial = false", src) is None)
check_true("启动扫描同时检查持久设置与本次开关",
           "if (g_initial && !g_skipInitial)" in src)

print("\n==== 10. 菜单计数 = 报告计数 ====")
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

print("\n==== 11. 标记窗口集合：维护而非每次重枚举 ====")
# MarkedWindows used to walk every top-level window and read our property once
# per window (~0.28 ms on a 360-window desktop, 88% of it the property read).
# It now keeps a validated set. The set can only stay honest if all three of
# these hold, so each is pinned at the source contract.
# tools/verify_marks.cpp checks the same equivalence against a live desktop.
_res = src_res
_set_prop_mark = re.findall(r"SetPropW\(\s*\w+\s*,\s*PROP_MARK", _res + src)
check("PROP_MARK 只有一个写入点", len(_set_prop_mark), 1)
_mark = re.search(r"(?ms)static void Mark\(HWND h\) \{.*?\n\}", src)
check_true("Mark() 报告给集合", _mark is not None and "RecordWindowMark(h)" in _mark.group(0))
_unmark_site = re.search(r"(?ms)RemovePropW\(r, PROP_MARK\);.*?RecordWindowUnmark\(r\);", src)
check_true("RemovePropW 之后注销集合", _unmark_site is not None)
_mw = re.search(r"(?ms)WindowMarks MarkedWindows\(\) \{.*?\n\}", _res)
check_true("MarkedWindows 存在", _mw is not None)
if _mw:
    body = _mw.group(0)
    code = re.sub(r"(?m)//.*$", "", body)   # comments may name the call
    check_true("首次读取先播种整桌扫描", "SeedMarkedSet()" in code)
    check_true("每次读取用 IsWindow 校验", "IsWindow(h)" in code)
    check_true("每次读取用 GetPropW 校验", "GetPropW(h, PROP_MARK)" in code)
    check_true("不在读取路径里重新枚举整桌", "EnumWindows(" not in code)
_ru = re.search(r"(?ms)void RecordWindowUnmark\(HWND h\) \{.*?\n\}", _res)
check_true("注销前确认属性确已消失（防漏计）",
           _ru is not None and "if (GetPropW(h, PROP_MARK)) return;" in _ru.group(0))
_seed = re.search(r"(?ms)void SeedMarkedSet\(\) \{.*?\n\}", _res)
check_true("播种用属性过滤整桌", _seed is not None and
           "GetPropW(h, PROP_MARK)" in _seed.group(0))

print("\n==== 12. UserAssist：轮换针，而不是解码每个值名 ====")
# ROT13 is a per-character bijection that commutes with case folding, so
# ContainsI(RoT13(name), needle) == ContainsI(name, RoT13(needle)). Rotating the
# needle once removes a string build plus a per-character pass per value
# (~43% of the match cost on this machine). tools/bench_ua_match.cpp proves the
# equivalence on the live registry.
_ua = re.search(r"(?ms)int UserAssistResidue\(.*?\n\}", _res)
check_true("UserAssistResidue 存在", _ua is not None)
if _ua:
    body = _ua.group(0)
    check_true("针在循环外轮换一次", "const std::wstring needle = RoT13(EXE_BASE);" in body)
    check_true("循环内不再逐个解码值名", "RoT13(name)" not in body)
    check_true("循环内直接搜原始值名", "ContainsI(name, needle.c_str())" in body)
_dmv = re.search(r"(?ms)int DeleteMatchingValues\(.*?\n\}", _res)
check_true("清理路径同样在循环外轮换针",
           _dmv is not None and "const std::wstring target = rot13" in _dmv.group(0)
           and "RoT13(name)" not in _dmv.group(0))

print("\n==== 11. 图标的小尺寸必须是未压缩 DIB ====")
# Windows decodes a PNG-compressed icon through WIC, and that one call loads
# WindowsCodecs.dll into the process: 2.3 MB of code pages and ~100 KB of private
# commit for a 16x16 tray bitmap. The fix is to store the sizes the program
# itself loads (16-48, i.e. every DPI a tray and a title bar ask for) as
# uncompressed DIB, while the large sizes stay PNG for Explorer's thumbnail
# views - Explorer decodes those in its own process, so they cost this program
# nothing. This check fails if anyone saves the small sizes back as PNG.
import struct as _struct


def _icon_formats(path):
    data = open(path, "rb").read()
    reserved, kind, count = _struct.unpack_from("<HHH", data, 0)
    if reserved != 0 or kind != 1:
        raise ValueError("not an icon: " + path)
    out = []
    for i in range(count):
        w, h, _c, _r, _p, _bpp, size, off = _struct.unpack_from(
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

print("\n==== 12. 图标工具可复现 ====")
# The rewrite that produced those icons is a script in tools/, not a manual
# edit, so it can be re-run and audited. It must prove pixel equality itself.
_mk = os.path.join(ROOT, "tools", "make_ico_bmp.py")
check_true("tools/make_ico_bmp.py 存在", os.path.exists(_mk), _mk)
if os.path.exists(_mk):
    _src = open(_mk, encoding="utf-8").read()
    check_true("工具会比对转换前后的像素", "pixels identical" in _src)
    check_true("工具不静默放过像素差异", "pixel mismatch" in _src)

bad = [r for r in results if not r[0]]
print("\n%s  %d/%d 通过" % ("ALL PASS" if not bad else "FAILURES",
                            len(results) - len(bad), len(results)))
sys.exit(1 if bad else 0)
