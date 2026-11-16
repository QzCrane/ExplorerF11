// Baseline floor for the memory comparison.
//
// Links with the same flags as ExplorerF11 (-static, -municode, -mwindows) and
// does progressively more of what the real program does, so the private bytes
// of each step can be attributed: CRT + user32 first, then the shell (which is
// what drags in windows.storage, combase and WindowsCodecs), then the registry
// and window APIs the residue scan uses.
//
//   mem_floor.exe 0   message loop only
//   mem_floor.exe 1   + tray icon (shell32, its dependency tree, GDI icon)
//   mem_floor.exe 2   + one residue-style registry + window walk
//
// Prints its own private bytes after settling, then exits.

#define WIN32_LEAN_AND_MEAN
#ifndef UNICODE
#define UNICODE
#endif
#ifndef _UNICODE
#define _UNICODE
#endif
#include <windows.h>
#include <shellapi.h>   // NOTIFYICONDATAW lives here, not in shellapi's sibling
#include <psapi.h>
#include <cstdio>
#include <string>
#include <vector>

static const UINT WM_TRAYICON = WM_APP + 1;
static const UINT TRAY_ID = 1;

static void ReportPrivate(const char *label) {
    PROCESS_MEMORY_COUNTERS_EX mc = {};
    if (GetProcessMemoryInfo(GetCurrentProcess(), (PROCESS_MEMORY_COUNTERS *)&mc,
                             sizeof(mc))) {
        std::printf("%-34s private %6llu KB  peak ws %6llu KB\n", label,
                    (unsigned long long)(mc.PrivateUsage / 1024),
                    (unsigned long long)(mc.PeakWorkingSetSize / 1024));
    }
}

static HICON MakeIcon() {
    // A 16x16 monochrome icon built in memory: same shape of work the tray icon
    // does (CreateIconIndirect), without shipping a resource file.
    static BYTE AND[16 * 2] = {};
    static BYTE XOR[16 * 2] = {};
    for (int i = 0; i < 16 * 2; ++i) XOR[i] = (BYTE)(i & 0x0F ? 0xFF : 0x00);
    HBITMAP andBmp = CreateBitmap(16, 16, 1, 1, AND);
    HBITMAP xorBmp = CreateBitmap(16, 16, 1, 1, XOR);
    ICONINFO ii = {};
    ii.fIcon = TRUE;
    ii.hbmMask = andBmp;
    ii.hbmColor = xorBmp;
    HICON icon = CreateIconIndirect(&ii);
    DeleteObject(andBmp);
    DeleteObject(xorBmp);
    return icon;
}

static LRESULT CALLBACK WndProc(HWND h, UINT m, WPARAM w, LPARAM l) {
    if (m == WM_TRAYICON) return 0;
    return DefWindowProcW(h, m, w, l);
}

