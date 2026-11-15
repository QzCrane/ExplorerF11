// SPDX-License-Identifier: MIT
//
// ExplorerF11 - event-driven F11 accelerator for Windows 11 File Explorer.
//
// When a folder window appears, or a new tab is opened in one, this posts two
// F11 press/release cycles to that window. The fullscreen round trip makes the
// window tear down and rebuild its top-level chrome, and navigation in the
// rebuilt window is noticeably faster. It automates the well-known manual
// trick; it is NOT a fix for the underlying shell behaviour.
//
// No polling, no focus stealing, no runtime dependencies, no admin rights.
//
// Layout:
//   main.cpp       window, tray icon, shell hooks, menu, report window, CLI
//   config.cpp     settings + autostart (HKCU only, zero writes by default)
//   footprint.cpp  what the tool leaves behind, and how to remove all of it
//   i18n.h         runtime language selection (zh / en), switchable while running
//
// Registry policy:
//   * DEFAULT CONFIG WRITES NOTHING. A fresh run creates zero keys.
//   * A setting is stored only while it deviates from its default value.
//   * Returning a setting to its default deletes the value, and removes the key
//     as soon as it holds nothing - the key never exists as an empty shell.
//   * Autostart off = no Run value at all.
//   * Autostart state follows what Windows will actually do: a Run value that
//     Task Manager disabled (StartupApproved flag) reads as off, and enabling
//     deletes that flag instead of writing one.
//   * The same rule covers the UI language: picking the system language deletes
//     the stored Language value, so a user who never touches the menu writes
//     nothing.
//   * --clean removes every removable trace, including Windows' own bookkeeping
//     (tray icon cache, compatibility store, MuiCache, UserAssist, Prefetch)
//     and leftovers from the pre-v5 product name.

#define WIN32_LEAN_AND_MEAN
#ifndef UNICODE
#define UNICODE
#endif
#ifndef _UNICODE
#define _UNICODE
#endif

// _wfopen is the portable-enough way to append a UTF-8 log from a Win32 binary;
// the "safe" variant buys nothing here and would add a template to the exe.
// Must be defined before the CRT headers are pulled in.
#ifdef _MSC_VER
#define _CRT_SECURE_NO_WARNINGS
#endif

#include <windows.h>
#include <shellapi.h>
#include <string>
#include <vector>
#include <cstdio>
#include <cstring>

#include "app.h"
#include "config.h"
#include "footprint.h"
#include "i18n.h"

using namespace ef11;

// MinGW links these four by default; MSVC needs them named explicitly.
#ifdef _MSC_VER
#pragma comment(lib, "user32.lib")       // windows, menus, the tray icon message
#pragma comment(lib, "gdi32.lib")        // CreateFontW, GetStockObject, GetDeviceCaps
#pragma comment(lib, "shell32.lib")      // Shell_NotifyIconW, SHGetStockIconInfo
#pragma comment(lib, "advapi32.lib")     // RegOpenKeyEx / RegSetValueEx
#endif

#ifndef HSHELL_RUDEAPPACTIVATED
#define HSHELL_RUDEAPPACTIVATED 0x8004   // a fullscreen app took the activation
#endif

static const UINT WM_TRAYICON    = WM_USER + 1;
static const UINT IDM_PAUSE      = 1002;
static const UINT IDM_APPLY      = 1003;
static const UINT IDM_APPLY_ALL  = 1004;
static const UINT IDM_AUTOSTART  = 1005;
static const UINT IDM_EXIT       = 1006;
static const UINT IDM_TABS       = 1007;
static const UINT IDM_INITIAL    = 1008;
static const UINT IDM_CLEAN      = 1009;
static const UINT IDM_STATUS     = 1010;
static const UINT IDM_LANG_ZH    = 1011;
static const UINT IDM_LANG_EN    = 1012;
// status window controls
static const UINT IDC_STATUS_TEXT = 2001;
static const UINT IDC_STATUS_COPY = 2002;
static const UINT IDC_STATUS_CLEAN = 2003;
static const UINT IDC_STATUS_CLOSE = 2004;
static const UINT TRAY_ID        = 1001;
static const UINT_PTR RISK_TIMER = 1;
static const UINT WM_APP_INITIAL = WM_APP + 1;   // start-up sweep, after the loop runs

static UINT  g_shellHookMsg      = 0;
static UINT  g_taskbarCreatedMsg = 0;
static bool  g_paused            = false;
static bool  g_log               = false;
static bool  g_quiet             = false;   // --quiet: no message boxes, scriptable
static bool  g_langExplicit      = false;   // --lang given on the command line
static bool  g_tabs              = DEF_TABS;
static bool  g_initial           = DEF_INITIAL;
static HWND  g_hwnd              = NULL;
static HWND  g_risk              = NULL;
static HWND  g_lastFolder        = NULL;   // last folder window that got activated
static HICON g_icon              = NULL;
static HANDLE g_mux              = NULL;
static HWINEVENTHOOK g_winEvent  = NULL;
static HWINEVENTHOOK g_winEvent2 = NULL;

// ---------------------------------------------------------------- logging

static void Log(const wchar_t *msg) {
    if (!g_log) return;
    wchar_t path[MAX_PATH];
    GetTempPathW(MAX_PATH, path);
    wcscat_s(path, MAX_PATH, L"ExplorerF11.log");

    const wchar_t *mode = L"a, ccs=UTF-8";
    WIN32_FILE_ATTRIBUTE_DATA fad;
    if (GetFileAttributesExW(path, GetFileExInfoStandard, &fad)) {
        ULONGLONG size = ((ULONGLONG)fad.nFileSizeHigh << 32) | fad.nFileSizeLow;
        if (size > 1024ULL * 1024ULL) mode = L"w, ccs=UTF-8";  // rotate at 1 MB
    }

    FILE *f = _wfopen(path, mode);
    if (!f) return;
    SYSTEMTIME st;
    GetLocalTime(&st);
    fwprintf(f, L"[%02d:%02d:%02d.%03d] ", st.wHour, st.wMinute, st.wSecond,
             st.wMilliseconds);
    fputws(msg, f);
    fputwc(L'\n', f);
    fclose(f);
}

// ---------------------------------------------------------------- autostart

// Every dialog goes through here so --quiet can suppress it (batch use).
static int Say(const wchar_t *text, UINT flags) {
    if (g_quiet) return (flags & MB_YESNO) ? IDYES : IDOK;
    return MessageBoxW(NULL, text, APP_NAME, flags);
}

// Result dialog after a clean. Every counter is independent, so a partial clean
// (for example Prefetch without admin rights) still tells the truth: only the
// groups that actually lost something are listed, each with its own count.
static void AppendCleanLine(std::wstring *s, const wchar_t *label, int n) {
    if (!n) return;
    wchar_t b[32];
    swprintf_s(b, L"%d", n);
    *s += L"  \u00B7 ";
    *s += label;
    *s += L"  \u00D7";
    *s += b;
    *s += L"\n";
}

