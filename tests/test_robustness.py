#!/usr/bin/env python3
"""Regression tests for the robustness defects found in the 1.0.0 audit.

    python tests/test_robustness.py

These five defects were invisible to CI and to the existing suites:

  1. On explorer restart, a failed shell-hook re-registration called
     RelaunchSelf() (synchronous DestroyWindow) and then still added a tray
     icon on the dead HWND -> an orphan, unclickable tray icon.
  2. The partial-F11 recovery used a single g_risk slot; a second failure
     within 500 ms overwrote the first, whose stuck fullscreen stayed stuck.
  3. That recovery trusted IsWindow() alone, so a recycled HWND could be
     poked with F11 and have its marks stripped, corrupting another window.
  4. ConsoleOut()'s CONOUT$ handle was never closed (owned/borrowed confused).
  5. A bare trailing `--lang` was misreported as an unknown option.

For (1)-(4) the observable behaviour needs live shell events that cannot be
driven deterministically, so the guarantee is asserted where it is encoded:
the source contracts. (5) is asserted behaviourally through the real CLI.
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

bad = [r for r in results if not r[0]]
print("\n%s  %d/%d 通过" % ("ALL PASS" if not bad else "FAILURES",
                            len(results) - len(bad), len(results)))
sys.exit(1 if bad else 0)
