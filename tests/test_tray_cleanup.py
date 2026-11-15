import os
import subprocess
import winreg

TRAY = r"Control Panel\NotifyIconSettings"
RUN = r"Software\Microsoft\Windows\CurrentVersion\Run"
CFG = r"Software\ExplorerF11"
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
EXE = os.path.join(ROOT, "dist", "ExplorerF11.exe")


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

planted = [
    (r"{TEST-OURS}", r"C:\somewhere\ExplorerF11.exe"),      # must be removed
    (r"{TEST-OTHER}", r"C:\somewhere\notepad-like.exe"),    # must survive
]
for sub, path in planted:
    k = winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, TRAY + "\\" + sub, 0, winreg.KEY_SET_VALUE)
    winreg.SetValueEx(k, "ExecutablePath", 0, winreg.REG_SZ, path)
    winreg.SetValueEx(k, "IsPromoted", 0, winreg.REG_DWORD, 0)
    winreg.CloseKey(k)


def count():
    ours = other = 0
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
            if s in (r"{TEST-OURS}", r"{TEST-OTHER}"):
                other += 1
        except OSError:
            pass
    root.Close()
    return ours, other


print("planted        -> ours=%d, test-keys=%d" % count())
subprocess.run([EXE, "--clean", "--quiet"], timeout=20)
print("after --clean  -> ours=%d, test-keys=%d  (expect ours=0, test-keys=1)" % count())

# leave no test junk behind
for sub, _ in planted:
    try:
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, TRAY + "\\" + sub)
    except OSError:
        pass
print("cleanup        -> test-keys=%d" % count()[1])

# put the caller's state back (--clean removed it on purpose)
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
print("restored       -> run=%r" % (val(RUN, "ExplorerF11"),))