static void ShowCleanReport(const CleanReport &r) {
    std::wstring s;
    if (!r.Any()) {
        s = T(L"\u6CA1\u6709\u9700\u8981\u6E05\u7406\u7684\u9879\u76EE\u3002\n\n"
               L"\u9ED8\u8BA4\u914D\u7F6E\u4E0D\u5199\u6CE8\u518C\u8868\u3001\u4E0D\u5EFA\u6587\u4EF6\uFF0C"
               L"\u8FD9\u6B21\u68C0\u67E5\u4E5F\u6CA1\u6709\u627E\u5230\u4EFB\u4F55\u4E0E\u672C\u7A0B\u5E8F"
               L"\u76F8\u5173\u7684\u8BB0\u5F55\u3002",
              L"Nothing to remove.\n\nThe default configuration writes no registry value and "
              L"no file, and this check found no record of the program anywhere.");
    } else {
        // Count first, then conjugate: "1 item removed" and "3 items removed"
        // read as prose, where "%d item(s)" reads as a placeholder.
        std::wstring head = T(L"已清除 ", L"Removed ");
        head += std::to_wstring(r.Total());
        head += T(L" 项：\n\n", r.Total() == 1 ? L" item:\n\n" : L" items:\n\n");
        s = head;
        AppendCleanLine(&s, T(L"\u8BBE\u7F6E\u952E\uFF08HKCU\\Software\\ExplorerF11\uFF09",
                              L"settings key (HKCU\\Software\\ExplorerF11)"), r.cfg);
        AppendCleanLine(&s, T(L"\u5F00\u673A\u81EA\u542F\u9879\uFF08HKCU\\...\\Run\\ExplorerF11\uFF09",
                              L"autostart entry (HKCU\\...\\Run\\ExplorerF11)"), r.run);
        AppendCleanLine(&s, T(L"\u65E5\u5FD7\u6587\u4EF6\uFF08%TEMP%\\ExplorerF11.log\uFF09",
                              L"log file (%TEMP%\\ExplorerF11.log)"), r.logFile);
        AppendCleanLine(&s, T(L"\u542F\u52A8\u5F00\u5173\u8BB0\u5F55\uFF08\u4EFB\u52A1\u7BA1\u7406\u5668\uFF09",
                              L"startup approval flag (Task Manager)"), r.approved);
        AppendCleanLine(&s, T(L"\u6258\u76D8\u56FE\u6807\u8BB0\u5F55",
                              L"tray icon bookkeeping"), r.tray);
        AppendCleanLine(&s, T(L"\u517C\u5BB9\u6027\u52A9\u624B\u8BB0\u5F55",
                              L"compatibility assistant store"), r.compat);
        AppendCleanLine(&s, T(L"\u5E94\u7528\u540D\u7F13\u5B58\uFF08MuiCache\uFF09",
                              L"friendly-name cache (MuiCache)"), r.mui);
        AppendCleanLine(&s, T(L"\u542F\u52A8\u6B21\u6570\u7EDF\u8BA1\uFF08UserAssist\uFF09",
                              L"launch counter (UserAssist)"), r.userAssist);
        AppendCleanLine(&s, T(L"\u9884\u8BFB\u53D6\u8BB0\u5F55\uFF08Prefetch\uFF09",
                              L"Prefetch entry"), r.prefetch);
        AppendCleanLine(&s, T(L"\u65E7\u7248\u672C\u6B8B\u7559\uFF08ExplorerF11Ultra\uFF09",
                              L"legacy leftovers (ExplorerF11Ultra)"), r.legacy);
        s += T(L"\n\u7A0B\u5E8F\u672C\u4F53\u4FDD\u7559\u5728\u539F\u5904\uFF1B\u8981\u5F7B\u5E95\u5378\u8F7D\uFF0C"
               L"\u518D\u628A ExplorerF11.exe \u5220\u6389\u5373\u53EF\u3002",
               L"\nThe exe stays where it is; delete ExplorerF11.exe as well for a full uninstall.");
    }
    Say(s.c_str(), MB_ICONINFORMATION);
}

// ---------------------------------------------------------------- status window

static HWND  g_status     = NULL;
static HFONT g_statusFont = NULL;

// An EDIT control only breaks lines on CRLF; a lone LF is swallowed and the
// whole report would run together as one paragraph.
static std::wstring ToCrlf(const std::wstring &s) {
    std::wstring r;
    r.reserve(s.size() + s.size() / 24);
    for (size_t i = 0; i < s.size(); ++i) {
        if (s[i] == L'\n') r += L"\r\n";
        else               r += s[i];
    }
    return r;
}

static void RefreshStatus(HWND h) {
    std::wstring t = ToCrlf(BuildFootprintReport(NULL, NULL));
    SetDlgItemTextW(h, IDC_STATUS_TEXT, t.c_str());
}

// The UI font that actually ships with the UI language. Segoe UI has no CJK
// coverage on an English system, and Microsoft YaHei UI does not exist on one.
static const wchar_t *UiFontName() {
    return T(L"Microsoft YaHei UI", L"Segoe UI");
}

// Called when the language changes while the report window is open: title,
// buttons and body all follow, so the window is never half-translated.
static void RelocalizeStatus(HWND h) {
    SetWindowTextW(h, T(L"ExplorerF11 \u00B7 \u8DB3\u8FF9\u62A5\u544A",
                        L"ExplorerF11 \u00B7 footprint report"));
    SetDlgItemTextW(h, IDC_STATUS_COPY,  T(L"\u590D\u5236\u5168\u90E8", L"Copy all"));
    SetDlgItemTextW(h, IDC_STATUS_CLEAN, T(L"\u6E05\u7406\u75D5\u8FF9", L"Clean up"));
    SetDlgItemTextW(h, IDC_STATUS_CLOSE, T(L"\u5173\u95ED", L"Close"));
    RefreshStatus(h);
    InvalidateRect(h, NULL, TRUE);
}

static void CopyToClipboard(HWND owner, const std::wstring &s) {
    if (!OpenClipboard(owner)) return;
    EmptyClipboard();
    size_t cb = (s.size() + 1) * sizeof(wchar_t);
    HGLOBAL g = GlobalAlloc(GMEM_MOVEABLE, cb);
    if (g) {
        void *p = GlobalLock(g);
        if (p) {
            memcpy(p, s.c_str(), cb);
            GlobalUnlock(g);
            SetClipboardData(CF_UNICODETEXT, g);
        } else {
            GlobalFree(g);
        }
    }
    CloseClipboard();
}

static void LayoutStatus(HWND h) {
    RECT r;
    GetClientRect(h, &r);
    const int m = 12, bh = 32, gap = 8;
    int y  = r.bottom - m - bh;
    int bw = 118;
    int x  = r.right - m;

    MoveWindow(GetDlgItem(h, IDC_STATUS_TEXT), m, m,
               r.right - 2 * m, (y - gap) - m, TRUE);
    x -= 84;  MoveWindow(GetDlgItem(h, IDC_STATUS_CLOSE), x, y, 84, bh, TRUE);
    x -= gap + bw; MoveWindow(GetDlgItem(h, IDC_STATUS_CLEAN), x, y, bw, bh, TRUE);
    x -= gap + bw; MoveWindow(GetDlgItem(h, IDC_STATUS_COPY),  x, y, bw, bh, TRUE);
}

