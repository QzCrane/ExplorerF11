// SPDX-License-Identifier: MIT
//
// Diagnostic micro-benchmark for the behaviour hot paths. NOT part of the
// release build and NOT a test gate: it exists so a performance claim can be
// reproduced with a number instead of an adjective.
//
//   g++ -std=c++23 -Os -I. tools/bench_hotpaths.cpp src/residue.cpp
//       src/config.cpp src/i18n_extra.cpp -o dist/bench_hotpaths.exe
//       -static -static-libgcc -static-libstdc++ -luser32 -lshell32 -ladvapi32
//   dist\bench_hotpaths.exe [iterations]
//
// Each path is warmed up, timed with QueryPerformanceCounter over several
// rounds, and reported as the MEDIAN milliseconds per 1000 calls. Median is
// deliberate: a single GC-like heap stretch or an Explorer hiccup must not
// move a published figure.

#define WIN32_LEAN_AND_MEAN
#ifndef UNICODE
#define UNICODE
#endif
#ifndef _UNICODE
#define _UNICODE
#endif

#include <windows.h>
#include <shellapi.h>
#include <algorithm>
#include <cstdio>
#include <cstdlib>
#include <string>
#include <vector>

#include "src/app.h"
#include "src/config.h"
#include "src/residue.h"
#include "src/i18n.h"

using namespace ef11;

static double median(std::vector<double> v) {
    if (v.empty()) return 0.0;
    std::sort(v.begin(), v.end());
    size_t n = v.size();
    return (n & 1) ? v[n / 2] : (v[n / 2 - 1] + v[n / 2]) / 2.0;
}

template <class F>
static double ms_per_1000(F fn, int iters, int rounds) {
    LARGE_INTEGER freq;
    QueryPerformanceFrequency(&freq);
    std::vector<double> samples;
    for (int r = 0; r < rounds; ++r) {
        fn();  // warm-up: pay page faults and heap growth before the clock starts
        LARGE_INTEGER a, b;
        QueryPerformanceCounter(&a);
        for (int i = 0; i < iters; ++i) fn();
        QueryPerformanceCounter(&b);
        samples.push_back((double)(b.QuadPart - a.QuadPart) * 1000.0 /
                          (double)freq.QuadPart / iters * 1000.0);
    }
    return median(samples);
}

static void report(const char *name, double ms) {
    std::printf("  %-34s %8.3f ms / 1000\n", name, ms);
}

