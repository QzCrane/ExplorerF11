// SPDX-License-Identifier: MIT
//
// One question, measured: how should a UserAssist value name be searched for
// our executable name?
//
// ROT13 is a per-character bijection that commutes with case folding, so
//     ContainsI(RoT13(name), needle)  ==  ContainsI(name, RoT13(needle))
// holds exactly. That removes the per-value decode. This tool proves the
// equivalence on the names actually on this machine and prices four ways of
// doing the same search. Value names are read from the live registry once and
// then replayed, so the number is pure string work with no registry noise.
//
// NOT part of the release build and NOT a test gate.
//
//   g++ -std=c++23 -Os -I. tools/bench_ua_match.cpp -o dist/bench_ua_match.exe
//       -static -static-libgcc -static-libstdc++ -ladvapi32 -lshlwapi
//   dist\bench_ua_match.exe [iterations]

#define WIN32_LEAN_AND_MEAN
#ifndef UNICODE
#define UNICODE
#endif
#ifndef _UNICODE
#define _UNICODE
#endif

#include <windows.h>
#include <shlwapi.h>

#include <algorithm>
#include <cstdio>
#include <cwctype>
#include <string>
#include <vector>

namespace {

const wchar_t *USERASSIST_KEY =
    L"Software\\Microsoft\\Windows\\CurrentVersion\\Explorer\\UserAssist";
const wchar_t *EXE_BASE = L"ExplorerF11.exe";

std::wstring RoT13(const std::wstring &in) {
    std::wstring out = in;
    for (size_t i = 0; i < out.size(); ++i) {
        wchar_t c = out[i];
        if (c >= L'a' && c <= L'z')      out[i] = (wchar_t)(L'a' + (c - L'a' + 13) % 26);
        else if (c >= L'A' && c <= L'Z') out[i] = (wchar_t)(L'A' + (c - L'A' + 13) % 26);
    }
    return out;
}

// What the program does today.
bool ContainsI(const wchar_t *hay, const wchar_t *needle) {
    size_t n = wcslen(needle);
    if (!n) return false;
    for (const wchar_t *p = hay; *p; ++p)
        if (_wcsnicmp(p, needle, n) == 0) return true;
    return false;
}

// Windows' own case-insensitive substring search (shlwapi).
bool ContainsStrStrI(const wchar_t *hay, const wchar_t *needle) {
    return StrStrIW(hay, needle) != NULL;
}

// First-character filter: locate the two possible cases of the needle's first
// character with wmemchr (vectorised), and run the full compare only there.
bool ContainsFirstChar(const wchar_t *hay, const wchar_t *needle) {
    const wchar_t first = needle[0];
    if (!first) return false;
    const wchar_t lo = (wchar_t)towlower(first);
    const wchar_t up = (wchar_t)towupper(first);
    const size_t n = wcslen(needle);
    const wchar_t *p = hay;
    const wchar_t *end = hay + wcslen(hay);
    while (p < end) {
        const wchar_t *a = (const wchar_t *)wmemchr(p, lo, (size_t)(end - p));
        const wchar_t *b = (lo == up) ? a : (const wchar_t *)wmemchr(p, up, (size_t)(end - p));
        if (!a)      p = b;
        else if (!b) p = a;
        else         p = (a < b) ? a : b;
        if (!p) return false;
        if ((size_t)(end - p) < n) return false;
        if (_wcsnicmp(p, needle, n) == 0) return true;
        ++p;
    }
    return false;
}

double Median(std::vector<double> v) {
    if (v.empty()) return 0.0;
    std::sort(v.begin(), v.end());
    size_t n = v.size();
    return (n & 1) ? v[n / 2] : (v[n / 2 - 1] + v[n / 2]) / 2.0;
}

template <class F>
double MicrosecondsPerCall(F fn, int iters, int rounds) {
    LARGE_INTEGER freq;
    QueryPerformanceFrequency(&freq);
    std::vector<double> samples;
    for (int r = 0; r < rounds; ++r) {
        fn();                       // warm up
        LARGE_INTEGER a, b;
        QueryPerformanceCounter(&a);
        for (int i = 0; i < iters; ++i) fn();
        QueryPerformanceCounter(&b);
        samples.push_back((double)(b.QuadPart - a.QuadPart) * 1e6 /
                          (double)freq.QuadPart / iters);
    }
    return Median(samples);
}

}  // namespace