static LRESULT CALLBACK StatusProc(HWND h, UINT msg, WPARAM wParam, LPARAM lParam) {
    switch (msg) {
    case WM_CREATE: {
        HINSTANCE inst = GetModuleHandleW(NULL);
        UINT dpi = 96;
        HDC dc = GetDC(NULL);
        if (dc) { dpi = GetDeviceCaps(dc, LOGPIXELSY); ReleaseDC(NULL, dc); }

        HWND e = CreateWindowExW(WS_EX_CLIENTEDGE, L"EDIT", L"",
                                 WS_CHILD | WS_VISIBLE | WS_VSCROLL | WS_TABSTOP |
                                 ES_MULTILINE | ES_READONLY | ES_AUTOVSCROLL,
                                 0, 0, 10, 10, h, (HMENU)(UINT_PTR)IDC_STATUS_TEXT, inst, NULL);
        g_statusFont = CreateFontW(-MulDiv(10, dpi, 72), 0, 0, 0, FW_NORMAL, 0, 0, 0,
                                   DEFAULT_CHARSET, OUT_DEFAULT_PRECIS, CLIP_DEFAULT_PRECIS,
                                   CLEARTYPE_QUALITY, FF_DONTCARE, UiFontName());
        if (e && g_statusFont) SendMessageW(e, WM_SETFONT, (WPARAM)g_statusFont, TRUE);
        if (e) SendMessageW(e, EM_SETMARGINS, EC_LEFTMARGIN | EC_RIGHTMARGIN, MAKELPARAM(10, 10));

        CreateWindowExW(0, L"BUTTON", T(L"复制全部", L"Copy all"),
                        WS_CHILD | WS_VISIBLE | WS_TABSTOP | BS_PUSHBUTTON,
                        0, 0, 10, 10, h, (HMENU)(UINT_PTR)IDC_STATUS_COPY, inst, NULL);
        CreateWindowExW(0, L"BUTTON", T(L"清理痕迹", L"Clean up"),
                        WS_CHILD | WS_VISIBLE | WS_TABSTOP | BS_PUSHBUTTON,
                        0, 0, 10, 10, h, (HMENU)(UINT_PTR)IDC_STATUS_CLEAN, inst, NULL);
        CreateWindowExW(0, L"BUTTON", T(L"关闭", L"Close"),
                        WS_CHILD | WS_VISIBLE | WS_TABSTOP | BS_PUSHBUTTON,
                        0, 0, 10, 10, h, (HMENU)(UINT_PTR)IDC_STATUS_CLOSE, inst, NULL);

        HFONT ui = (HFONT)GetStockObject(DEFAULT_GUI_FONT);
        SendDlgItemMessageW(h, IDC_STATUS_COPY,  WM_SETFONT, (WPARAM)ui, TRUE);
        SendDlgItemMessageW(h, IDC_STATUS_CLEAN, WM_SETFONT, (WPARAM)ui, TRUE);
        SendDlgItemMessageW(h, IDC_STATUS_CLOSE, WM_SETFONT, (WPARAM)ui, TRUE);

        RefreshStatus(h);
        return 0;
    }

    case WM_SIZE:
        LayoutStatus(h);
        return 0;

    case WM_GETMINMAXINFO: {
        MINMAXINFO *mm = (MINMAXINFO *)lParam;
        mm->ptMinTrackSize.x = 520;
        mm->ptMinTrackSize.y = 360;
        return 0;
    }

    case WM_COMMAND:
        switch (LOWORD(wParam)) {
        case IDC_STATUS_COPY:
            CopyToClipboard(h, ToCrlf(BuildFootprintReport(NULL, NULL)));
            break;
        case IDC_STATUS_CLEAN: {
            // The list refreshes in place, which is clearer feedback than a
            // second dialog on top of the report the user is already reading.
            CleanReport rep = CleanAll();
            RefreshStatus(h);
            SetWindowTextW(h, rep.Any()
                ? T(L"ExplorerF11 · 足迹报告（已清理）",
                    L"ExplorerF11 · footprint report (cleaned)")
                : T(L"ExplorerF11 · 足迹报告（本来就干净）",
                    L"ExplorerF11 · footprint report (already clean)"));
            break;
        }
        case IDC_STATUS_CLOSE:
            DestroyWindow(h);
            break;
        }
        return 0;

    case WM_CLOSE:
        DestroyWindow(h);
        return 0;

    case WM_DESTROY:
        if (g_statusFont) { DeleteObject(g_statusFont); g_statusFont = NULL; }
        g_status = NULL;
        return 0;
    }
    return DefWindowProcW(h, msg, wParam, lParam);
}

static void ShowStatusWindow(HWND owner) {
    if (g_status && IsWindow(g_status)) {
        RefreshStatus(g_status);
        SetForegroundWindow(g_status);
        return;
    }
    HINSTANCE inst = GetModuleHandleW(NULL);
    WNDCLASSW wc = {};
    wc.lpfnWndProc   = StatusProc;
    wc.hInstance     = inst;
    wc.lpszClassName = STATUS_CLASS;
    wc.hCursor       = LoadCursorW(NULL, IDC_ARROW);
    wc.hbrBackground = (HBRUSH)(COLOR_BTNFACE + 1);
    RegisterClassW(&wc);   // harmless if it already exists

    UINT dpi = 96;
    HDC dc = GetDC(NULL);
    if (dc) { dpi = GetDeviceCaps(dc, LOGPIXELSY); ReleaseDC(NULL, dc); }

    // Tall enough for the whole report on a normal screen, but never taller
    // than the work area (150% scaling on 1080p would otherwise overflow).
    int w = MulDiv(860, dpi, 96);
    int h = MulDiv(780, dpi, 96);
    RECT wa = {0, 0, 1920, 1080};
    SystemParametersInfoW(SPI_GETWORKAREA, 0, &wa, 0);
    int maxW = (wa.right - wa.left) - MulDiv(40, dpi, 96);
    int maxH = (wa.bottom - wa.top) - MulDiv(40, dpi, 96);
    if (w > maxW) w = maxW;
    if (h > maxH) h = maxH;

    // Centre inside the work area: CW_USEDEFAULT can drop the buttons under the
    // taskbar on a scaled display.
    int x = wa.left + ((wa.right - wa.left) - w) / 2;
    int y = wa.top + ((wa.bottom - wa.top) - h) / 2;

    g_status = CreateWindowExW(WS_EX_APPWINDOW, STATUS_CLASS,
                               T(L"ExplorerF11 · 足迹报告",
                                 L"ExplorerF11 · footprint report"),
                               WS_OVERLAPPEDWINDOW & ~WS_MAXIMIZEBOX,
                               x, y, w, h,
                               owner, NULL, inst, NULL);
    if (!g_status) return;
    ShowWindow(g_status, SW_SHOW);
    SetForegroundWindow(g_status);
}

// v4 wrote defaults into HKCU\Software\ExplorerF11Ultra and registered autostart
// under the old exe name. Both would be orphaned by the rename, so move them.
static void MigrateOldName() {
    bool hadAutostart = DeleteRunValue(OLD_RUN_VALUE);
    DeleteApproved(OLD_RUN_VALUE);   // its Windows flag would be orphaned too

    HKEY k;
    if (RegOpenKeyExW(HKEY_CURRENT_USER, OLD_CFG_KEY, 0, KEY_QUERY_VALUE, &k) == ERROR_SUCCESS) {
        bool hasTabs = false, hasInit = false;
        bool tabs = DEF_TABS, init = DEF_INITIAL;
        DWORD v = 0, cb = sizeof(v), type = 0;
        if (RegQueryValueExW(k, CFG_TABS, NULL, &type, (BYTE *)&v, &cb) == ERROR_SUCCESS
            && type == REG_DWORD) {
            hasTabs = true; tabs = v != 0;
        }
        cb = sizeof(v); type = 0;
        if (RegQueryValueExW(k, CFG_INITIAL, NULL, &type, (BYTE *)&v, &cb) == ERROR_SUCCESS
            && type == REG_DWORD) {
            hasInit = true; init = v != 0;
        }
        RegCloseKey(k);

        if (hasTabs) CfgWrite(CFG_TABS, tabs, DEF_TABS);
        if (hasInit) CfgWrite(CFG_INITIAL, init, DEF_INITIAL);
        RegDeleteKeyW(HKEY_CURRENT_USER, OLD_CFG_KEY);
    }

    if (hadAutostart) SetAutostart(true);   // repoint at the renamed exe
}

// ---------------------------------------------------------------- filters

static bool IsExplorerWindow(HWND h) {
    if (!h || !IsWindow(h)) return false;
    wchar_t cn[64] = {0};
    if (GetClassNameW(h, cn, 64) == 0 || wcscmp(cn, EXPLORER_CLASS) != 0) return false;
    // Control Panel shares CabinetWClass with real folder windows.
    wchar_t title[256] = {0};
    GetWindowTextW(h, title, 256);
    if (wcsstr(title, L"Control Panel") || wcsstr(title, L"\u63A7\u5236\u9762\u677F"))
        return false;
    return true;
}

