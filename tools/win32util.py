#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Win32 primitives the suites and the screenshot tool share: stop, start,
wait, measure, read a version block.

Measured, the suite spent 62.5 s of which 46 s was `time.sleep` and another
17 s was `powershell`/`taskkill` starting a process to do something a single
API call does. Every one of those sleeps was a guess: long enough on an idle
machine, wrong on a loaded one, and never the shortest correct wait.

Nothing here sleeps for a reason of its own. A wait ends when the thing being
waited for is observable:

  * stopping ends when the process handle signals exit,
  * starting ends when the window exists and the message loop has drained the
    start-up messages (`WaitForInputIdle`),
  * a posted command ends when the caller's own predicate sees its effect.

The 10 ms between polls is the only fixed interval, and it is a poll interval,
not a deadline.
"""

import ctypes
import os
import subprocess
import time
from ctypes import wintypes

k32 = ctypes.WinDLL("kernel32", use_last_error=True)
u32 = ctypes.WinDLL("user32", use_last_error=True)
psapi = ctypes.WinDLL("psapi", use_last_error=True)
ver = ctypes.WinDLL("version", use_last_error=True)

TH32CS_SNAPPROCESS = 0x00000002
TH32CS_SNAPTHREAD = 0x00000004
INVALID_HANDLE_VALUE = wintypes.HANDLE(-1).value
PROCESS_TERMINATE = 0x0001
PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_VM_READ = 0x0010
SYNCHRONIZE = 0x00100000

MAX_PATH_ = 260


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
                ("th32ProcessID", wintypes.DWORD),
                ("th32DefaultHeapID", ctypes.c_void_p),
                ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
                ("th32ParentProcessID", wintypes.DWORD),
                ("pcPriClassBase", ctypes.c_long), ("dwFlags", wintypes.DWORD),
                ("szExeFile", wintypes.WCHAR * MAX_PATH_)]


class THREADENTRY32(ctypes.Structure):
    _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
                ("th32ThreadID", wintypes.DWORD),
                ("th32OwnerProcessID", wintypes.DWORD),
                ("tpBasePri", ctypes.c_long), ("tpDeltaPri", ctypes.c_long),
                ("dwFlags", wintypes.DWORD)]


class PROCESS_MEMORY_COUNTERS_EX(ctypes.Structure):
    _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
                ("PrivateUsage", ctypes.c_size_t)]


class VS_FIXEDFILEINFO(ctypes.Structure):
    _fields_ = [("dwSignature", wintypes.DWORD), ("dwStrucVersion", wintypes.DWORD),
                ("dwFileVersionMS", wintypes.DWORD),
                ("dwFileVersionLS", wintypes.DWORD),
                ("dwProductVersionMS", wintypes.DWORD),
                ("dwProductVersionLS", wintypes.DWORD),
                ("dwFileFlagsMask", wintypes.DWORD), ("dwFileFlags", wintypes.DWORD),
                ("dwFileOS", wintypes.DWORD), ("dwFileType", wintypes.DWORD),
                ("dwFileSubtype", wintypes.DWORD), ("dwFileDateMS", wintypes.DWORD),
                ("dwFileDateLS", wintypes.DWORD)]


k32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
k32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
k32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
k32.Thread32First.argtypes = [wintypes.HANDLE, ctypes.POINTER(THREADENTRY32)]
k32.Thread32Next.argtypes = [wintypes.HANDLE, ctypes.POINTER(THREADENTRY32)]
k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
k32.OpenProcess.restype = wintypes.HANDLE
k32.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
k32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
k32.WaitForSingleObject.restype = wintypes.DWORD
k32.CloseHandle.argtypes = [wintypes.HANDLE]
u32.WaitForInputIdle.argtypes = [wintypes.HANDLE, wintypes.DWORD]
k32.GetProcessHandleCount.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE,
                                       ctypes.POINTER(PROCESS_MEMORY_COUNTERS_EX),
                                       wintypes.DWORD]
u32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
u32.FindWindowW.restype = wintypes.HWND
u32.IsWindow.argtypes = [wintypes.HWND]
ver.GetFileVersionInfoSizeW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(wintypes.DWORD)]
ver.GetFileVersionInfoSizeW.restype = wintypes.DWORD
ver.GetFileVersionInfoW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                    ctypes.c_void_p]
ver.VerQueryValueW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR,
                               ctypes.POINTER(ctypes.c_void_p),
                               ctypes.POINTER(wintypes.UINT)]


def pids(image_name):
    """Process ids whose image name matches, case-insensitively."""
    snap = k32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snap == INVALID_HANDLE_VALUE:
        return []
    out = []
    entry = PROCESSENTRY32W()
    entry.dwSize = ctypes.sizeof(entry)
    try:
        ok = k32.Process32FirstW(snap, ctypes.byref(entry))
        while ok:
            if entry.szExeFile.lower() == image_name.lower():
                out.append(entry.th32ProcessID)
            ok = k32.Process32NextW(snap, ctypes.byref(entry))
    finally:
        k32.CloseHandle(snap)
    return out


def terminate(image_name="ExplorerF11.exe", timeout=5.0):
    """Stop every instance and return once they are gone.

    `taskkill /F /IM` does the same thing through a process launch: measured at
    1.1 s per call, and the suites called it seven times. The handle it would
    have waited on is available here directly, so the wait is real instead of a
    fixed 0.5 s that hopes the process died.
    """
    me = os.getpid()
    stopped = 0
    for pid in pids(image_name):
        if pid == me:
            continue
        h = k32.OpenProcess(PROCESS_TERMINATE | SYNCHRONIZE, False, pid)
        if not h:
            continue
        try:
            if k32.TerminateProcess(h, 1):
                stopped += 1
            k32.WaitForSingleObject(h, int(timeout * 1000))
        finally:
            k32.CloseHandle(h)
    if stopped:
        # TerminateProcess is asynchronous: the handle can be signalled a few
        # milliseconds before the image is unloaded and its window is gone.
        wait_until(lambda: not pids(image_name), timeout=timeout)
    return stopped


def wait_until(predicate, timeout=10.0, interval=0.01):
    """Poll `predicate` until it is true or the deadline passes."""
    end = time.time() + timeout
    while True:
        if predicate():
            return True
        if time.time() >= end:
            return False
        time.sleep(interval)


def window(class_name="ExplorerF11Window", timeout=0.0):
    """The app's hidden window, or 0."""
    find = lambda: u32.FindWindowW(class_name, None) or 0
    if timeout <= 0:
        return find()
    wait_until(lambda: find() != 0, timeout=timeout)
    return find()