int wmain(int argc, wchar_t **argv) {
    const int level = (argc > 1) ? _wtoi(argv[1]) : 0;

    WNDCLASSEXW wc = {};
    wc.cbSize = sizeof(wc);
    wc.lpfnWndProc = WndProc;
    wc.hInstance = GetModuleHandleW(NULL);
    wc.lpszClassName = L"MemFloorClass";
    RegisterClassExW(&wc);

    HWND h = CreateWindowExW(0, L"MemFloorClass", L"memfloor", 0, 0, 0, 0, 0,
                             HWND_MESSAGE, NULL, wc.hInstance, NULL);
    ReportPrivate("after window");

    if (level >= 1) {
        HICON icon = MakeIcon();
        NOTIFYICONDATAW nid = {};
        nid.cbSize = sizeof(nid);
        nid.hWnd = h;
        nid.uID = TRAY_ID;
        nid.uFlags = NIF_ICON | NIF_MESSAGE | NIF_TIP | NIF_SHOWTIP;
        nid.uCallbackMessage = WM_TRAYICON;
        nid.hIcon = icon;
        wcscpy_s(nid.szTip, L"memfloor");
        Shell_NotifyIconW(NIM_ADD, &nid);
        NOTIFYICON_VERSION_4;
        Shell_NotifyIconW(NIM_SETVERSION, &nid);
        ReportPrivate("after tray icon");
    }

    if (level >= 2) {
        // One pass of the shape the residue scan uses.
        std::vector<std::wstring> rows;
        HKEY k;
        if (RegOpenKeyExW(HKEY_CURRENT_USER,
                          L"Software\\Microsoft\\Windows\\CurrentVersion\\Explorer",
                          0, KEY_READ, &k) == ERROR_SUCCESS) {
            for (DWORD i = 0; i < 30; ++i) {
                wchar_t name[256];
                DWORD cch = 256;
                if (RegEnumKeyExW(k, i, name, &cch, NULL, NULL, NULL, NULL) != ERROR_SUCCESS)
                    break;
                rows.push_back(name);
            }
            RegCloseKey(k);
        }
        int windows = 0;
        EnumWindows([](HWND w, LPARAM p) -> BOOL {
            ++*(int *)p;
            return TRUE;
        }, (LPARAM)&windows);
        std::printf("%-34s (%zu keys, %d windows)\n", "scan", rows.size(), windows);
        ReportPrivate("after registry + window walk");
    }

    if (level >= 3 && level <= 6) {
        WNDCLASSEXW st = {};
        st.cbSize = sizeof(st);
        st.lpfnWndProc = WndProc;
        st.hInstance = GetModuleHandleW(NULL);
        st.lpszClassName = L"MemFloorStatus";
        st.hCursor = LoadCursorW(NULL, IDC_ARROW);
        st.hbrBackground = (HBRUSH)(COLOR_BTNFACE + 1);
        RegisterClassExW(&st);

        HWND w = CreateWindowExW(WS_EX_APPWINDOW, L"MemFloorStatus", L"report",
                                 WS_OVERLAPPEDWINDOW, 0, 0, 560, 420, NULL, NULL,
                                 st.hInstance, NULL);
        HDC dc = GetDC(NULL);
        int dpi = GetDeviceCaps(dc, LOGPIXELSY);
        ReleaseDC(NULL, dc);
        // Level 4 asks whether the stock UI font is enough. If the window's cost
        // collapses without CreateFontW, the font handle is what drags in a face
        // file; if it does not, the cost is the window and its controls, and no
        // amount of font juggling will help.
        HFONT f = NULL;
        if (level == 4)
            f = (HFONT)GetStockObject(DEFAULT_GUI_FONT);
        else
            f = CreateFontW(-MulDiv(10, dpi, 72), 0, 0, 0, FW_NORMAL, 0, 0, 0,
                            DEFAULT_CHARSET, OUT_DEFAULT_PRECIS, CLIP_DEFAULT_PRECIS,
                            CLEARTYPE_QUALITY, DEFAULT_PITCH | FF_DONTCARE, L"Segoe UI");
        HWND e = (level == 6) ? NULL : CreateWindowExW(WS_EX_CLIENTEDGE, L"EDIT", L"",
                                 WS_CHILD | WS_VISIBLE | WS_VSCROLL | ES_MULTILINE |
                                 ES_READONLY | ES_AUTOVSCROLL,
                                 10, 10, 520, 320, w, (HMENU)(UINT_PTR)2001,
                                 st.hInstance, NULL);
        if (e && f) SendMessageW(e, WM_SETFONT, (WPARAM)f, TRUE);
        if (level == 3 || level == 4) {
            const wchar_t *labels[3] = {L"Copy all", L"Clean…", L"Close"};
            for (int i = 0; i < 3; ++i)
                CreateWindowExW(0, L"BUTTON", labels[i], WS_CHILD | WS_VISIBLE,
                                400 - i * 90, 340, 84, 26, w, (HMENU)(UINT_PTR)(2002 + i),
                                st.hInstance, NULL);
        }
        ShowWindow(w, SW_SHOW);
        UpdateWindow(w);
        ReportPrivate(level == 3 ? "open: frame+edit+3 buttons"
                            : level == 4 ? "open: frame+edit+3 buttons, stock font"
                            : level == 5 ? "open: frame+edit"
                                         : "open: frame only");

        DestroyWindow(w);
        if (f) DeleteObject(f);
        ReportPrivate("report window destroyed");
    }

    if (level >= 7) {
        // Load the shipped icon through the same path the tray uses. If a PNG
        // compressed .ico pulls in the imaging stack, the modules will show it.
        HICON fromFile = (HICON)LoadImageW(NULL, L"src\\ExplorerF11.ico", IMAGE_ICON,
                                          16, 16, LR_LOADFROMFILE);
        std::printf("%-34s %s\n", "LoadImageW(.ico from file)",
                    fromFile ? "ok" : "failed");
        Sleep(200);
        ReportPrivate("after LoadImageW(png ico)");
        if (fromFile) DestroyIcon(fromFile);
    }

    // Settle: give the shell and the CRT a moment to finish lazy work, then
    // report the number the process would sit at on a tray.
    Sleep(3000);
    ReportPrivate("settled");

    if (level >= 1) {
        NOTIFYICONDATAW nid = {};
        nid.cbSize = sizeof(nid);
        nid.hWnd = h;
        nid.uID = TRAY_ID;
        Shell_NotifyIconW(NIM_DELETE, &nid);
    }
    DestroyWindow(h);
    return 0;
}