static bool IsMarked(HWND h) { return GetPropW(h, PROP_MARK) != NULL; }
static void Mark(HWND h) {
    SetPropW(h, PROP_MARK, (HANDLE)1);
    SetPropW(h, PROP_TICK, (HANDLE)(ULONG_PTR)GetTickCount64());
}
static ULONG_PTR MarkedAt(HWND h) {
    return (ULONG_PTR)GetPropW(h, PROP_TICK);
}

// Heuristic: the F11 fullscreen state drops the caption.
static bool LooksFullscreen(HWND h) {
    LONG_PTR s = GetWindowLongPtrW(h, GWL_STYLE);
    return (s & WS_CAPTION) == 0;
}

// ---------------------------------------------------------------- core action

// Two complete F11 press/release cycles, posted asynchronously.
// Verified on 26H2 26300.9974: enters and exits fullscreen with lParam=0 too.
static int PostF11Raw(HWND h) {
    int ok = 0;
    if (PostMessageW(h, WM_KEYDOWN, VK_F11, 0)) ++ok;
    if (PostMessageW(h, WM_KEYUP,   VK_F11, 0)) ++ok;
    if (PostMessageW(h, WM_KEYDOWN, VK_F11, 0)) ++ok;
    if (PostMessageW(h, WM_KEYUP,   VK_F11, 0)) ++ok;
    return ok;
}

static bool Accelerate(HWND h, bool force) {
    if (!h || !IsWindow(h)) return false;
    if (IsIconic(h)) return false;          // never poke a minimized window
    if (!force && IsMarked(h)) return false;

    Mark(h);
    int ok = PostF11Raw(h);
    if (ok == 4) return true;

    // A partially delivered pair can leave the window in fullscreen.
    // Schedule a one-shot recovery that can only ever exit fullscreen.
    Log(L"partial post, scheduling recovery");
    g_risk = h;
    SetTimer(g_hwnd, RISK_TIMER, 500, NULL);
    return false;
}

struct SweepCtx {
    int n;        // windows actually accelerated
    int skipped;  // minimized -> must not be poked, handled on restore instead
    bool force;   // true = re-apply even to windows already handled
};

static BOOL CALLBACK EnumApplyProc(HWND h, LPARAM lp) {
    SweepCtx *c = (SweepCtx *)lp;
    if (!IsExplorerWindow(h)) return TRUE;
    if (IsIconic(h)) { ++(c->skipped); return TRUE; }
    if (Accelerate(h, c->force)) ++(c->n);
    return TRUE;
}

// New tabs are NOT top-level windows: pressing "+" only creates a
// ShellTabWindowClass child inside an already-existing window, so ShellHook
// never fires for it. This WinEvent hook catches that child creation and
// re-applies the pair to its owner window.
static void CALLBACK WinEventProc(HWINEVENTHOOK, DWORD event, HWND hwnd,
                                  LONG idObject, LONG idChild, DWORD, DWORD) {
    if (event != EVENT_OBJECT_CREATE || idObject != OBJID_WINDOW || idChild != 0)
        return;
    if (!hwnd) return;
    wchar_t cn[64];
    if (GetClassNameW(hwnd, cn, 64) == 0 || wcscmp(cn, TAB_CLASS) != 0) return;

    HWND parent = GetParent(hwnd);
    if (!parent || !IsMarked(parent)) return;   // only windows we already handle

    // The window's OWN first tab arrives right after we accelerate the window.
    // Treat anything inside 1.2 s as that first tab, not as a user action.
    ULONG_PTR now = (ULONG_PTR)GetTickCount64();
    ULONG_PTR last = MarkedAt(parent);
    if (now - last < 1200) return;

    if (g_paused || !g_tabs) return;
    if (Accelerate(parent, true)) Log(L"new tab: re-accelerated parent window");
}

// A window minimized when the tool started is skipped by the start-up sweep
// (poking a minimized window is unsafe). Catch it the moment it is restored.
static void CALLBACK RestoreProc(HWINEVENTHOOK, DWORD event, HWND hwnd,
                                 LONG idObject, LONG idChild, DWORD, DWORD) {
    if (event != EVENT_SYSTEM_MINIMIZEEND || idObject != OBJID_WINDOW || idChild != 0)
        return;
    if (!hwnd || g_paused || IsMarked(hwnd)) return;
    if (!IsExplorerWindow(hwnd)) return;
    if (Accelerate(hwnd, false)) Log(L"restored from minimized: accelerated");
}

// ---------------------------------------------------------------- tray

static HICON LoadTrayIcon() {
    SHSTOCKICONINFO sii = {};
    sii.cbSize = sizeof(sii);
    if (SUCCEEDED(SHGetStockIconInfo(SIID_FOLDER, SHGSI_ICON | SHGSI_SMALLICON, &sii))) {
        g_icon = sii.hIcon;   // owned by us -> DestroyIcon on exit
        return g_icon;
    }
    return LoadIconW(NULL, IDI_APPLICATION);
}

static std::wstring BuildTrayTip();   // defined below, needs the live state text

static void AddTray(HWND h) {
    if (!g_icon) LoadTrayIcon();   // once; also survives an explorer restart
    NOTIFYICONDATAW nid = {};
    nid.cbSize = sizeof(nid);
    nid.hWnd = h;
    nid.uID = TRAY_ID;
    nid.uFlags = NIF_ICON | NIF_MESSAGE | NIF_TIP;
    nid.uCallbackMessage = WM_TRAYICON;
    nid.hIcon = g_icon ? g_icon : LoadIconW(NULL, IDI_APPLICATION);
    wcsncpy_s(nid.szTip, BuildTrayTip().c_str(), _TRUNCATE);
    Shell_NotifyIconW(NIM_ADD, &nid);
}

// The tooltip answers "is it on, and what has it done" without opening the menu.
static void UpdateTrayTip() {
    if (!g_hwnd) return;
    NOTIFYICONDATAW nid = {};
    nid.cbSize = sizeof(nid);
    nid.hWnd = g_hwnd;
    nid.uID = TRAY_ID;
    nid.uFlags = NIF_TIP;
    wcsncpy_s(nid.szTip, BuildTrayTip().c_str(), _TRUNCATE);
    Shell_NotifyIconW(NIM_MODIFY, &nid);
}

// ---------------------------------------------------------------- language

// --lang and EXPLORERF11_LANG are per-run instructions and therefore beat the
// stored choice; the stored choice beats the machine locale, which is what
// makes a tray click survive a restart.
static void LoadLanguage() {
    Lang l;
    if (EnvLang(&l)) { SetLang(l); return; }
    std::wstring tag = CfgReadStr(CFG_LANG);
    if (ParseLang(tag.c_str(), &l)) { SetLang(l); return; }
    SetLang(LocaleLang());
}

// Store the choice only while it differs from the default, and delete the value
// when it returns: picking your own system language must leave nothing behind.
static void SaveLanguage(Lang l) {
    if (l == DefaultLang()) CfgWriteStr(CFG_LANG, std::wstring());
    else                    CfgWriteStr(CFG_LANG, LangTag(l));
}

// Applies a language to everything already on screen. The menu needs no help -
// it is rebuilt on every open - but the tooltip and an open report window do.
static void ApplyLanguage(Lang l) {
    SetLang(l);
    SaveLanguage(l);
    UpdateTrayTip();
    if (g_status && IsWindow(g_status)) RelocalizeStatus(g_status);
    Log(l == Lang::Zh ? L"language switched to zh" : L"language switched to en");
}

static void RemoveTray(HWND h) {
    NOTIFYICONDATAW nid = {};
    nid.cbSize = sizeof(nid);
    nid.hWnd = h;
    nid.uID = TRAY_ID;
    Shell_NotifyIconW(NIM_DELETE, &nid);
}