def launch(exe, args=(), env=None, class_name="ExplorerF11Window", timeout=10.0):
    """Start the app and return once it is idle in its message loop.

    Waiting for the window is not enough: the start-up sweep is posted from
    WM_CREATE and runs after the loop begins, so a test that reads the registry
    the moment the window appears can read it before the sweep. WaitForInputIdle
    returns when the queue is empty and the thread is blocked on GetMessage,
    which is the first moment the start-up work is genuinely finished.
    """
    proc = subprocess.Popen([exe] + list(args), cwd=os.path.dirname(exe), env=env)
    if class_name:
        if not wait_until(lambda: window(class_name) != 0, timeout=timeout):
            return proc
        u32.WaitForInputIdle(proc._handle, int(timeout * 1000))
    return proc


def stats(pid):
    """(private MB, thread count, handle count) of a running process.

    Replaces the PowerShell query the smoke test used: same three numbers,
    read with GetProcessMemoryInfo/GetProcessHandleCount instead of starting a
    shell, which cost 1.1 s and could fail for reasons unrelated to the binary.
    """
    h = k32.OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, pid)
    if not h:
        return None
    try:
        counters = PROCESS_MEMORY_COUNTERS_EX()
        counters.cb = ctypes.sizeof(counters)
        if not psapi.GetProcessMemoryInfo(
                h, ctypes.byref(counters), ctypes.sizeof(counters)):
            return None
        handles = wintypes.DWORD()
        k32.GetProcessHandleCount(h, ctypes.byref(handles))

        threads = 0
        snap = k32.CreateToolhelp32Snapshot(TH32CS_SNAPTHREAD, 0)
        if snap != INVALID_HANDLE_VALUE:
            entry = THREADENTRY32()
            entry.dwSize = ctypes.sizeof(entry)
            try:
                ok = k32.Thread32First(snap, ctypes.byref(entry))
                while ok:
                    if entry.th32OwnerProcessID == pid:
                        threads += 1
                    ok = k32.Thread32Next(snap, ctypes.byref(entry))
            finally:
                k32.CloseHandle(snap)
        return round(counters.PrivateUsage / (1024.0 * 1024.0), 2), threads, handles.value
    finally:
        k32.CloseHandle(h)


