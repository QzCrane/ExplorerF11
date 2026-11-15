#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Pins the tray menu: exact order, groups, ticks, greyed rows.

--menu prints the very menu the right click builds (same BuildTrayMenu call),
so this test cannot drift away from the real UI. Read-only: it must not write
a single registry value.
"""
import os
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
    print(("PASS  " if ok else "FAIL  ") + name + ("" if ok else "\n      got  %r\n      want %r" % (got, want)))


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


def menu():
    env = dict(os.environ, EXPLORERF11_LANG="zh")
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

print("\n==== 2. 逐行顺序 ====")
HEAD = rows[0] if rows else ""
check_true("第 1 行是灰色状态行", HEAD.startswith("[x] ExplorerF11"), HEAD)
check_true("状态行内容合法",
           HEAD.endswith("运行中") or HEAD.endswith("已暂停")
           or ("已加速" in HEAD and HEAD.endswith("个窗口")), HEAD)

want = [
    "----",
    "[ ] 对所有已打开的窗口应用",
    "[ ] 对当前窗口立即应用",
    "[ ] 暂停加速",
    "----",
    "[✓] 新标签页也加速",
    "[✓] 启动时处理已打开的窗口",
    None,                        # 开机自启 —— 勾选反映真实自启状态
    "----",
    None,                        # 注册表足迹 —— 括号里是处数
    "[ ] 清除全部痕迹并退出…",
    "----",
    "[ ] 退出",
]
rest = rows[1:]
check("行数", len(rest), len(want))
for i, w in enumerate(want):
    got = rest[i] if i < len(rest) else "<missing>"
    if w is None:
        if i == 7:
            check_true("第 %d 行是开机自启且带勾选位" % (i + 2),
                       (got.startswith("[✓] ") or got.startswith("[ ] "))
                       and got.endswith("开机自启"), got)
        else:
            check_true("第 %d 行是足迹报告" % (i + 2),
                       got.startswith("[ ] 足迹报告（") and got.endswith("）…"), got)
    else:
        check("第 %d 行" % (i + 2), got, w)

print("\n==== 3. 结构约束 ====")
check("分隔线 4 条", sum(1 for r in rest if r == "----"), 4)
# 两个默认打开的设置必然有勾；开机自启跟着真实注册表状态走
run = val(RUN, "ExplorerF11")
appr = val(APPROVED, "ExplorerF11")
blocked = isinstance(appr, bytes) and len(appr) >= 1 and (appr[0] & 1) != 0
autostart_on = run is not None and not blocked
check("勾选项数 = 2 + 自启状态", sum(1 for r in rest if r.startswith("[✓] ")),
      2 + (1 if autostart_on else 0))
check_true("退出永远在最后一行", rest[-1] == "[ ] 退出", rest[-1])
check_true("退出上一行是分隔线", len(rest) > 1 and rest[-2] == "----")
fp_i = next(i for i, r in enumerate(rest) if r.startswith("[ ] 足迹报告（"))
sep_i = next(i for i, r in enumerate(rest) if i > fp_i and r == "----")
check("维护段 = 足迹 + 清除 + 分隔线", rest[fp_i + 1:sep_i + 1],
      ["[ ] 清除全部痕迹并退出…", "----"])
check("清除之后紧跟退出", rest[sep_i + 1], "[ ] 退出")
check_true("只有维护段带省略号",
           all(r.endswith("…") for r in rest if "…" in r) and
           sum(1 for r in rest if "…" in r) == 2,
           "带 … 的行：%d" % sum(1 for r in rest if "…" in r))
check_true("没有残留旧文案", not any("注册表足迹" in r for r in rest))

print("\n==== 4. 暂停后文案应切换 ====")
# 用一份临时配置模拟"已暂停"不可行（暂停不落盘），这里只验证静态部分：
# 恢复加速 与 暂停加速 是同一行，不会同时出现
check("暂停/恢复只占一行", sum(1 for r in rest if "暂停加速" in r or "恢复加速" in r), 1)

print("\n" + ("全部通过" if fails == 0 else "%d 项失败" % fails))
sys.exit(1 if fails else 0)
