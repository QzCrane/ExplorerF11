#!/usr/bin/env python3
"""Icon and tray-tooltip contract tests.

    python tests/test_icons.py

Two things are checked here that no other suite covers:

  * the binary actually carries its icons and its version block, so Explorer,
    the taskbar, Alt+Tab and the tray all show the product mark instead of the
    generic blank document;
  * the tooltip is rebuilt whenever the state changes and again just before the
    shell draws it. The shell offers no API to read a tooltip back, so the
    freshness guarantee is asserted where it is implemented: the notification
    version, the popup-open branch, and the single funnel every state change
    goes through.
"""

import sys as _sys

# These suites print Chinese, Japanese and Korean. A Windows console defaults to
# a legacy code page, where print() raises UnicodeEncodeError and the suite fails
# for a reason that has nothing to do with the binary under test.
if hasattr(_sys.stdout, "reconfigure"):
    _sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import ctypes
import ctypes.wintypes as wintypes
import os
import re
import struct
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
EXE = os.path.join(ROOT, "dist", "ExplorerF11.exe")
SRC = os.path.join(ROOT, "src")
SIZES = [16, 20, 24, 32, 40, 48, 64, 128, 256]

results = []


def check(name, got, want):
    ok = got == want
    results.append((ok, name))
    print(("  PASS  " if ok else "  FAIL  ") + "%-52s got=%r want=%r" % (name, got, want))
    return ok


def check_true(name, cond, detail=""):
    return check(name + (("  [" + detail + "]") if detail else ""), bool(cond), True)


def ico_sizes(path):
    """Sizes declared in an .ico directory, without any imaging library."""
    data = open(path, "rb").read()
    reserved, kind, count = struct.unpack_from("<HHH", data, 0)
    assert reserved == 0 and kind == 1, "not an ICO file: %s" % path
    out = set()
    for i in range(count):
        bw, bh = data[6 + i * 16], data[6 + i * 16 + 1]
        out.add(256 if bw == 0 else bw)
    return out


print("==== 1. 二进制里有图标 ====")
check_true("exe 存在", os.path.exists(EXE), EXE)
if not os.path.exists(EXE):
    sys.exit(2)

shell32 = ctypes.windll.shell32
shell32.ExtractIconExW.argtypes = [wintypes.LPCWSTR, ctypes.c_int,
                                   ctypes.POINTER(wintypes.HICON),
                                   ctypes.POINTER(wintypes.HICON), ctypes.c_uint]
shell32.ExtractIconExW.restype = ctypes.c_uint
count = shell32.ExtractIconExW(EXE, -1, None, None, 0)
check("exe 内图标数（运行 / 暂停）", count, 2)

print("\n==== 2. 文件属性里的版本信息 ====")
ver = subprocess.run([EXE, "--version", "--quiet"], capture_output=True, timeout=20)
version = ver.stdout.decode("utf-8", "replace").strip().split()[-1]
print("      版本：%s" % version)


def version_info(name):
    # Read through the shell so no extra dependency is needed.
    p = subprocess.run(["powershell", "-NoProfile", "-Command",
                        "(Get-Item '%s').VersionInfo.%s" % (EXE, name)],
                       capture_output=True, timeout=30)
    return p.stdout.decode("utf-8", "replace").strip()


check("FileVersion 与 --version 一致", version_info("FileVersion"), version + ".0")
check("ProductVersion 与 --version 一致", version_info("ProductVersion"), version + ".0")
# StringFileInfo (above) is a string table and can drift from the binary
# VS_FIXEDFILEINFO block. 1.0.1 shipped with the block still at 1.0.0.0 because
# only the strings were bumped. Raw reads that block, so assert it too.
check("FileVersionRaw 与 --version 一致（二进制版本块）",
      version_info("FileVersionRaw.ToString()"), version + ".0")
check("ProductVersionRaw 与 --version 一致（二进制版本块）",
      version_info("ProductVersionRaw.ToString()"), version + ".0")
check("CompanyName", version_info("CompanyName"), "ExplorerF11")
check_true("FileDescription 提到 ExplorerF11",
           "ExplorerF11" in version_info("FileDescription"), version_info("FileDescription"))
check("OriginalFilename", version_info("OriginalFilename"), "ExplorerF11.exe")

print("\n==== 3. 图标文件本身：每种尺寸都在 ====")
for name in ("ExplorerF11.ico", "ExplorerF11-paused.ico"):
    p = os.path.join(SRC, name)
    got = ico_sizes(p)
    check_true("%s 覆盖全部尺寸" % name,
               all(s in got for s in SIZES), "missing %s" % sorted(set(SIZES) - got))
check("两个图标尺寸集合一致",
      ico_sizes(os.path.join(SRC, "ExplorerF11.ico")),
      ico_sizes(os.path.join(SRC, "ExplorerF11-paused.ico")))

print("\n==== 4. 托盘图标：不是系统自带文件夹 ====")
main_cpp = open(os.path.join(SRC, "main.cpp"), encoding="utf-8").read()
check_true("不再借用 SIID_FOLDER", "SIID_FOLDER" not in main_cpp)
check_true("从自身资源加载图标",
           "LoadImageW" in main_cpp and "MAKEINTRESOURCEW" in main_cpp)
check_true("按系统小图标尺寸加载（缩放屏不糊）",
           "SM_CXSMICON" in main_cpp and "SM_CXICON" in main_cpp)
check_true("暂停时换成灰色图标",
           "g_iconPaused" in main_cpp and "TrayIconForState" in main_cpp)

print("\n==== 5. 工具提示：内容源唯一，且会被推送 ====")
check_true("使用 NOTIFYICON_VERSION_4", "NOTIFYICON_VERSION_4" in main_cpp)
check_true("注册 NIF_SHOWTIP", "NIF_SHOWTIP" in main_cpp)
check_true("悬停将弹出时重建提示",
           re.search(r"NIN_POPUPOPEN\)\s*\{[^}]*UpdateTrayTip\(\)", main_cpp, re.S) is not None,
           "")
check_true("状态变化统一走 OnStateChanged",
           main_cpp.count("OnStateChanged();") >= 6,
           str(main_cpp.count("OnStateChanged();")))
# The only direct calls must be the two builders and the popup-open refresh.
direct = len(re.findall(r"(?<!void )UpdateTrayTip\(\);", main_cpp))
check_true("没有绕过统一入口的零散刷新", direct <= 3, str(direct))
check_true("窗口创建后刷新提示", "OnStateChanged();   // one more window" in main_cpp)
check_true("窗口销毁后刷新提示", "IsMarked(gone)) OnStateChanged();" in main_cpp)
check_true("资源管理器重启后重新挂回托盘",
           "TaskbarCreated" in main_cpp and "AddTray(h);" in main_cpp)

print("\n==== 6. 报告窗口带图标 ====")
check_true("WM_SETICON 同时设大小图标",
           "WM_SETICON, ICON_BIG" in main_cpp and "WM_SETICON, ICON_SMALL" in main_cpp)

bad = [r for r in results if not r[0]]
print("\n%s  %d/%d 通过" % ("ALL PASS" if not bad else "FAILURES",
                            len(results) - len(bad), len(results)))
sys.exit(1 if bad else 0)