// The one definition of the live state. The tooltip and the menu header both
// call it, and the count itself lives in footprint.cpp, so the three surfaces
// that show "how many" cannot drift apart.
static std::wstring LiveStateText() {
    if (g_paused) return T(L"已暂停加速", L"paused");
    return AcceleratedText(MarkedWindows());
}

// Name, version and live state in two short lines - the tray tooltip is the
// only place a user sees the tool without opening anything.
static std::wstring BuildTrayTip() {
    std::wstring s = L"ExplorerF11 " EF11_VERSION;
    s += L"\n";
    s += LiveStateText();
    return s;
}

// The window "对当前窗口立即应用" would act on.
// GetForegroundWindow() is useless here: the tray click hands foreground to the
// taskbar, and our own SetForegroundWindow(h) hands it to this hidden window.
// So we remember the last folder window the shell reported as activated.
static bool IsLiveTarget(HWND t) {
    return IsExplorerWindow(t) && IsWindowVisible(t) && !IsIconic(t);
}

struct FindCtx { HWND found; };

static BOOL CALLBACK EnumFindProc(HWND h, LPARAM lp) {
    FindCtx *c = (FindCtx *)lp;
    if (!IsLiveTarget(h)) return TRUE;
    c->found = h;       // EnumWindows walks the z-order: first hit = frontmost
    return FALSE;
}

static HWND CurrentFolderTarget() {
    if (IsLiveTarget(g_lastFolder)) return g_lastFolder;
    HWND fg = GetForegroundWindow();
    if (IsLiveTarget(fg)) return fg;
    // Nothing was activated since start-up (fresh tray click, tool just launched).
    // Take the folder window nearest the front: that is the one in use.
    FindCtx c = {NULL};
    EnumWindows(EnumFindProc, (LPARAM)&c);
    return c.found;
}

// Menu layout, top to bottom:
//   header (grey, not clickable) | actions | settings | maintenance | exit
// Reading order is fixed: what you do often is highest, what cannot be undone
// is furthest from the pointer's resting place and never next to 退出.
// Settings read as states (ticked = on), never as verbs, and never carry an
// ellipsis: an ellipsis is reserved for the two items that open a window.
static HMENU BuildTrayMenu() {
    HMENU m = CreatePopupMenu();

    // Header: name + version + live state, so "is it working / is it paused"
    // needs no click and no memory.
    std::wstring state = LiveStateText();
    std::wstring head = L"ExplorerF11 " EF11_VERSION L"  \u00B7  " + state;
    AppendMenuW(m, MF_STRING | MF_GRAYED, 0, head.c_str());

    AppendMenuW(m, MF_SEPARATOR, 0, NULL);

    // --- actions: fix something now -------------------------------------
    AppendMenuW(m, MF_STRING, IDM_APPLY_ALL,
                T(L"\u5BF9\u6240\u6709\u5DF2\u6253\u5F00\u7684\u7A97\u53E3\u5E94\u7528",
                  L"Apply to all open windows"));
    HWND target = CurrentFolderTarget();
    AppendMenuW(m, MF_STRING | (target ? MF_ENABLED : MF_GRAYED), IDM_APPLY,
                T(L"\u5BF9\u5F53\u524D\u7A97\u53E3\u7ACB\u5373\u5E94\u7528",
                  L"Apply to the active window"));
    if (g_log) {
        wchar_t a[64] = {0}, b[64] = {0};
        GetClassNameW(g_lastFolder, a, 64);
        GetClassNameW(GetForegroundWindow(), b, 64);
        wchar_t dbg[256];
        swprintf_s(dbg, L"menu: last=%p(%s) fg(%s) -> apply %s",
                   (void *)g_lastFolder, a, b, target ? L"on" : L"off");
        Log(dbg);
    }
    AppendMenuW(m, MF_STRING, IDM_PAUSE,
                g_paused ? T(L"\u6062\u590D\u52A0\u901F", L"Resume acceleration")
                         : T(L"\u6682\u505C\u52A0\u901F", L"Pause acceleration"));

    AppendMenuW(m, MF_SEPARATOR, 0, NULL);

    // --- settings: ticked = on, no ellipsis, no verb --------------------
    AppendMenuW(m, MF_STRING | (g_tabs ? MF_CHECKED : MF_UNCHECKED),
                IDM_TABS, T(L"\u65B0\u5EFA\u9009\u9879\u5361\u65F6\u91CD\u65B0\u52A0\u901F\u7A97\u53E3",
                            L"Re-accelerate the window on new tabs"));
    AppendMenuW(m, MF_STRING | (g_initial ? MF_CHECKED : MF_UNCHECKED),
                IDM_INITIAL,
                T(L"\u542F\u52A8\u65F6\u5904\u7406\u5DF2\u6253\u5F00\u7684\u7A97\u53E3",
                  L"Accelerate windows open at start-up"));
    AppendMenuW(m, MF_STRING | (IsAutostartEnabled() ? MF_CHECKED : MF_UNCHECKED),
                IDM_AUTOSTART, T(L"\u5F00\u673A\u81EA\u542F", L"Start with Windows"));

    // Language is a state with three possible sources, so it lives in a
    // submenu: two radio rows, each written in its own language, so the menu
    // stays usable even after switching to one you do not read.
    {
        HMENU lang = CreatePopupMenu();
        AppendMenuW(lang, MF_STRING, IDM_LANG_ZH, L"\u4E2D\u6587\uFF08\u7B80\u4F53\uFF09");
        AppendMenuW(lang, MF_STRING, IDM_LANG_EN, L"English");
        CheckMenuRadioItem(lang, 0, 1, IsZh() ? 0 : 1, MF_BYPOSITION);
        AppendMenuW(m, MF_STRING | MF_POPUP, (UINT_PTR)lang,
                    T(L"\u754C\u9762\u8BED\u8A00", L"Language"));
    }

    AppendMenuW(m, MF_SEPARATOR, 0, NULL);

    // --- maintenance: footprint first (read-only), then the destructive one
    {
        // The count is shown right in the menu, so "how dirty is it" is visible
        // without opening anything. Totals only: building the whole report just
        // to print a number would scan everything twice.
        FootprintTotals t = CurrentTotals();
        std::wstring label;
        if (!t.Clean())
            label = T(L"足迹报告（", L"Footprint report (") +
                    FormatItemCount(t.Total()) + T(L"）…", L")\u2026");
        else
            label = T(L"足迹报告（干净）…", L"Footprint report (clean)\u2026");
        AppendMenuW(m, MF_STRING, IDM_STATUS, label.c_str());
    }
    AppendMenuW(m, MF_STRING, IDM_CLEAN,
                T(L"\u6E05\u9664\u5168\u90E8\u75D5\u8FF9\u5E76\u9000\u51FA\u2026",
                  L"Clear all traces and exit\u2026"));

    AppendMenuW(m, MF_SEPARATOR, 0, NULL);

    // --- exit: always last, always alone -------------------------------
    AppendMenuW(m, MF_STRING, IDM_EXIT, T(L"\u9000\u51FA", L"Exit"));
    return m;
}

static void ShowMenu(HWND h) {
    POINT p;
    GetCursorPos(&p);
    HMENU m = BuildTrayMenu();
    SetForegroundWindow(h);
    TrackPopupMenu(m, TPM_RIGHTBUTTON, p.x, p.y, 0, h, NULL);
    PostMessageW(h, WM_NULL, 0, 0);
    DestroyMenu(m);
}

