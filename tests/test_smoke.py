import ctypes
import os
import subprocess
import time
from ctypes import wintypes

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
EXE = os.path.join(ROOT, "dist", "ExplorerF11.exe")
LOG = os.path.join(os.environ["TEMP"], "ExplorerF11.log")

u = ctypes.windll.user32
u.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
u.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
u.GetWindowLongPtrW.restype = ctypes.c_void_p
u.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]

CB = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
GWL_STYLE = -16
WS_CAPTION = 0x00C00000


def folder_windows():
    out = []

    def cb(h, lp):
        b = ctypes.create_unicode_buffer(64)
        u.GetClassNameW(h, b, 64)
        if b.value == "CabinetWClass":
            t = ctypes.create_unicode_buffer(260)
            u.GetWindowTextW(h, t, 260)
            style = u.GetWindowLongPtrW(h, GWL_STYLE) or 0
            out.append((h, t.value, bool(style & WS_CAPTION)))
        return True

    u.EnumWindows(CB(cb), 0)
    return out


if os.path.exists(LOG):
    os.remove(LOG)

subprocess.run(["powershell", "-NoProfile", "-Command",
                "Stop-Process -Name ExplorerF11 -Force -ErrorAction SilentlyContinue"],
               capture_output=True)
time.sleep(0.5)
subprocess.Popen([EXE, "--log"], cwd=os.path.dirname(EXE))
time.sleep(1.5)

print("1) 打开资源管理器窗口")
subprocess.Popen("explorer.exe C:\\Windows\\System32\\drivers", shell=True)
time.sleep(2.5)
wins = folder_windows()
for h, t, cap in wins:
    print("   hwnd=0x%08X caption=%-5s %r" % (h, cap, t))

print("\n2) 日志")
print(open(LOG, encoding="utf-8-sig").read().strip() if os.path.exists(LOG) else "<no log>")

p = subprocess.run(["powershell", "-NoProfile", "-Command",
                    "$p=Get-Process -Name ExplorerF11 -EA SilentlyContinue;"
                    "if($p){'{0} MB private / {1} threads / {2} handles' -f "
                    "[math]::Round($p.PrivateMemorySize64/1MB,2),$p.Threads.Count,$p.HandleCount}"],
                   capture_output=True, text=True)
print("\n3) 资源:", p.stdout.strip())

# Leave the desktop as we found it: close only the window this test opened,
# stop the instance, drop the log. A test that leaves state behind is a bug.
print("\n4) 收尾")
closed = 0
for h, t, cap in wins:
    cls = ctypes.create_unicode_buffer(64)
    u.GetClassNameW(h, cls, 64)
    if cls.value == "CabinetWClass" and "drivers" in t.lower():
        u.PostMessageW(h, 0x0010, 0, 0)      # WM_CLOSE
        closed += 1
time.sleep(0.8)
print("   关闭测试打开的窗口: %d" % closed)
subprocess.run(["taskkill", "/F", "/IM", "ExplorerF11.exe"], capture_output=True)
time.sleep(0.3)
if os.path.exists(LOG):
    os.remove(LOG)
print("   结束实例并删除日志")
