#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Pins the tray menu: exact rows, groups, ticks, and the language submenu.

--menu prints the very menu the right click builds (same BuildTrayMenu call),
so this test cannot drift away from the real UI. Submenu rows are indented by
four spaces under their "[>]" parent. Read-only: it must not write a single
registry value.
"""

import sys as _sys

# These suites print Chinese, Japanese and Korean. A Windows console defaults to
# a legacy code page, where print() raises UnicodeEncodeError and the suite fails
# for a reason that has nothing to do with the binary under test.
if hasattr(_sys.stdout, "reconfigure"):
    _sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import os
import re
import subprocess
import sys
import winreg

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
EXE = os.path.join(ROOT, "dist", "ExplorerF11.exe")

RUN = r"Software\Microsoft\Windows\CurrentVersion\Run"
CFG = r"Software\ExplorerF11"
APPROVED = r"Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run"

fails = 0


def check(name, got, want):
    global fails
    ok = got == want
    if not ok:
        fails += 1
    print(("PASS  " if ok else "FAIL  ") + name +
          ("" if ok else "\n      got  %r\n      want %r" % (got, want)))


def check_true(name, cond, note=""):
    check(name + (("  (" + note + ")") if note else ""), bool(cond), True)


def val(path, name):
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path) as k:
            return winreg.QueryValueEx(k, name)[0]
    except OSError:
        return None


def state():
    cfg = {}
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, CFG) as k:
            i = 0
            while True:
                try:
                    n, v, _ = winreg.EnumValue(k, i)
                except OSError:
                    break
                cfg[n] = v
                i += 1
    except OSError:
        pass
    return {
        "run": val(RUN, "ExplorerF11"),
        "approved": val(APPROVED, "ExplorerF11"),
        "cfg": cfg,
    }


def menu(lang="zh"):
    env = dict(os.environ, EXPLORERF11_LANG=lang)
    p = subprocess.run([EXE, "--menu"], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", env=env)
    return p.returncode, [l.rstrip() for l in p.stdout.splitlines() if l.strip()]


print("==== 1. 菜单存在且只读 ====")
before = state()
code, rows = menu()
after = state()
check("退出码 = 0", code, 0)
check_true("有输出", len(rows) > 0, "%d 行" % len(rows))
check("不写注册表（前后完全一致）", after, before)

print("\n==== 2. 逐行顺序（中文）====")
HEAD = rows[0] if rows else ""
def version():
    p = subprocess.run([EXE, "--version"], capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    return p.stdout.strip().replace("ExplorerF11 ", "").strip()

VERSION = version()
check_true("第 1 行是灰色状态行", HEAD.startswith("[x] ExplorerF11"), HEAD)
check_true("状态行版本号与 --version 一致", VERSION in HEAD, HEAD)
# 状态行只有四种形态。数量和单位写死在这里：窗口数后面必须带选项卡数，
# 否则又会回到「明明看得见两个 tab，却只说 1 个窗口」。
check_true("状态行内容合法",
           re.fullmatch(r"\[x\] ExplorerF11 " + re.escape(VERSION) +
                        r"  ·  (已暂停加速|运行中，等待文件夹窗口|"
                        r"已加速 \d+ 个窗口(（含 \d+ 个选项卡）)?)", HEAD) is not None,
           HEAD)
if "已加速" in HEAD:
    check_true("窗口数后面带着选项卡数", "（含 " in HEAD and HEAD.endswith("个选项卡）"), HEAD)

want = [
    "----",
    "[ ] 对所有已打开的窗口应用",
    None,                            # 对当前窗口立即应用 —— 无可用窗口时置灰
    "[ ] 暂停加速",
    "----",
    "[✓] 新建选项卡时重新加速窗口",
    "[✓] 启动时加速已打开的窗口",
    None,                            # 开机自启 —— 勾选反映真实自启状态
    "[>] 界面语言",
    "    [✓] 简体中文",
    "    [ ] 繁體中文",
    "    [ ] English",
    "    [ ] 日本語",
    "    [ ] 한국어",
    "----",
    None,                            # 残留报告 —— 括号里是项数
    "----",
    "[ ] 退出",
]
rest = rows[1:]
check("行数（含子菜单五行）", len(rest), len(want))
for i, w in enumerate(want):
    got = rest[i] if i < len(rest) else "<missing>"
    if w is None:
        if i == 7:
            check_true("第 %d 行是开机自启且带勾选位" % (i + 2),
                       (got.startswith("[✓] ") or got.startswith("[ ] "))
                       and got.endswith("开机自启"), got)
        elif i == 2:
            # 没有可用目标窗口时置灰，是正确行为；这一行只钉位置与文案。
            check_true("第 %d 行是对当前窗口立即应用（可灰）" % (i + 2),
                       got[:4] in ("[ ] ", "[x] ") and got.endswith("对当前窗口立即应用"),
                       got)
        else:
            check_true("第 %d 行是残留报告" % (i + 2),
                       got.startswith("[ ] 残留报告（") and got.endswith("）…"), got)
    else:
        check("第 %d 行" % (i + 2), got, w)

print("\n==== 3. 结构约束 ====")
check("顶层分隔线 3 条", sum(1 for r in rest if r.strip() == "----"), 4)
LANG_ROWS = ("简体中文", "繁體中文", "English", "日本語", "한국어")
check_true("子菜单行缩进 4 格",
           all(r.startswith("    ") for r in rest
               if any(name in r for name in LANG_ROWS)), "")
run = val(RUN, "ExplorerF11")
appr = val(APPROVED, "ExplorerF11")
blocked = isinstance(appr, bytes) and len(appr) >= 1 and (appr[0] & 1) != 0
autostart_on = run is not None and not blocked
# 两个默认打开的设置 + 语言单选 + 可能的自启
check("勾选项数 = 3 + 自启状态", sum(1 for r in rest if r.strip().startswith("[✓] ")),
      3 + (1 if autostart_on else 0))
check_true("退出永远在最后一行", rest[-1] == "[ ] 退出", rest[-1])
check_true("退出上一行是分隔线", len(rest) > 1 and rest[-2] == "----")
fp_i = next(i for i, r in enumerate(rest) if r.startswith("[ ] 残留报告（"))
sep_i = next(i for i, r in enumerate(rest) if i > fp_i and r.strip() == "----")
check("维护段 = 残留 + 分隔线",
      [r.strip() for r in rest[fp_i + 1:sep_i + 1]], ["----"])
check("残留报告之后紧跟退出", rest[sep_i + 1], "[ ] 退出")
# One destructive action, one place. It lives inside the report window, where
# the user can see what is about to be deleted; the menu keeps no second copy.
check_true("菜单里没有第二个清理入口",
           not any("清除" in r or "Clean" in r or "clean" in r for r in rest), "")
check_true("只有残留报告带省略号",
           all(r.strip().endswith("…") for r in rest if "…" in r) and
           sum(1 for r in rest if "…" in r) == 1,
           "带 … 的行：%d" % sum(1 for r in rest if "…" in r))
check_true("没有残留旧文案",
           not any("注册表残留" in r or "Run at logon" in r or "新标签页" in r
                   for r in rest))

print("\n==== 4. 五种语言：同样结构、勾选正确、正文随语言切换 ====")
# 状态行有三种形态：等待窗口、已加速 N 个窗口、已暂停。哪一种是当前状态取决于
# 这台机器上有没有文件夹窗口 —— CI 上没有，开发机上通常有 —— 所以每种语言接受
# 该语言的全部合法形态，而不是假定其中一个。
for lang, checked, status_markers, report_prefix, exit_row in (
    ("en", "English", ("accelerated", "waiting for a folder window"),
     "[ ] Residue report (", "[ ] Exit"),
    ("zh-Hant", "繁體中文", ("個視窗", "等待資料夾視窗"),
     "[ ] 殘留報告（", "[ ] 結束"),
    ("ja", "日本語", ("ウィンドウを高速化", "待機中"),
     "[ ] 残留レポート（", "[ ] 終了"),
    ("ko", "한국어", ("가속됨", "대기 중"),
     "[ ] 잔여물 보고서 (", "[ ] 종료"),
):
    code_l, rows_l = menu(lang)
    check("%s 菜单退出码 = 0" % lang, code_l, 0)
    check("%s 菜单行数一致" % lang, len(rows_l), len(rows))
    check_true("%s 状态行已本地化" % lang,
               any(m in rows_l[0] for m in status_markers), rows_l[0])
    checked_langs = [r.strip()[4:] for r in rows_l if r.startswith("    [✓] ")]
    check("%s 语言单选唯一且正确" % lang, checked_langs, [checked])
    check_true("%s 残留报告项" % lang,
               any(r.startswith(report_prefix) for r in rows_l),
               next((r for r in rows_l if "报告" in r or "報告" in r or "report" in r
                     or "レポート" in r or "보고서" in r), ""))
    check("%s 退出项已本地化" % lang, rows_l[-1], exit_row)
    # 子菜单里的语言名是专名，不翻译；其余正文必须整体换掉。
    # 分隔线是跨语言共用的结构符号，不参与比对。
    body = [r for r in rows_l[1:] if not r.startswith("    ") and r != "----"]
    check_true("%s 正文没有混用中文简体菜单" % lang,
               not any(r in rows for r in body), str(body))

print("\n==== 5. 暂停/恢复只占一行 ====")
check("暂停/恢复只占一行", sum(1 for r in rest if "暂停加速" in r or "恢复加速" in r), 1)

print("\n==== 6. 帮助里写明计数单位 ====")
def help_text(lang):
    env = dict(os.environ, EXPLORERF11_LANG=lang)
    p = subprocess.run([EXE, "--help"], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", env=env)
    return p.stdout

zh_help, en_help = help_text("zh"), help_text("en")
check_true("中文帮助：以窗口为单位，选项卡不单独加速",
           "以窗口为单位" in zh_help and "选项卡不会单独加速" in zh_help)
check_true("英文帮助：counted in windows, never per tab",
           "counted in windows" in en_help and "never accelerated on its own" in en_help)

print("\n==== 7. 未知选项立刻失败，不静默启动托盘 ====")
# A typo must never turn into "started a tray instance and did nothing": the
# exit code is the only signal a script can see. 2 is the conventional usage
# error, distinct from --status's 0/1 which reports the machine's state.
def run(args, lang="en"):
    env = dict(os.environ, EXPLORERF11_LANG=lang)
    p = subprocess.run([EXE] + args, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", env=env)
    return p.returncode, p.stdout

rc, out = run(["--cleen", "--quiet"])
check("未知选项退出码 = 2", rc, 2)
check_true("未知选项被原样写出", "--cleen" in out, out.strip().splitlines()[0] if out else "")
check_true("未知选项提示 --help", "--help" in out)
rc, out = run(["--lang", "xx", "--quiet"])
check("无效 --lang 退出码 = 2", rc, 2)
check_true("无效 --lang 写出整个参数", "--lang xx" in out, out.strip().splitlines()[0] if out else "")
rc, out = run(["--lang"], "zh")
check("--lang 缺少取值退出码 = 2", rc, 2)
check_true("中文界面下用中文报告未知选项", "未知选项：" in out, out.strip().splitlines()[0] if out else "")
rc, out = run(["--version", "--quiet"])
check("已知选项仍然退出 0", rc, 0)

print("\n" + ("全部通过" if fails == 0 else "%d 项失败" % fails))
sys.exit(1 if fails else 0)