// --menu: dump the real menu (same builder the right click uses) so the order,
// the ticks and the submenu contents can be asserted in a test instead of
// eyeballed. Submenu rows are indented by four spaces under a "[>]" parent.
static void DumpMenu(HMENU m, const std::wstring &indent, std::wstring *out) {
    int n = m ? GetMenuItemCount(m) : 0;
    for (int i = 0; i < n; ++i) {
        UINT st = GetMenuState(m, i, MF_BYPOSITION);
        if (st == (UINT)-1 || (st & MF_SEPARATOR)) { *out += indent + L"----\n"; continue; }

        HMENU sub = GetSubMenu(m, i);
        *out += indent;
        if (sub)                 *out += L"[>] ";
        else if (st & MF_CHECKED) *out += L"[\u2713] ";
        else if (st & MF_GRAYED)  *out += L"[x] ";
        else                      *out += L"[ ] ";

        wchar_t txt[256] = {0};
        GetMenuStringW(m, i, txt, 256, MF_BYPOSITION);
        *out += txt;
        *out += L"\n";
        if (sub) DumpMenu(sub, indent + L"    ", out);
    }
}

static std::wstring MenuDump() {
    std::wstring s;
    HMENU m = BuildTrayMenu();
    DumpMenu(m, L"", &s);
    if (m) DestroyMenu(m);
    return s;
}

// Last-resort recovery: some builds refuse a second shell-hook registration in
// the same process. A fresh instance costs ~1.7 MB private and always works.
static void RelaunchSelf() {
    if (g_mux) {                       // release the mutex BEFORE spawning
        CloseHandle(g_mux);
        g_mux = NULL;
    }
    // Re-use our own command line verbatim, so every flag survives the relaunch.
    std::wstring cmd = GetCommandLineW();
    if (!cmd.empty()) {
        STARTUPINFOW si = {};
        si.cb = sizeof(si);
        PROCESS_INFORMATION pi = {};
        if (CreateProcessW(NULL, cmd.data(), NULL, NULL, FALSE, 0, NULL, NULL, &si, &pi)) {
            CloseHandle(pi.hProcess);
            CloseHandle(pi.hThread);
        }
    }
    DestroyWindow(g_hwnd);
}

// ---------------------------------------------------------------- window proc

static LRESULT CALLBACK WndProc(HWND h, UINT msg, WPARAM wParam, LPARAM lParam) {
    if (msg == g_taskbarCreatedMsg && g_taskbarCreatedMsg) {
        // explorer.exe restarted: our shell hook registration AND tray icon are gone.
        // Re-registering on an already-registered window fails, so clear it first.
        DeregisterShellHookWindow(h);
        BOOL ok = RegisterShellHookWindow(h);
        DWORD err = GetLastError();
        if (ok) {
            Log(L"explorer restarted: shell hook re-registered");
        } else {
            wchar_t line[128];
            swprintf_s(line, L"re-register failed (err=%lu), relaunching", err);
            Log(line);
            RelaunchSelf();
        }
        RemoveTray(h);
        AddTray(h);
        return 0;
    }

    if (msg == g_shellHookMsg && g_shellHookMsg) {
        if (wParam == HSHELL_WINDOWCREATED) {
            HWND target = reinterpret_cast<HWND>(lParam);
            if (!g_paused && IsExplorerWindow(target) && Accelerate(target, false)) {
                wchar_t title[256] = {0};
                GetWindowTextW(target, title, 256);
                std::wstring line = L"accelerated: ";
                line += title;
                Log(line.c_str());
            }
        } else if (wParam == HSHELL_WINDOWACTIVATED || wParam == HSHELL_RUDEAPPACTIVATED) {
            // Remember the last folder window the user worked in; the tray menu
            // needs it because at click time the foreground is the taskbar.
            HWND a = reinterpret_cast<HWND>(lParam);
            if (IsExplorerWindow(a)) g_lastFolder = a;
        }
        return 0;
    }

    switch (msg) {
    case WM_CREATE:
        g_hwnd = h;
        if (IsExplorerWindow(GetForegroundWindow()))   // until an activation fires
            g_lastFolder = GetForegroundWindow();
        g_shellHookMsg = RegisterWindowMessageW(L"SHELLHOOK");
        g_taskbarCreatedMsg = RegisterWindowMessageW(L"TaskbarCreated");
        if (!RegisterShellHookWindow(h)) {
            Log(L"RegisterShellHookWindow failed");
            Say(T(L"无法向 Shell 注册事件通知，因此本程序收不到窗口事件，也就无法工作。\n\n"
                  L"请注销后重新登录，然后再运行一次。",
                  L"Could not register for shell event notifications, so the tool receives "
                  L"no window events and cannot work.\n\n"
                  L"Sign out and back in, then run it again."), MB_ICONERROR);
            return -1;
        }
        AddTray(h);
        g_winEvent = SetWinEventHook(EVENT_OBJECT_CREATE, EVENT_OBJECT_CREATE, NULL,
                                     WinEventProc, 0, 0,
                                     WINEVENT_OUTOFCONTEXT | WINEVENT_SKIPOWNPROCESS);
        g_winEvent2 = SetWinEventHook(EVENT_SYSTEM_MINIMIZEEND, EVENT_SYSTEM_MINIMIZEEND,
                                      NULL, RestoreProc, 0, 0,
                                      WINEVENT_OUTOFCONTEXT | WINEVENT_SKIPOWNPROCESS);
        Log(g_winEvent ? L"started (tab hook ok)" : L"started (tab hook FAILED)");
        if (g_initial) PostMessageW(h, WM_APP_INITIAL, 0, 0);
        return 0;

    case WM_APP_INITIAL: {
        // Windows opened before this tool started never fire HSHELL_WINDOWCREATED.
        // Windows already carrying our mark are left alone: the property survives
        // process exit, so they are still in the accelerated state.
        SweepCtx c = {0, 0, false};
        EnumWindows(EnumApplyProc, (LPARAM)&c);
        wchar_t line[96];
        swprintf_s(line, L"initial sweep: %d applied, %d minimized",
                   c.n, c.skipped);
        Log(line);
        return 0;
    }

    case WM_TIMER:
        if (wParam == RISK_TIMER) {
            KillTimer(h, RISK_TIMER);
            HWND r = g_risk;
            g_risk = NULL;
            if (r && IsWindow(r)) {
                if (LooksFullscreen(r)) {
                    PostMessageW(r, WM_KEYDOWN, VK_F11, 0);
                    PostMessageW(r, WM_KEYUP,   VK_F11, 0);
                    Log(L"recovery: exited stuck fullscreen");
                }
                // The pair never landed, so this window is NOT accelerated.
                // Drop the mark: a later start-up sweep, restore or apply-all
                // can retry it. Leaving it marked would hide it forever.
                RemovePropW(r, PROP_MARK);
                RemovePropW(r, PROP_TICK);
            }
        }
        return 0;

    case WM_TRAYICON:
        if (lParam == WM_RBUTTONUP || lParam == WM_LBUTTONUP) ShowMenu(h);
        return 0;

    case WM_COMMAND:
        switch (LOWORD(wParam)) {
        case IDM_LANG_ZH:
            ApplyLanguage(Lang::Zh);
            break;
        case IDM_LANG_EN:
            ApplyLanguage(Lang::En);
            break;
        case IDM_PAUSE:
            g_paused = !g_paused;
            UpdateTrayTip();
            Log(g_paused ? L"paused" : L"resumed");
            break;
        case IDM_APPLY: {
            // Never post F11 to whatever happens to be in front: this must be a
            // folder window, or a browser/editor in focus would get toggled.
            HWND t = CurrentFolderTarget();
            if (!t) {
                Log(L"manual apply: no folder window to act on");
                break;
            }
            if (Accelerate(t, true)) Log(L"manual apply: last active folder window");
            UpdateTrayTip();
            break;
        }
        case IDM_APPLY_ALL: {
            SweepCtx c = {0, 0, true};   // explicit request: re-apply to everything
            EnumWindows(EnumApplyProc, (LPARAM)&c);
            wchar_t buf[96];
            swprintf_s(buf, L"apply-all: %d applied, %d minimized", c.n, c.skipped);
            Log(buf);
            UpdateTrayTip();
            break;
        }
        case IDM_STATUS:
            ShowStatusWindow(h);
            break;
        case IDM_AUTOSTART: {
            bool on = !IsAutostartEnabled();
            SetAutostart(on);
            Log(on ? L"autostart on" : L"autostart off");
            break;
        }
        case IDM_TABS:
            g_tabs = !g_tabs;
            CfgWrite(CFG_TABS, g_tabs, DEF_TABS);
            Log(g_tabs ? L"new-tab acceleration on (default, nothing stored)"
                       : L"new-tab acceleration off (stored)");
            break;
        case IDM_INITIAL:
            g_initial = !g_initial;
            CfgWrite(CFG_INITIAL, g_initial, DEF_INITIAL);
            Log(g_initial ? L"start-up sweep on (default, nothing stored)"
                          : L"start-up sweep off (stored)");
            break;
        case IDM_CLEAN: {
            if (Say(T(L"将删除本程序留下的全部可清理痕迹：\n\n"
                       L"  · 设置键 HKCU\\Software\\ExplorerF11\n"
                       L"  · 开机自启项，以及任务管理器为它记的启动开关\n"
                       L"  · 日志文件\n"
                       L"  · Windows 为它记的托盘图标、兼容性、应用名、启动次数与预读取条目\n\n"
                       L"程序本体不会被删除。完成后本程序退出，下次启动回到全部默认设置。"
                       L"确定继续？",
                       L"Every removable trace of this program will be deleted:\n\n"
                       L"  - settings key HKCU\\Software\\ExplorerF11\n"
                       L"  - the autostart entry and the startup flag Task Manager kept for it\n"
                       L"  - the log file\n"
                       L"  - the tray icon, compatibility, friendly-name, launch-count and "
                       L"Prefetch records Windows kept for it\n\n"
                       L"The exe itself is not deleted. The tool then exits, and the next start "
                       L"is back to defaults. Continue?"),
                    MB_ICONQUESTION | MB_YESNO) != IDYES)
                break;
            CleanReport rep = CleanAll();
            Log(L"registry cleaned");
            RemoveTray(h);
            ShowCleanReport(rep);
            DestroyWindow(h);
            break;
        }
        case IDM_EXIT:
            DestroyWindow(h);
            break;
        }
        return 0;

    case WM_ENDSESSION:
        RemoveTray(h);
        return 0;

    case WM_DESTROY:
        if (g_winEvent) {
            UnhookWinEvent(g_winEvent);
            g_winEvent = NULL;
        }
        if (g_winEvent2) {
            UnhookWinEvent(g_winEvent2);
            g_winEvent2 = NULL;
        }
        if (g_icon) {
            DestroyIcon(g_icon);
            g_icon = NULL;
        }
        DeregisterShellHookWindow(h);
        RemoveTray(h);
        Log(L"stopped");
        PostQuitMessage(0);
        return 0;

    default:
        break;
    }

    return DefWindowProcW(h, msg, wParam, lParam);
}

