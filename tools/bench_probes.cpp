// SPDX-License-Identifier: MIT
//
// Per-probe cost breakdown for the eleven residue rows. The aggregate
// benchmark (bench_hotpaths.cpp) answers "how much does the report cost"; this
// one answers "which probe does the report spend it on", which is what decides
// whether a probe can be made cheaper or has to be paid in full.
//
// NOT part of the release build and NOT a test gate.
//
//   g++ -std=c++23 -Os -I. tools/bench_probes.cpp src/residue.cpp src/config.cpp
//       src/i18n_extra.cpp -o dist/bench_probes.exe
//       -static -static-libgcc -static-libstdc++ -luser32 -lshell32 -ladvapi32
//   dist\bench_probes.exe [iterations]

#define WIN32_LEAN_AND_MEAN
#ifndef UNICODE
#define UNICODE
#endif
#ifndef _UNICODE
#define _UNICODE
#endif

#include <windows.h>
#include <algorithm>
#include <cstdio>
#include <cstdlib>
#include <string>
#include <vector>

#include "src/app.h"
#include "src/config.h"
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
        fn();
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
    std::printf("  %-38s %8.3f ms / 1000\n", name, ms);
}

int main(int argc, char **argv) {
    int iters = (argc > 1) ? std::atoi(argv[1]) : 300;
    if (iters < 10) iters = 10;
    const int rounds = 5;
    SetLang(Lang::En);
    std::printf("Per-probe breakdown, %d iters x %d rounds, median\n\n", iters, rounds);

    HKEY k;
    report("1  settings key (open+query)", ms_per_1000([&] {
        if (RegOpenKeyExW(HKEY_CURRENT_USER, CFG_KEY, 0, KEY_READ, &k) == ERROR_SUCCESS) {
            DWORD vals = 0;
            RegQueryInfoKeyW(k, NULL, NULL, NULL, NULL, NULL, NULL, &vals,
                             NULL, NULL, NULL, NULL);
            RegCloseKey(k);
        }
    }, iters, rounds));

    report("2  autostart value", ms_per_1000([&] {
        if (RegOpenKeyExW(HKEY_CURRENT_USER, RUN_KEY, 0, KEY_READ, &k) == ERROR_SUCCESS) {
            wchar_t b[2048]; DWORD cb = sizeof(b), t = 0;
            RegQueryValueExW(k, RUN_VALUE, NULL, &t, (BYTE *)b, &cb);
            RegCloseKey(k);
        }
    }, iters, rounds));

    report("3+4 two file stats", ms_per_1000([&] {
        WIN32_FILE_ATTRIBUTE_DATA d;
        GetFileAttributesExW(LogPath().c_str(), GetFileExInfoStandard, &d);
        GetFileAttributesExW(ExePath().c_str(), GetFileExInfoStandard, &d);
    }, iters, rounds));

    report("5  startup approval flag", ms_per_1000([&] {
        if (RegOpenKeyExW(HKEY_CURRENT_USER, APPROVED_KEY, 0, KEY_READ, &k) == ERROR_SUCCESS) {
            wchar_t b[64]; DWORD cb = sizeof(b), t = 0;
            RegQueryValueExW(k, RUN_VALUE, NULL, &t, (BYTE *)b, &cb);
            RegCloseKey(k);
        }
    }, iters, rounds));

    report("6  tray icon bookkeeping", ms_per_1000([&] {
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
    }, iters, rounds));

    for (const wchar_t *key : {COMPAT_KEY, MUI_KEY}) {
        const char *name = (key == COMPAT_KEY) ? "7  compat store (value scan)"
                                               : "8  MuiCache (value scan)";
        report(name, ms_per_1000([&] {
            if (RegOpenKeyExW(HKEY_CURRENT_USER, key, 0, KEY_READ, &k) == ERROR_SUCCESS) {
                for (DWORD i = 0;; ++i) {
                    wchar_t n[1024]; DWORD cch = 1024;
                    if (RegEnumValueW(k, i, n, &cch, NULL, NULL, NULL, NULL) != ERROR_SUCCESS) break;
                }
                RegCloseKey(k);
            }
        }, iters, rounds));
    }

    report("9  UserAssist (GUID x value)", ms_per_1000([&] {
        if (RegOpenKeyExW(HKEY_CURRENT_USER, USERASSIST_KEY, 0, KEY_READ, &k) == ERROR_SUCCESS) {
            for (DWORD i = 0;; ++i) {
                wchar_t guid[128]; DWORD cch = 128;
                if (RegEnumKeyExW(k, i, guid, &cch, NULL, NULL, NULL, NULL) != ERROR_SUCCESS) break;
                std::wstring c = std::wstring(USERASSIST_KEY) + L"\\" + guid + L"\\Count";
                HKEY ck;
                if (RegOpenKeyExW(HKEY_CURRENT_USER, c.c_str(), 0, KEY_READ, &ck) == ERROR_SUCCESS) {
                    for (DWORD v = 0;; ++v) {
                        wchar_t n[1024]; DWORD nch = 1024;
                        if (RegEnumValueW(ck, v, n, &nch, NULL, NULL, NULL, NULL) != ERROR_SUCCESS) break;
                    }
                    RegCloseKey(ck);
                }
            }
            RegCloseKey(k);
        }
    }, iters, rounds));

    report("10 Prefetch glob", ms_per_1000([&] {
        wchar_t win[MAX_PATH];
        if (GetWindowsDirectoryW(win, MAX_PATH)) {
            std::wstring pat = std::wstring(win) + L"\\Prefetch\\EXPLORERF11.EXE-*.pf";
            WIN32_FIND_DATAW fd;
            HANDLE fh = FindFirstFileW(pat.c_str(), &fd);
            if (fh != INVALID_HANDLE_VALUE) FindClose(fh);
        }
    }, iters, rounds));

    std::printf("\nUserAssist value names containing the exe (decoded):\n");
    if (RegOpenKeyExW(HKEY_CURRENT_USER, USERASSIST_KEY, 0, KEY_READ, &k) == ERROR_SUCCESS) {
        int hits = 0;
        for (DWORD i = 0;; ++i) {
            wchar_t guid[128]; DWORD cch = 128;
            if (RegEnumKeyExW(k, i, guid, &cch, NULL, NULL, NULL, NULL) != ERROR_SUCCESS) break;
            std::wstring c = std::wstring(USERASSIST_KEY) + L"\\" + guid + L"\\Count";
            HKEY ck;
            if (RegOpenKeyExW(HKEY_CURRENT_USER, c.c_str(), 0, KEY_READ, &ck) != ERROR_SUCCESS) continue;
            for (DWORD v = 0;; ++v) {
                wchar_t n[1024]; DWORD nch = 1024;
                if (RegEnumValueW(ck, v, n, &nch, NULL, NULL, NULL, NULL) != ERROR_SUCCESS) break;
                std::wstring plain(n);
                for (size_t p = 0; p < plain.size(); ++p) {
                    wchar_t ch = plain[p];
                    if (ch >= L'a' && ch <= L'z')      plain[p] = (wchar_t)(L'a' + (ch - L'a' + 13) % 26);
                    else if (ch >= L'A' && ch <= L'Z') plain[p] = (wchar_t)(L'A' + (ch - L'A' + 13) % 26);
                }
                if (plain.find(L"ExplorerF11.exe") != std::wstring::npos) {
                    std::printf("  %ls\\%ls\n", guid, plain.c_str());
                    ++hits;
                }
            }
            RegCloseKey(ck);
        }
        RegCloseKey(k);
        std::printf("  (%d hit(s))\n", hits);
    }
    std::printf("\nour exe path: %ls\n", ExePath().c_str());
    return 0;
}