int main(int argc, char **argv) {
    int iters = (argc > 1) ? std::atoi(argv[1]) : 400;
    if (iters < 10) iters = 10;
    const int rounds = 5;

    std::printf("ExplorerF11 hot-path benchmark, %d iters x %d rounds, median\n\n",
                iters, rounds);

    SetLang(Lang::En);

    // ---- residue layer: shared by --status, --menu and the open report ----
    WindowMarks m = MarkedWindows();
    report("MarkedWindows (EnumWindows)", ms_per_1000([&] { MarkedWindows(); }, iters, rounds));
    report("CollectResidues (11 probes)", ms_per_1000([&] { CollectResidues(); }, iters, rounds));
    report("CurrentTotals (menu count)", ms_per_1000([&] { CurrentTotals(); }, iters, rounds));
    report("BuildResidueReport (full)", ms_per_1000([&] { BuildResidueReport(); }, iters, rounds));
    report("BuildResidueReport (+marks)", ms_per_1000([&] { BuildResidueReport(NULL, NULL, &m); }, iters, rounds));

    // ---- decompose CollectResidues: probe (Win32) vs string formatting ----
    // Mirrors residue.cpp's eleven probes but does NO string building at all.
    // The gap between this and CollectResidues is the cost of constructing the
    // writer/note/where/content strings that Summarize() throws away for the
    // menu-count path. That gap is the ceiling of a "count only" fast path.
    const wchar_t *EXE_BASE_BENCH = L"ExplorerF11.exe";
    auto containsI = [](const wchar_t *hay, const wchar_t *needle) {
        size_t n = wcslen(needle);
        if (!n) return false;
        for (const wchar_t *p = hay; *p; ++p)
            if (_wcsnicmp(p, needle, n) == 0) return true;
        return false;
    };
    auto probesOnly = [&] {
        HKEY k;
        // 1. settings key
        if (RegOpenKeyExW(HKEY_CURRENT_USER, CFG_KEY, 0, KEY_READ, &k) == ERROR_SUCCESS) {
            DWORD vals = 0;
            RegQueryInfoKeyW(k, NULL, NULL, NULL, NULL, NULL, NULL, &vals,
                             NULL, NULL, NULL, NULL);
            for (DWORD i = 0; i < vals; ++i) {
                wchar_t name[256]; DWORD cch = 256;
                RegEnumValueW(k, i, name, &cch, NULL, NULL, NULL, NULL);
            }
            RegCloseKey(k);
        }
        // 2. autostart value
        if (RegOpenKeyExW(HKEY_CURRENT_USER, RUN_KEY, 0, KEY_READ, &k) == ERROR_SUCCESS) {
            wchar_t b[2048]; DWORD cb = sizeof(b), t = 0;
            RegQueryValueExW(k, RUN_VALUE, NULL, &t, (BYTE *)b, &cb);
            RegCloseKey(k);
        }
        // 3+4. two files
        WIN32_FILE_ATTRIBUTE_DATA d;
        GetFileAttributesExW(LogPath().c_str(), GetFileExInfoStandard, &d);
        GetFileAttributesExW(ExePath().c_str(), GetFileExInfoStandard, &d);
        // 5. approval flag
        if (RegOpenKeyExW(HKEY_CURRENT_USER, APPROVED_KEY, 0, KEY_READ, &k) == ERROR_SUCCESS) {
            wchar_t b[2048]; DWORD cb = sizeof(b), t = 0;
            RegQueryValueExW(k, RUN_VALUE, NULL, &t, (BYTE *)b, &cb);
            RegCloseKey(k);
        }
        // 6. tray icon bookkeeping
        if (RegOpenKeyExW(HKEY_CURRENT_USER, TRAY_KEY, 0, KEY_READ, &k) == ERROR_SUCCESS) {
            for (DWORD i = 0;; ++i) {
                wchar_t sub[256]; DWORD cch = 256;
                if (RegEnumKeyExW(k, i, sub, &cch, NULL, NULL, NULL, NULL) != ERROR_SUCCESS) break;
                std::wstring p = std::wstring(TRAY_KEY) + L"\\" + sub;
                HKEY sk;
                if (RegOpenKeyExW(HKEY_CURRENT_USER, p.c_str(), 0, KEY_READ, &sk) == ERROR_SUCCESS) {
                    wchar_t exe[MAX_PATH * 2]; DWORD cb = sizeof(exe), t = 0;
                    RegQueryValueExW(sk, L"ExecutablePath", NULL, &t, (BYTE *)exe, &cb);
                    RegCloseKey(sk);
                }
            }
            RegCloseKey(k);
        }
        // 7+8. Compat store + MuiCache value scans
        for (const wchar_t *key : {COMPAT_KEY, MUI_KEY}) {
            if (RegOpenKeyExW(HKEY_CURRENT_USER, key, 0, KEY_READ, &k) == ERROR_SUCCESS) {
                for (DWORD i = 0;; ++i) {
                    wchar_t name[1024]; DWORD cch = 1024;
                    if (RegEnumValueW(k, i, name, &cch, NULL, NULL, NULL, NULL) != ERROR_SUCCESS) break;
                    containsI(name, EXE_BASE_BENCH);
                }
                RegCloseKey(k);
            }
        }
        // 9. UserAssist
        if (RegOpenKeyExW(HKEY_CURRENT_USER, USERASSIST_KEY, 0, KEY_READ, &k) == ERROR_SUCCESS) {
            for (DWORD i = 0;; ++i) {
                wchar_t guid[128]; DWORD cch = 128;
                if (RegEnumKeyExW(k, i, guid, &cch, NULL, NULL, NULL, NULL) != ERROR_SUCCESS) break;
                std::wstring c = std::wstring(USERASSIST_KEY) + L"\\" + guid + L"\\Count";
                HKEY ck;
                if (RegOpenKeyExW(HKEY_CURRENT_USER, c.c_str(), 0, KEY_READ, &ck) == ERROR_SUCCESS) {
                    for (DWORD v = 0;; ++v) {
                        wchar_t name[1024]; DWORD nch = 1024;
                        if (RegEnumValueW(ck, v, name, &nch, NULL, NULL, NULL, NULL) != ERROR_SUCCESS) break;
                        containsI(name, EXE_BASE_BENCH);
                    }
                    RegCloseKey(ck);
                }
            }
            RegCloseKey(k);
        }
        // 10. Prefetch
        wchar_t win[MAX_PATH];
        if (GetWindowsDirectoryW(win, MAX_PATH)) {
            std::wstring pat = std::wstring(win) + L"\\Prefetch\\EXPLORERF11.EXE-*.pf";
            WIN32_FIND_DATAW fd;
            HANDLE fh = FindFirstFileW(pat.c_str(), &fd);
            if (fh != INVALID_HANDLE_VALUE) {
                do {} while (FindNextFileW(fh, &fd));
                FindClose(fh);
            }
        }
        // 11. window marks use the passed snapshot here (count only)
    };
    report("probes only (no strings)", ms_per_1000(probesOnly, iters, rounds));
    report("string+struct overhead", ms_per_1000([&] { CollectResidues(&m); }, iters, rounds)
                                      - ms_per_1000(probesOnly, iters, rounds));

    // ---- window filter: runs on every activation / creation event ---------
    report("filter top-level windows", ms_per_1000([&] {
        EnumWindows([](HWND h, LPARAM) -> BOOL {
            wchar_t cn[64] = {0};
            if (GetClassNameW(h, cn, 64) && wcscmp(cn, EXPLORER_CLASS) == 0) {
                wchar_t title[256] = {0};
                GetWindowTextW(h, title, 256);
            }
            return TRUE;
        }, 0);
    }, iters, rounds));

    // ---- tray IPC: OnStateChanged issues TWO NIM_MODIFY calls today -------
    WNDCLASSW wc = {};
    wc.lpfnWndProc = DefWindowProcW;
    wc.hInstance = GetModuleHandleW(NULL);
    wc.lpszClassName = L"EF11BenchTray";
    RegisterClassW(&wc);
    HWND h = CreateWindowExW(0, wc.lpszClassName, L"bench", 0, 0, 0, 0, 0,
                             NULL, NULL, wc.hInstance, NULL);
    if (h) {
        NOTIFYICONDATAW nid = {};
        nid.cbSize = sizeof(nid);
        nid.hWnd = h;
        nid.uID = 4242;
        nid.uFlags = NIF_ICON | NIF_MESSAGE | NIF_TIP;
        nid.uCallbackMessage = WM_USER + 7;
        nid.hIcon = LoadIconW(NULL, IDI_APPLICATION);
        wcscpy_s(nid.szTip, L"bench");
        Shell_NotifyIconW(NIM_ADD, &nid);
        const int ipcIters = iters / 4 < 200 ? 200 : iters / 4;

        nid.uFlags = NIF_ICON;
        double one = ms_per_1000([&] { Shell_NotifyIconW(NIM_MODIFY, &nid); }, ipcIters, rounds);
        nid.uFlags = NIF_ICON | NIF_TIP | NIF_SHOWTIP;
        double both = ms_per_1000([&] { Shell_NotifyIconW(NIM_MODIFY, &nid); }, ipcIters, rounds);
        report("NIM_MODIFY (icon only)", one);
        report("NIM_MODIFY (icon+tip)", both);
        report("two calls vs one (saved)", one + ms_per_1000([&] {
            NOTIFYICONDATAW t = {};
            t.cbSize = sizeof(t); t.hWnd = h; t.uID = 4242;
            t.uFlags = NIF_TIP | NIF_SHOWTIP; wcscpy_s(t.szTip, L"bench");
            Shell_NotifyIconW(NIM_MODIFY, &t);
        }, ipcIters, rounds) - both);

        nid.uFlags = 0;
        Shell_NotifyIconW(NIM_DELETE, &nid);
        DestroyWindow(h);
    }

    std::printf("\nmarks on this machine: windows=%d tabs=%d\n", m.windows, m.tabs);
    return 0;
}