// ---------------------------------------------------------------- entry

// Ask a running instance to exit, so --clean cannot be undone by a live process.
static void CloseRunningInstance() {
    HWND h = FindWindowW(WINDOW_CLASS, NULL);
    if (!h) return;
    PostMessageW(h, WM_CLOSE, 0, 0);
    for (int i = 0; i < 20 && IsWindow(h); ++i) Sleep(50);
}

// Console output for --status / --menu. This is a -mwindows binary, so it owns
// no console; the handle is resolved in the order that covers every way the
// program can be started:
//   1. an inherited pipe or file — a script, a build step, `--status > out.txt`;
//   2. the console of whoever started us — a shell, Explorer, a shortcut;
//   3. the screen buffer of the console we are attached to, if the environment
//      attached us but passed no inheritable handle.
// Trying the inherited handle first matters: a redirecting parent sets it, and
// losing it would silently drop the whole report into an invisible console.
static HANDLE ConsoleOut() {
    HANDLE h = GetStdHandle(STD_OUTPUT_HANDLE);
    if (h && h != INVALID_HANDLE_VALUE) return h;
    if (AttachConsole(ATTACH_PARENT_PROCESS)) {
        h = GetStdHandle(STD_OUTPUT_HANDLE);
        if (h && h != INVALID_HANDLE_VALUE) return h;
    }
    return CreateFileW(L"CONOUT$", GENERIC_WRITE, FILE_SHARE_WRITE | FILE_SHARE_READ,
                       NULL, OPEN_EXISTING, 0, NULL);
}

// Writes as wide characters to a console (correct code page, no transcoding) and
// as UTF-8 to a pipe or a file. Returns false only when there is no output at
// all, which is the caller's cue to fall back to a dialog.
static bool Emit(const std::wstring &text) {
    HANDLE out = ConsoleOut();
    if (!out || out == INVALID_HANDLE_VALUE) return false;
    DWORD n = 0;
    if (WriteConsoleW(out, text.c_str(), (DWORD)text.size(), &n, NULL)) return true;
    int need = WideCharToMultiByte(CP_UTF8, 0, text.c_str(), (int)text.size(),
                                   NULL, 0, NULL, NULL);
    if (need <= 0) return false;
    std::string a((size_t)need, '\0');
    WideCharToMultiByte(CP_UTF8, 0, text.c_str(), (int)text.size(),
                        &a[0], need, NULL, NULL);
    return WriteFile(out, a.data(), (DWORD)a.size(), &n, NULL) != 0;
}

// Text behind --help. Kept next to the parser so a new flag cannot be documented
// in one language and forgotten in the other.
static std::wstring UsageText() {
    std::wstring s;
    s += L"ExplorerF11 " EF11_VERSION;
    s += T(L" — 让 Windows 11 资源管理器变快\n\n", L" - accelerate Windows 11 File Explorer\n\n");
    s += T(L"用法：ExplorerF11.exe [选项]\n\n", L"Usage: ExplorerF11.exe [options]\n\n");
    s += T(L"选项：\n", L"Options:\n");
    s += T(
        L"  （无参数）        在托盘运行，自动加速之后打开的文件夹窗口\n"
        L"  --install         在托盘运行，并勾选开机自启\n"
        L"  --uninstall       只删除开机自启项，其他一切不动\n"
        L"  --status          打印完整足迹报告；退出码 0 = 干净，1 = 有可清理项\n"
        L"  --clean, --purge  删除全部可清理痕迹后退出（会先关闭正在运行的实例）\n"
        L"  --menu            把托盘菜单按文本打印出来（供测试与排查）\n"
        L"  --lang zh|en      本次运行的界面语言\n"
        L"  --log             把运行日志写到 %TEMP%\\ExplorerF11.log\n"
        L"  --no-initial      不处理本次启动前已经打开的窗口\n"
        L"  --quiet           不弹任何对话框（脚本用）\n"
        L"  --version, -v     打印版本号\n"
        L"  --help, -h        打印这段说明\n\n",
        L"  (none)            run in the tray, accelerate folder windows opened later\n"
        L"  --install         run in the tray and tick \"Start with Windows\"\n"
        L"  --uninstall       remove the autostart entry only, nothing else\n"
        L"  --status          print the full footprint report; exit 0 = clean, 1 = traces\n"
        L"  --clean, --purge  remove every removable trace, then exit (closes a running copy)\n"
        L"  --menu            print the tray menu as text (tests and troubleshooting)\n"
        L"  --lang zh|en      UI language for this run\n"
        L"  --log             write %TEMP%\\ExplorerF11.log\n"
        L"  --no-initial      leave windows that were already open alone\n"
        L"  --quiet           never show a message box (for scripts)\n"
        L"  --version, -v     print the version\n"
        L"  --help, -h        print this help\n\n");
    s += T(
        L"语言：--lang 优先，其次环境变量 EXPLORERF11_LANG，再次托盘菜单里的选择，\n"
        L"      最后跟随系统语言。托盘里的选择会被保存；选回系统语言即删除保存值。\n\n"
        L"足迹：默认配置不写注册表、不建文件。只有把某个开关改成非默认值、勾选\n"
        L"      开机自启或切换界面语言时才会写入，改回默认即删除。--status 列出\n"
        L"      全部可能位置（含 Windows 自动记录的那些），--clean 清零。程序本体\n"
        L"      不算痕迹，要彻底卸载请自行删除 ExplorerF11.exe。\n\n"
        L"单位：加速以窗口为单位，不以选项卡为单位 —— F11 由窗口框架处理，一次往返对\n"
        L"      该窗口内的全部选项卡同时生效，选项卡不会单独加速。状态行括号里是这些\n"
        L"      窗口当前包含的选项卡数。\n\n"
        L"示例：\n"
        L"  ExplorerF11.exe --install              安装，并在登录时启动\n"
        L"  ExplorerF11.exe --status --lang en     用英文核对足迹\n"
        L"  ExplorerF11.exe --clean --quiet        在脚本里静默清空全部痕迹\n",
        L"Language: --lang first, then EXPLORERF11_LANG, then the choice made in the tray\n"
        L"      menu, then the system language. The tray choice is stored; picking the\n"
        L"      system language again deletes the stored value.\n\n"
        L"Footprint: the default configuration writes no registry value and no file. A\n"
        L"      value appears only when a setting leaves its default, when autostart is\n"
        L"      ticked, or when the UI language is switched; returning to the default\n"
        L"      deletes it. --status lists every possible location (including the ones\n"
        L"      Windows records on its own), --clean zeroes them. The exe is not a trace:\n"
        L"      delete ExplorerF11.exe yourself for a full uninstall.\n\n"
        L"Unit: acceleration is counted in windows, not in tabs - F11 is handled by the\n"
        L"      window frame, so one round trip covers every tab in that window at once,\n"
        L"      and a tab is never accelerated on its own. The bracketed figure is how many\n"
        L"      tabs those windows currently hold.\n\n"
        L"Examples:\n"
        L"  ExplorerF11.exe --install              install, and start at logon\n"
        L"  ExplorerF11.exe --status --lang en     check the footprint in English\n"
        L"  ExplorerF11.exe --clean --quiet        clear everything silently from a script\n");
    return s;
}