def _version_strings(path):
    """The StringFileInfo block as a dict, whatever its language id is."""
    dummy = wintypes.DWORD()
    size = ver.GetFileVersionInfoSizeW(path, ctypes.byref(dummy))
    if not size:
        return {}
    buf = ctypes.create_string_buffer(size)
    if not ver.GetFileVersionInfoW(path, 0, size, buf):
        return {}

    ptr = ctypes.c_void_p()
    length = wintypes.UINT()
    pairs = []
    if ver.VerQueryValueW(buf, "\\VarFileInfo\\Translation",
                          ctypes.byref(ptr), ctypes.byref(length)) and length.value >= 4:
        words = ctypes.cast(ptr, ctypes.POINTER(wintypes.WORD))
        for i in range(length.value // 4):
            pairs.append((words[2 * i], words[2 * i + 1]))
    if not pairs:
        pairs = [(0x0409, 1200)]

    out = {}
    for lang, codepage in pairs:
        for name in ("CompanyName", "FileDescription", "FileVersion", "InternalName",
                     "LegalCopyright", "OriginalFilename", "ProductName",
                     "ProductVersion"):
            key = "\\StringFileInfo\\%04x%04x\\%s" % (lang, codepage, name)
            if ver.VerQueryValueW(buf, key, ctypes.byref(ptr), ctypes.byref(length)):
                out[name] = ctypes.wstring_at(ptr, length.value).rstrip("\x00")
    return out


def file_version(path):
    """Version strings and the raw fixed block, as a dict.

    Keys match what the suites used to read from
    `(Get-Item ...).VersionInfo.*`, including the two Raw values, because the
    fixed block can drift from the string table - 1.0.1 shipped with the block
    at 1.0.0.0 after only the strings were bumped.
    """
    out = _version_strings(path)

    dummy = wintypes.DWORD()
    size = ver.GetFileVersionInfoSizeW(path, ctypes.byref(dummy))
    if size:
        buf = ctypes.create_string_buffer(size)
        if ver.GetFileVersionInfoW(path, 0, size, buf):
            ptr = ctypes.c_void_p()
            length = wintypes.UINT()
            if ver.VerQueryValueW(buf, "\\", ctypes.byref(ptr), ctypes.byref(length)):
                fixed = ctypes.cast(ptr, ctypes.POINTER(VS_FIXEDFILEINFO)).contents
                out["FileVersionRaw"] = "%d.%d.%d.%d" % (
                    fixed.dwFileVersionMS >> 16, fixed.dwFileVersionMS & 0xFFFF,
                    fixed.dwFileVersionLS >> 16, fixed.dwFileVersionLS & 0xFFFF)
                out["ProductVersionRaw"] = "%d.%d.%d.%d" % (
                    fixed.dwProductVersionMS >> 16, fixed.dwProductVersionMS & 0xFFFF,
                    fixed.dwProductVersionLS >> 16, fixed.dwProductVersionLS & 0xFFFF)
    return out
