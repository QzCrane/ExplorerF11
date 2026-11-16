// SPDX-License-Identifier: MIT
//
// Equivalence check for the maintained marked-window set.
//
// MarkedWindows() used to rediscover the answer on every call: EnumWindows plus
// one GetPropW per top-level window. It now keeps a set and validates it. The
// two must agree in every state, including the awkward ones:
//
//   1  a mark left behind by a previous run (the set has never been seeded)
//   2  a window marked through the normal path (RecordWindowMark)
//   3  the same handle reported twice (must not be counted twice)
//   4  a property removed behind the set's back (validation must drop it)
//   5  an explicit unmark
//   6  a destroyed window
//
// Each case compares the set against a fresh walk over the whole desktop, so
// "equal" means the maintained answer and the rediscovered answer are the same
// number on this machine right now.
//
// NOT part of the release build and NOT a test gate.
//
//   g++ -std=c++23 -Os -I. tools/verify_marks.cpp src/residue.cpp src/config.cpp
//       src/i18n_extra.cpp -o dist/verify_marks.exe -static -static-libgcc
//       -static-libstdc++ -luser32 -lshell32 -ladvapi32
//   dist\verify_marks.exe

#define WIN32_LEAN_AND_MEAN
#ifndef UNICODE
#define UNICODE
#endif
#ifndef _UNICODE
#define _UNICODE
#endif

#include <windows.h>

#include <cstdio>

#include "src/app.h"
#include "src/i18n.h"
#include "src/residue.h"

using namespace ef11;

namespace {

int g_failures = 0;

// What the program did before 1.0.4: ask every top-level window.
int WalkCount() {
    int n = 0;
    EnumWindows([](HWND h, LPARAM p) -> BOOL {
        if (GetPropW(h, PROP_MARK)) ++*(int *)p;
        return TRUE;
    }, (LPARAM)&n);
    return n;
}

void Check(const char *what, int got, int walk) {
    const bool ok = (got == walk);
    if (!ok) ++g_failures;
    std::printf("  %-46s set %3d   walk %3d   %s\n", what, got, walk,
                ok ? "ok" : "MISMATCH");
}

LRESULT CALLBACK Proc(HWND h, UINT m, WPARAM w, LPARAM l) {
    return DefWindowProcW(h, m, w, l);
}

HWND MakeWindow() {
    WNDCLASSW wc = {};
    wc.lpfnWndProc = Proc;
    wc.hInstance = GetModuleHandleW(NULL);
    wc.lpszClassName = L"ExplorerF11VerifyMarks";
    RegisterClassW(&wc);
    return CreateWindowExW(0, wc.lpszClassName, L"verify", WS_OVERLAPPEDWINDOW,
                           0, 0, 200, 120, NULL, NULL, wc.hInstance, NULL);
}

}  // namespace

int main() {
    SetLang(Lang::En);
    std::printf("marked-window equivalence, live desktop\n\n");

    HWND w = MakeWindow();
    if (!w) {
        std::printf("could not create a window (%lu)\n", GetLastError());
        return 2;
    }

    // 1 + 2 - a mark that predates the first read. The set has never been
    // seeded, so this is the case a maintained set cannot infer: it must come
    // from the seeding walk.
    SetPropW(w, PROP_MARK, (HANDLE)1);
    Check("mark present before first read (seeding)", MarkedWindows().windows, WalkCount());

    // 3 - reporting the same handle again must not double it.
    RecordWindowMark(w);
    RecordWindowMark(w);
    Check("same handle reported twice", MarkedWindows().windows, WalkCount());

    // 4 - property removed without telling the set.
    RemovePropW(w, PROP_MARK);
    Check("property removed behind the set's back", MarkedWindows().windows, WalkCount());

    // 2 - the normal path: property set, then reported.
    SetPropW(w, PROP_MARK, (HANDLE)1);
    RecordWindowMark(w);
    Check("normal mark path", MarkedWindows().windows, WalkCount());

    // 5 - an unmark that arrives while the property is still set. The set must
    // keep the window: dropping it would under-count until the process exits,
    // because read-side validation only removes entries, never adds one.
    RecordWindowUnmark(w);
    Check("unmarked but property still set (guarded)", MarkedWindows().windows, WalkCount());

    // 5b - the real sequence at the call site: property gone, then reported.
    RemovePropW(w, PROP_MARK);
    RecordWindowUnmark(w);
    Check("explicit unmark after RemovePropW", MarkedWindows().windows, WalkCount());

    // 6 - destroyed window; still marked, so only IsWindow can drop it.
    SetPropW(w, PROP_MARK, (HANDLE)1);
    RecordWindowMark(w);
    DestroyWindow(w);
    Check("destroyed window", MarkedWindows().windows, WalkCount());

    std::printf("\n%s\n", g_failures ? "FAILURES" : "ALL PASS");
    return g_failures ? 1 : 0;
}