int main(int argc, char **argv) {
    int iters = (argc > 1) ? atoi(argv[1]) : 200;
    if (iters < 10) iters = 10;
    const int rounds = 7;

    std::vector<std::wstring> names;
    HKEY root;
    if (RegOpenKeyExW(HKEY_CURRENT_USER, USERASSIST_KEY, 0, KEY_READ, &root) ==
        ERROR_SUCCESS) {
        for (DWORD i = 0;; ++i) {
            wchar_t guid[128];
            DWORD cch = 128;
            if (RegEnumKeyExW(root, i, guid, &cch, NULL, NULL, NULL, NULL) != ERROR_SUCCESS)
                break;
            std::wstring path = std::wstring(USERASSIST_KEY) + L"\\" + guid + L"\\Count";
            HKEY ck;
            if (RegOpenKeyExW(HKEY_CURRENT_USER, path.c_str(), 0, KEY_READ, &ck)
                != ERROR_SUCCESS)
                continue;
            for (DWORD v = 0;; ++v) {
                wchar_t n[1024];
                DWORD nch = 1024;
                if (RegEnumValueW(ck, v, n, &nch, NULL, NULL, NULL, NULL) != ERROR_SUCCESS) break;
                names.push_back(n);
            }
            RegCloseKey(ck);
        }
        RegCloseKey(root);
    }

    size_t chars = 0;
    for (const std::wstring &n : names) chars += n.size();
    std::printf("UserAssist value names on this machine: %zu, %zu chars (mean %zu)\n\n",
                names.size(), chars, names.empty() ? (size_t)0 : chars / names.size());

    const std::wstring rotatedNeedle = RoT13(EXE_BASE);
    int decodeHits = 0, rotateHits = 0, strstriHits = 0, firstCharHits = 0;

    // A - decode every name, then search for the plain needle (what ships).
    const double decodeUs = MicrosecondsPerCall([&] {
        int h = 0;
        for (const std::wstring &n : names) {
            std::wstring plain = RoT13(n);
            if (ContainsI(plain.c_str(), EXE_BASE)) ++h;
        }
        decodeHits = h;
    }, iters, rounds);

    // B - skip the decode, search for the rotated needle.
    const double rotateUs = MicrosecondsPerCall([&] {
        int h = 0;
        for (const std::wstring &n : names)
            if (ContainsI(n.c_str(), rotatedNeedle.c_str())) ++h;
        rotateHits = h;
    }, iters, rounds);

    // C - same needle, shlwapi's search.
    const double strstriUs = MicrosecondsPerCall([&] {
        int h = 0;
        for (const std::wstring &n : names)
            if (ContainsStrStrI(n.c_str(), rotatedNeedle.c_str())) ++h;
        strstriHits = h;
    }, iters, rounds);

    // D - same needle, first-character filter.
    const double firstCharUs = MicrosecondsPerCall([&] {
        int h = 0;
        for (const std::wstring &n : names)
            if (ContainsFirstChar(n.c_str(), rotatedNeedle.c_str())) ++h;
        firstCharHits = h;
    }, iters, rounds);

    std::printf("A  decode each name, naive scan : %8.2f us / pass  (%d hits)\n",
                decodeUs, decodeHits);
    std::printf("B  rotated needle, naive scan   : %8.2f us / pass  (%d hits)\n",
                rotateUs, rotateHits);
    std::printf("C  rotated needle, StrStrIW     : %8.2f us / pass  (%d hits)\n",
                strstriUs, strstriHits);
    std::printf("D  rotated needle, first-char   : %8.2f us / pass  (%d hits)\n",
                firstCharUs, firstCharHits);

    const bool same = (decodeHits == rotateHits) && (rotateHits == strstriHits) &&
                      (rotateHits == firstCharHits);
    std::printf("\nsame answer everywhere: %s\n", same ? "yes" : "NO");
    std::printf("B vs A: %.2f us saved (%.0f%%)\n", decodeUs - rotateUs,
                decodeUs > 0 ? (decodeUs - rotateUs) * 100.0 / decodeUs : 0.0);
    std::printf("D vs B: %.2f us saved (%.0f%%)\n", rotateUs - firstCharUs,
                rotateUs > 0 ? (rotateUs - firstCharUs) * 100.0 / rotateUs : 0.0);
    return same ? 0 : 1;
}