int WINAPI wWinMain(HINSTANCE hInst, HINSTANCE, PWSTR, int) {
    bool wantInstall = false, wantUninstall = false, wantClean = false;
    bool wantStatus = false, wantMenu = false;
    bool wantHelp = false, wantVersion = false;
    int argc = 0;
    LPWSTR *argv = CommandLineToArgvW(GetCommandLineW(), &argc);
    if (argv) {
        for (int i = 1; i < argc; ++i) {
            if (_wcsicmp(argv[i], L"--log") == 0)             g_log = true;
            else if (_wcsicmp(argv[i], L"--install") == 0)    wantInstall = true;
            else if (_wcsicmp(argv[i], L"--uninstall") == 0)  wantUninstall = true;
            else if (_wcsicmp(argv[i], L"--clean") == 0)      wantClean = true;
            else if (_wcsicmp(argv[i], L"--purge") == 0)      wantClean = true;
            else if (_wcsicmp(argv[i], L"--status") == 0)     wantStatus = true;
            else if (_wcsicmp(argv[i], L"--menu") == 0)       wantMenu = true;
            else if (_wcsicmp(argv[i], L"--quiet") == 0)      g_quiet = true;
            else if (_wcsicmp(argv[i], L"--no-initial") == 0) g_initial = false;  // this run only
            else if (_wcsicmp(argv[i], L"--help") == 0 ||
                     _wcsicmp(argv[i], L"-h") == 0 ||
                     _wcsicmp(argv[i], L"/?") == 0)            wantHelp = true;
            else if (_wcsicmp(argv[i], L"--version") == 0 ||
                     _wcsicmp(argv[i], L"-v") == 0)            wantVersion = true;
            else if (_wcsicmp(argv[i], L"--lang") == 0 && i + 1 < argc) {
                Lang l;
                if (ParseLang(argv[++i], &l)) { SetLang(l); g_langExplicit = true; }
            } else if (_wcsnicmp(argv[i], L"--lang=", 7) == 0) {
                Lang l;
                if (ParseLang(argv[i] + 7, &l)) { SetLang(l); g_langExplicit = true; }
            }
        }
        LocalFree(argv);
    }

    // Language: --lang wins, then EXPLORERF11_LANG, then the stored tray choice,
    // then the system locale. LoadLanguage only runs when nothing was chosen on
    // the command line.
    if (!g_langExplicit) LoadLanguage();

    if (wantVersion) {
        std::wstring v = std::wstring(L"ExplorerF11 ") + EF11_VERSION + L"\n";
        if (!Emit(v)) Say(v.c_str(), MB_ICONINFORMATION);
        return 0;
    }

    if (wantHelp) {
        std::wstring h = UsageText();
        if (!Emit(h)) Say(h.c_str(), MB_ICONINFORMATION);
        return 0;
    }

    if (wantMenu) {
        g_tabs    = CfgRead(CFG_TABS, DEF_TABS);          // read-only, so the dump
        g_initial = CfgRead(CFG_INITIAL, DEF_INITIAL);    // shows the real ticks
        std::wstring d = MenuDump();
        if (!Emit(d)) Say(d.c_str(), MB_ICONINFORMATION);
        return 0;
    }

    // --status: print the footprint report and use the exit code as the verdict
    // (0 = clean, 1 = something is there). Read-only; works with or without a
    // console, and never blocks a script with a dialog unless there is no stdout.
    if (wantStatus) {
        int places = 0;
        DWORD bytes = 0;
        std::wstring report = BuildFootprintReport(&places, &bytes);
        if (!Emit(report)) Say(report.c_str(), MB_ICONINFORMATION);
        return places ? 1 : 0;
    }

    if (wantClean) {
        CloseRunningInstance();
        ShowCleanReport(CleanAll());
        return 0;
    }

    if (wantUninstall) {
        SetAutostart(false);
        Say(T(L"已删除开机自启项。\n\n"
              L"程序本体与其他痕迹都还在。要全部清除，运行：\n"
              L"    ExplorerF11.exe --clean",
              L"Autostart entry removed.\n\n"
              L"The exe and the remaining traces are still there. To clear everything, run:\n"
              L"    ExplorerF11.exe --clean"), MB_ICONINFORMATION);
        return 0;
    }

    g_mux = CreateMutexW(NULL, FALSE, MUTEX_NAME);
    if (g_mux && GetLastError() == ERROR_ALREADY_EXISTS) {
        CloseHandle(g_mux);
        return 0;   // already running
    }

    // Preferences live in the registry (not on the command line) so they survive
    // both autostart and self-relaunch, neither of which passes arguments.
    MigrateOldName();
    g_tabs    = CfgRead(CFG_TABS, DEF_TABS);
    g_initial = CfgRead(CFG_INITIAL, DEF_INITIAL);

    if (wantInstall) SetAutostart(true);

    WNDCLASSW wc = {};
    wc.lpfnWndProc = WndProc;
    wc.hInstance = hInst;
    wc.lpszClassName = WINDOW_CLASS;
    if (!RegisterClassW(&wc)) return 1;

    // Hidden TOP-LEVEL window (no WS_VISIBLE, no parent) -> invisible, but still
    // eligible for broadcast messages such as TaskbarCreated.
    HWND h = CreateWindowExW(0, wc.lpszClassName, APP_NAME, 0,
                             0, 0, 0, 0, NULL, NULL, hInst, NULL);
    if (!h) return 2;

    MSG msg;
    while (GetMessageW(&msg, NULL, 0, 0) > 0) {
        TranslateMessage(&msg);
        DispatchMessageW(&msg);
    }

    if (g_mux) CloseHandle(g_mux);
    return 0;
}
