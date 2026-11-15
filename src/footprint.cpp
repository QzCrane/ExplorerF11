// SPDX-License-Identifier: MIT
#include "footprint.h"

#include <cstdio>

#include "app.h"
#include "config.h"
#include "i18n.h"

namespace ef11 {
namespace {

const wchar_t *EXE_BASE = L"ExplorerF11.exe";

std::wstring FmtBytes(DWORD n) {
    wchar_t b[64];
    if (n < 1024)             swprintf_s(b, L"%lu B", (unsigned long)n);
    else if (n < 1024 * 1024) swprintf_s(b, L"%.1f KB", n / 1024.0);
    else                      swprintf_s(b, L"%.1f MB", n / (1024.0 * 1024.0));
    return b;
}

bool ContainsI(const wchar_t *hay, const wchar_t *needle) {
    size_t n = wcslen(needle);
    if (!n) return false;
    for (const wchar_t *p = hay; *p; ++p)
        if (_wcsnicmp(p, needle, n) == 0) return true;
    return false;
}

const wchar_t *BaseName(const wchar_t *path) {
    const wchar_t *cut = wcsrchr(path, L'\\');
    return cut ? cut + 1 : path;
}

// ROT13, the "encryption" UserAssist applies to its value names.
std::wstring RoT13(const std::wstring &in) {
    std::wstring out = in;
    for (size_t i = 0; i < out.size(); ++i) {
        wchar_t c = out[i];
        if (c >= L'a' && c <= L'z')      out[i] = (wchar_t)(L'a' + (c - L'a' + 13) % 26);
        else if (c >= L'A' && c <= L'Z') out[i] = (wchar_t)(L'A' + (c - L'A' + 13) % 26);
    }
    return out;
}

// Enumerate every value under a key; sum the data + name bytes.
bool KeyContents(HKEY root, const wchar_t *path, std::wstring *detail, DWORD *bytes) {
    HKEY k;
    if (RegOpenKeyExW(root, path, 0, KEY_READ, &k) != ERROR_SUCCESS) return false;

    DWORD sub = 0, vals = 0;
    if (RegQueryInfoKeyW(k, NULL, NULL, NULL, &sub, NULL, NULL, &vals,
                         NULL, NULL, NULL, NULL) != ERROR_SUCCESS) {
        RegCloseKey(k);
        return false;
    }
    *bytes = 0;
    detail->clear();
    for (DWORD i = 0; i < vals; ++i) {
        wchar_t name[256];
        DWORD cch = 256, cb = 0, type = 0;
        if (RegEnumValueW(k, i, name, &cch, NULL, &type, NULL, &cb) != ERROR_SUCCESS) continue;
        *bytes += cb + (cch + 1) * (DWORD)sizeof(wchar_t);
        if (!detail->empty()) *detail += L", ";
        *detail += name;
        if (type == REG_DWORD && cb == 4) {
            DWORD v = 0, cb2 = 4;
            if (RegQueryValueExW(k, name, NULL, NULL, (BYTE *)&v, &cb2) == ERROR_SUCCESS) {
                wchar_t nb[32];
                swprintf_s(nb, L" = %lu", (unsigned long)v);
                *detail += nb;
            }
        } else if (type == REG_SZ && cb >= sizeof(wchar_t) && cb < 256) {
            // Short strings (the language tag) are worth showing; long ones
            // (paths) would bury the rest of the line.
            wchar_t sv[64] = {0};
            DWORD cb2 = sizeof(sv);
            if (RegQueryValueExW(k, name, NULL, NULL, (BYTE *)sv, &cb2) == ERROR_SUCCESS) {
                *detail += L" = ";
                *detail += sv;
            }
        }
    }
    RegCloseKey(k);
    return true;
}

// One named value. Handles the types this tool can meet in practice.
bool OneValue(HKEY root, const wchar_t *path, const wchar_t *name,
              std::wstring *detail, DWORD *bytes) {
    HKEY k;
    if (RegOpenKeyExW(root, path, 0, KEY_READ, &k) != ERROR_SUCCESS) return false;
    BYTE buf[2048] = {0};
    DWORD cb = sizeof(buf), type = 0;
    bool ok = RegQueryValueExW(k, name, NULL, &type, buf, &cb) == ERROR_SUCCESS;
    RegCloseKey(k);
    if (!ok) return false;

    *bytes = cb + (DWORD)(wcslen(name) + 1) * (DWORD)sizeof(wchar_t);
    if (type == REG_BINARY) {
        *detail = (cb >= 1 && (buf[0] & 1))
                      ? T(L"已禁用（曾由任务管理器关闭）",
                          L"disabled (switched off in Task Manager)")
                      : T(L"已启用", L"enabled");
    } else if (type == REG_SZ && cb >= sizeof(wchar_t)) {
        *detail = (const wchar_t *)buf;
    } else {
        *detail = T(L"存在", L"present");
    }
    return true;
}

// Values whose *name* contains needle. Used for the two caches that key
// themselves by executable path.
int ValuesMatching(HKEY root, const wchar_t *path, const wchar_t *needle,
                   std::wstring *detail, DWORD *bytes) {
    HKEY k;
    if (RegOpenKeyExW(root, path, 0, KEY_READ, &k) != ERROR_SUCCESS) return 0;
    int n = 0;
    *bytes = 0;
    detail->clear();
    for (DWORD i = 0;; ++i) {
        wchar_t name[1024];
        DWORD cch = 1024, cb = 0, type = 0;
        if (RegEnumValueW(k, i, name, &cch, NULL, &type, NULL, &cb) != ERROR_SUCCESS) break;
        if (!ContainsI(name, needle)) continue;
        ++n;
        *bytes += cb + (cch + 1) * (DWORD)sizeof(wchar_t);
        if (!detail->empty()) *detail += L", ";
        *detail += BaseName(name);
    }
    RegCloseKey(k);
    return n;
}

// Windows' tray-icon bookkeeping: only entries whose ExecutablePath is our exe.
int TrayFootprint(std::wstring *detail, DWORD *bytes) {
    *bytes = 0;
    detail->clear();
    HKEY root;
    if (RegOpenKeyExW(HKEY_CURRENT_USER, TRAY_KEY, 0, KEY_READ, &root) != ERROR_SUCCESS) return 0;

    int n = 0;
    for (DWORD i = 0;; ++i) {
        wchar_t sub[256];
        DWORD cch = 256;
        if (RegEnumKeyExW(root, i, sub, &cch, NULL, NULL, NULL, NULL) != ERROR_SUCCESS) break;

        std::wstring p = std::wstring(TRAY_KEY) + L"\\" + sub;
        HKEY sk;
        if (RegOpenKeyExW(HKEY_CURRENT_USER, p.c_str(), 0, KEY_READ, &sk) != ERROR_SUCCESS) continue;
        wchar_t exe[MAX_PATH * 2] = {0};
        DWORD cb = sizeof(exe), type = 0;
        bool ours = false;
        if (RegQueryValueExW(sk, L"ExecutablePath", NULL, &type, (BYTE *)exe, &cb) == ERROR_SUCCESS)
            ours = _wcsicmp(BaseName(exe), EXE_BASE) == 0;
        RegCloseKey(sk);
        if (!ours) continue;

        ++n;
        std::wstring ignored;
        DWORD b = 0;
        KeyContents(HKEY_CURRENT_USER, p.c_str(), &ignored, &b);
        *bytes += b;
    }
    RegCloseKey(root);
    if (n) {
        wchar_t b[64];
        swprintf_s(b, L"%d", n);
        *detail = b;
    }
    return n;
}

// UserAssist keeps one Count key per GUID with ROT13-encoded value names.
int UserAssistFootprint(std::wstring *detail, DWORD *bytes) {
    *bytes = 0;
    detail->clear();
    HKEY root;
    if (RegOpenKeyExW(HKEY_CURRENT_USER, USERASSIST_KEY, 0, KEY_READ, &root) != ERROR_SUCCESS)
        return 0;

    int n = 0;
    for (DWORD i = 0;; ++i) {
        wchar_t guid[128];
        DWORD cch = 128;
        if (RegEnumKeyExW(root, i, guid, &cch, NULL, NULL, NULL, NULL) != ERROR_SUCCESS) break;
        std::wstring count = std::wstring(USERASSIST_KEY) + L"\\" + guid + L"\\Count";
        HKEY ck;
        if (RegOpenKeyExW(HKEY_CURRENT_USER, count.c_str(), 0, KEY_READ, &ck) != ERROR_SUCCESS)
            continue;
        for (DWORD v = 0;; ++v) {
            wchar_t name[1024];
            DWORD nch = 1024, cb = 0, type = 0;
            if (RegEnumValueW(ck, v, name, &nch, NULL, &type, NULL, &cb) != ERROR_SUCCESS) break;
            std::wstring plain = RoT13(name);
            if (!ContainsI(plain.c_str(), EXE_BASE)) continue;
            ++n;
            *bytes += cb + (nch + 1) * (DWORD)sizeof(wchar_t);
            if (!detail->empty()) *detail += L", ";
            *detail += guid;
        }
        RegCloseKey(ck);
    }
    RegCloseKey(root);
    return n;
}

// Prefetch is readable by administrators only; a plain user simply sees no
// entry, which is why the note says so instead of pretending it is absent.
int PrefetchFootprint(std::wstring *detail, DWORD *bytes) {
    *bytes = 0;
    detail->clear();
    wchar_t win[MAX_PATH] = {0};
    if (!GetWindowsDirectoryW(win, MAX_PATH)) return 0;
    std::wstring pattern = std::wstring(win) + L"\\Prefetch\\EXPLORERF11.EXE-*.pf";

    WIN32_FIND_DATAW fd;
    HANDLE h = FindFirstFileW(pattern.c_str(), &fd);
    if (h == INVALID_HANDLE_VALUE) return 0;
    int n = 0;
    do {
        ++n;
        *bytes += fd.nFileSizeLow;
        if (!detail->empty()) *detail += L", ";
        *detail += fd.cFileName;
    } while (FindNextFileW(h, &fd));
    FindClose(h);
    return n;
}

bool FileInfo(const std::wstring &path, DWORD *bytes) {
    WIN32_FILE_ATTRIBUTE_DATA d;
    if (!GetFileAttributesExW(path.c_str(), GetFileExInfoStandard, &d)) return false;
    if (bytes) *bytes = d.nFileSizeLow;
    return true;
}

// ---------------------------------------------------------------- cleaning

int CleanTrayIcons() {
    HKEY root;
    if (RegOpenKeyExW(HKEY_CURRENT_USER, TRAY_KEY, 0, KEY_READ | KEY_WRITE, &root)
        != ERROR_SUCCESS)
        return 0;

    std::vector<std::wstring> victims;
    for (DWORD i = 0;; ++i) {
        wchar_t name[256];
        DWORD cch = 256;
        LSTATUS s = RegEnumKeyExW(root, i, name, &cch, NULL, NULL, NULL, NULL);
        if (s == ERROR_NO_MORE_ITEMS) break;
        if (s != ERROR_SUCCESS) continue;

        HKEY sub;
        if (RegOpenKeyExW(root, name, 0, KEY_QUERY_VALUE, &sub) != ERROR_SUCCESS) continue;
        wchar_t exe[MAX_PATH * 2] = {0};
        DWORD cb = sizeof(exe), type = 0;
        if (RegQueryValueExW(sub, L"ExecutablePath", NULL, &type, (BYTE *)exe, &cb) == ERROR_SUCCESS &&
            _wcsicmp(BaseName(exe), EXE_BASE) == 0)
            victims.push_back(name);
        RegCloseKey(sub);
    }

    int removed = 0;
    for (size_t i = 0; i < victims.size(); ++i)
        if (RegDeleteKeyW(root, victims[i].c_str()) == ERROR_SUCCESS) ++removed;
    RegCloseKey(root);
    return removed;
}

int DeleteMatchingValues(const wchar_t *path, const wchar_t *needle, bool rot13) {
    HKEY k;
    if (RegOpenKeyExW(HKEY_CURRENT_USER, path, 0, KEY_READ | KEY_SET_VALUE, &k) != ERROR_SUCCESS)
        return 0;
    std::vector<std::wstring> victims;
    for (DWORD i = 0;; ++i) {
        wchar_t name[1024];
        DWORD cch = 1024;
        if (RegEnumValueW(k, i, name, &cch, NULL, NULL, NULL, NULL) != ERROR_SUCCESS) break;
        std::wstring probe = rot13 ? RoT13(name) : std::wstring(name);
        if (ContainsI(probe.c_str(), needle)) victims.push_back(name);
    }
    int removed = 0;
    for (size_t i = 0; i < victims.size(); ++i)
        if (RegDeleteValueW(k, victims[i].c_str()) == ERROR_SUCCESS) ++removed;
    RegCloseKey(k);
    return removed;
}

int CleanUserAssist() {
    HKEY root;
    if (RegOpenKeyExW(HKEY_CURRENT_USER, USERASSIST_KEY, 0, KEY_READ, &root) != ERROR_SUCCESS)
        return 0;
    std::vector<std::wstring> counts;
    for (DWORD i = 0;; ++i) {
        wchar_t guid[128];
        DWORD cch = 128;
        if (RegEnumKeyExW(root, i, guid, &cch, NULL, NULL, NULL, NULL) != ERROR_SUCCESS) break;
        counts.push_back(std::wstring(USERASSIST_KEY) + L"\\" + guid + L"\\Count");
    }
    RegCloseKey(root);

    int removed = 0;
    for (size_t i = 0; i < counts.size(); ++i)
        removed += DeleteMatchingValues(counts[i].c_str(), EXE_BASE, true);
    return removed;
}

int CleanPrefetch() {
    wchar_t win[MAX_PATH] = {0};
    if (!GetWindowsDirectoryW(win, MAX_PATH)) return 0;
    std::wstring pattern = std::wstring(win) + L"\\Prefetch\\EXPLORERF11.EXE-*.pf";
    WIN32_FIND_DATAW fd;
    HANDLE h = FindFirstFileW(pattern.c_str(), &fd);
    if (h == INVALID_HANDLE_VALUE) return 0;
    int removed = 0;
    do {
        std::wstring full = std::wstring(win) + L"\\Prefetch\\" + fd.cFileName;
        if (DeleteFileW(full.c_str())) ++removed;
    } while (FindNextFileW(h, &fd));
    FindClose(h);
    return removed;
}

int CleanLegacy() {
    int n = 0;
    if (RegDeleteKeyW(HKEY_CURRENT_USER, OLD_CFG_KEY) == ERROR_SUCCESS) ++n;
    if (DeleteRunValue(OLD_RUN_VALUE)) ++n;
    HKEY k;
    if (RegOpenKeyExW(HKEY_CURRENT_USER, APPROVED_KEY, 0, KEY_SET_VALUE, &k) == ERROR_SUCCESS) {
        if (RegDeleteValueW(k, OLD_RUN_VALUE) == ERROR_SUCCESS) ++n;
        RegCloseKey(k);
    }
    return n;
}

// ---------------------------------------------------------------- formatting

std::wstring Pad2(int n) {
    wchar_t b[24];
    swprintf_s(b, L"%d", n);
    return b;
}

// Count + optional size, with the plural English needs and Chinese does not.
std::wstring ItemsBytes(int n, DWORD bytes) {
    std::wstring s = Pad2(n);
    s += T(L" 项", n == 1 ? L" item" : L" items");
    if (n) {
        s += T(L"（", L" (");
        s += FmtBytes(bytes);
        s += T(L"）", L")");
    }
    return s;
}

}  // namespace

int MarkedWindowCount() {
    struct Ctx { int n; } ctx = {0};
    EnumWindows([](HWND h, LPARAM p) -> BOOL {
        if (GetPropW(h, PROP_MARK)) ++reinterpret_cast<Ctx *>(p)->n;
        return TRUE;
    }, (LPARAM)&ctx);
    return ctx.n;
}

std::vector<Footprint> CollectFootprints() {
    std::vector<Footprint> f;
    std::wstring d;
    const wchar_t *W_WIN = T(L"Windows 自动记录", L"recorded by Windows");

    // ---- 1. our settings key -------------------------------------------
    {
        Footprint x;
        x.group   = Group::Ours;
        x.label   = T(L"设置键", L"Settings key");
        x.writer  = T(L"本程序；仅当某个开关被改成非默认值时才写入",
                      L"this program, and only while a setting differs from its default");
        x.where   = std::wstring(L"HKCU\\") + CFG_KEY;
        x.note    = T(L"可能的值：Tabs、InitialSweep、Language。改回默认值即删除该值；"
                      L"键内没有任何值时，键本身一并删除",
                      L"possible values: Tabs, InitialSweep, Language. Resetting one deletes it; "
                      L"when the key holds nothing, the key itself is deleted");
        x.present = KeyContents(HKEY_CURRENT_USER, CFG_KEY, &d, &x.bytes);
        if (x.present) x.content = d + L" (" + FmtBytes(x.bytes) + L")";
        f.push_back(x);
    }
    // ---- 2. autostart value --------------------------------------------
    {
        Footprint x;
        x.group   = Group::Ours;
        x.label   = T(L"开机自启项", L"Autostart entry");
        x.writer  = T(L"本程序；你在托盘菜单里勾选「开机自启」时",
                      L"this program, when \"Start with Windows\" is ticked in the tray menu");
        x.where   = std::wstring(L"HKCU\\") + RUN_KEY + L"\\" + RUN_VALUE;
        x.note    = T(L"一个 REG_SZ 值：带引号的 exe 完整路径，不带任何参数。取消勾选即删除",
                      L"one REG_SZ value: the quoted full path to the exe, with no arguments. "
                      L"Unticking deletes it");
        x.present = OneValue(HKEY_CURRENT_USER, RUN_KEY, RUN_VALUE, &d, &x.bytes);
        if (x.present) x.content = d + L" (" + FmtBytes(x.bytes) + L")";
        f.push_back(x);
    }
    // ---- 3. log file ----------------------------------------------------
    {
        Footprint x;
        x.group   = Group::Ours;
        x.label   = T(L"日志文件", L"Log file");
        x.writer  = T(L"本程序；只有带 --log 参数或排查问题时",
                      L"this program, only with --log");
        x.where   = LogPath();
        x.note    = T(L"默认不存在。超过 1 MB 会从头重写，不会无限增长。"
                      L"「清除全部痕迹」删除它",
                      L"not created by default. Rewritten from scratch past 1 MB, so it cannot "
                      L"grow without bound. Removed by \"clear all traces\"");
        x.present = FileInfo(x.where, &x.bytes);
        if (x.present) x.content = FmtBytes(x.bytes);
        f.push_back(x);
    }
    // ---- 4. the executable itself --------------------------------------
    {
        Footprint x;
        x.group     = Group::File;
        x.label     = T(L"程序本体", L"Program file");
        x.writer    = T(L"你；这个文件是你放到这里的", L"you; the file is where you put it");
        x.where     = ExePath();
        x.note      = T(L"这不是痕迹，而是程序本身，清理不会删除它。彻底卸载：先"
                        L"「清除全部痕迹」，再删除该文件",
                        L"not residue but the program itself; cleanup never deletes it. "
                        L"Full uninstall: clear all traces, then delete this file");
        x.deletable = false;
        x.present   = FileInfo(x.where, &x.bytes);
        if (x.present) x.content = FmtBytes(x.bytes);
        f.push_back(x);
    }
    // ---- 5. Task Manager on/off flag -----------------------------------
    {
        Footprint x;
        x.group   = Group::Windows;
        x.label   = T(L"启动开关（任务管理器）", L"Startup approval flag (Task Manager)");
        x.writer  = W_WIN;
        x.where   = std::wstring(L"HKCU\\") + APPROVED_KEY + L"\\" + RUN_VALUE;
        x.note    = T(L"12 字节 REG_BINARY。首字节为奇数表示你在任务管理器里把它关过；"
                      L"重新勾选自启或清理痕迹时删除该值",
                      L"12-byte REG_BINARY; an odd first byte means you switched it off in Task "
                      L"Manager. Deleted when autostart is re-ticked or traces are cleared");
        x.present = OneValue(HKEY_CURRENT_USER, APPROVED_KEY, RUN_VALUE, &d, &x.bytes);
        if (x.present) x.content = d + L" (" + FmtBytes(x.bytes) + L")";
        f.push_back(x);
    }
    // ---- 6. tray icon bookkeeping --------------------------------------
    {
        Footprint x;
        x.group   = Group::Windows;
        x.label   = T(L"托盘图标记录", L"Tray icon bookkeeping");
        x.writer  = W_WIN;
        x.where   = std::wstring(L"HKCU\\") + TRAY_KEY + L"\\{...}";
        x.note    = T(L"每个托盘图标一条记录，内含约 1–3 KB 的图标快照；"
                      L"只统计 ExecutablePath 指向本程序的那些",
                      L"one record per tray icon, each holding a 1-3 KB icon snapshot; "
                      L"only entries whose ExecutablePath points at this exe are counted");
        x.present = TrayFootprint(&d, &x.bytes) > 0;
        if (x.present) x.content = d + T(L" 条", L" entries") + L" (" + FmtBytes(x.bytes) + L")";
        f.push_back(x);
    }
    // ---- 7. Compatibility Assistant store ------------------------------
    {
        Footprint x;
        x.group   = Group::Windows;
        x.label   = T(L"兼容性助手记录", L"Compatibility Assistant store");
        x.writer  = W_WIN;
        x.where   = std::wstring(L"HKCU\\") + COMPAT_KEY + L"\\<exe path>";
        x.note    = T(L"Windows 在程序运行后留下的一条「它运行过」的记录，供兼容性判断使用",
                      L"one \"this program ran\" record Windows keeps for compatibility decisions");
        x.present = ValuesMatching(HKEY_CURRENT_USER, COMPAT_KEY, EXE_BASE, &d, &x.bytes) > 0;
        if (x.present) x.content = L"ExplorerF11.exe (" + FmtBytes(x.bytes) + L")";
        f.push_back(x);
    }
    // ---- 8. MuiCache friendly name -------------------------------------
    {
        Footprint x;
        x.group   = Group::Windows;
        x.label   = T(L"应用名缓存（MuiCache）", L"Friendly-name cache (MuiCache)");
        x.writer  = W_WIN;
        x.where   = std::wstring(L"HKCU\\") + MUI_KEY + L"\\<exe path>.FriendlyAppName";
        x.note    = T(L"任务管理器、防火墙等界面里显示的程序名就缓存在这里",
                      L"where Task Manager and the firewall get the name they display");
        x.present = ValuesMatching(HKEY_CURRENT_USER, MUI_KEY, EXE_BASE, &d, &x.bytes) > 0;
        if (x.present) x.content = d + L" (" + FmtBytes(x.bytes) + L")";
        f.push_back(x);
    }
    // ---- 9. UserAssist counters ----------------------------------------
    {
        Footprint x;
        x.group   = Group::Windows;
        x.label   = T(L"启动次数统计（UserAssist）", L"Launch counter (UserAssist)");
        x.writer  = W_WIN;
        x.where   = std::wstring(L"HKCU\\") + USERASSIST_KEY + L"\\{...}\\Count";
        x.note    = T(L"值名是 ROT13 编码的 exe 路径，记录启动次数与最后使用时间",
                      L"value names are ROT13-encoded exe paths; stores launch count and last-used time");
        x.present = UserAssistFootprint(&d, &x.bytes) > 0;
        if (x.present) x.content = d + L" (" + FmtBytes(x.bytes) + L")";
        f.push_back(x);
    }
    // ---- 10. Prefetch ---------------------------------------------------
    {
        Footprint x;
        x.group   = Group::Windows;
        x.label   = T(L"预读取记录（Prefetch）", L"Prefetch entry");
        x.writer  = W_WIN;
        x.where   = std::wstring(L"%WINDIR%\\Prefetch\\") + EXE_BASE + L"-*.pf";
        x.note    = T(L"只有管理员可读。存在即说明系统预读过它；清理会删除，需要管理员权限",
                      L"readable by administrators only. Its presence means the system has "
                      L"prefetched it; cleanup deletes it and needs elevation");
        x.present = PrefetchFootprint(&d, &x.bytes) > 0;
        if (x.present) x.content = d + L" (" + FmtBytes(x.bytes) + L")";
        f.push_back(x);
    }
    // ---- 11. in-memory window marks ------------------------------------
    {
        int n = MarkedWindowCount();
        Footprint x;
        x.group   = Group::Ours;
        x.label   = T(L"窗口标记（只在内存中）", L"Window marks (memory only)");
        x.writer  = T(L"本程序；写在资源管理器窗口的属性里",
                      L"this program, as a property on explorer windows");
        x.where   = T(L"窗口属性 ExplorerF11.Marked", L"window property ExplorerF11.Marked");
        x.note    = T(L"不落盘：explorer 重启或注销后自动消失，因此无需也无法清理",
                      L"never touches disk: gone when explorer restarts or you sign out, "
                      L"so there is nothing to clean");
        x.present = n > 0;
        x.deletable = false;
        if (x.present) x.content = Pad2(n) + T(L" 个窗口", L" window(s)");
        f.push_back(x);
    }
    // ---- 12-14. legacy leftovers ---------------------------------------
    {
        Footprint x;
        x.group   = Group::Legacy;
        x.label   = T(L"旧版本设置键", L"Legacy settings key");
        x.writer  = T(L"v4 及更早版本", L"v4 and earlier");
        x.where   = std::wstring(L"HKCU\\") + OLD_CFG_KEY;
        x.note    = T(L"旧版本的产品名是 ExplorerF11Ultra；新版本首次运行会自动迁移并删除它",
                      L"older builds used the product name ExplorerF11Ultra; the first run of "
                      L"this version migrates it and deletes it");
        x.present = KeyContents(HKEY_CURRENT_USER, OLD_CFG_KEY, &d, &x.bytes);
        if (x.present) x.content = d + L" (" + FmtBytes(x.bytes) + L")";
        f.push_back(x);
    }
    {
        Footprint x;
        x.group   = Group::Legacy;
        x.label   = T(L"旧版本自启项", L"Legacy autostart entry");
        x.writer  = T(L"v4 及更早版本", L"v4 and earlier");
        x.where   = std::wstring(L"HKCU\\") + RUN_KEY + L"\\" + OLD_RUN_VALUE;
        x.note    = T(L"新版本首次运行会把它改指到当前 exe；「清除全部痕迹」也会删除",
                      L"repointed at the current exe on first run; \"clear all traces\" deletes it too");
        x.present = OneValue(HKEY_CURRENT_USER, RUN_KEY, OLD_RUN_VALUE, &d, &x.bytes);
        if (x.present) x.content = d + L" (" + FmtBytes(x.bytes) + L")";
        f.push_back(x);
    }
    {
        Footprint x;
        x.group   = Group::Legacy;
        x.label   = T(L"旧版本启动开关", L"Legacy startup flag");
        x.writer  = T(L"Windows；为旧版本记的", L"Windows, for the old build");
        x.where   = std::wstring(L"HKCU\\") + APPROVED_KEY + L"\\" + OLD_RUN_VALUE;
        x.note    = T(L"删掉自启项时若不同时删它，会留下一个孤立的开关",
                      L"removing the entry without this flag would leave an orphan behind");
        x.present = OneValue(HKEY_CURRENT_USER, APPROVED_KEY, OLD_RUN_VALUE, &d, &x.bytes);
        if (x.present) x.content = d + L" (" + FmtBytes(x.bytes) + L")";
        f.push_back(x);
    }
    return f;
}

FootprintTotals Summarize(const std::vector<Footprint> &items) {
    FootprintTotals t;
    for (size_t i = 0; i < items.size(); ++i) {
        const Footprint &x = items[i];
        if (!x.present || !x.deletable) continue;
        switch (x.group) {
        case Group::Ours:    ++t.ours;    t.ourBytes += x.bytes; break;
        case Group::Legacy:  ++t.legacy;  t.ourBytes += x.bytes; break;
        case Group::Windows: ++t.windows; t.winBytes += x.bytes; break;
        case Group::File:    break;   // the program is not a trace of itself
        }
    }
    return t;
}

FootprintTotals CurrentTotals() {
    return Summarize(CollectFootprints());
}

std::wstring FormatItemCount(int n) {
    std::wstring s = Pad2(n);
    s += T(L" 项", n == 1 ? L" item" : L" items");
    return s;
}

std::wstring BuildFootprintReport(int *placesOut, DWORD *bytesOut) {
    std::vector<Footprint> f = CollectFootprints();
    FootprintTotals t = Summarize(f);

    std::wstring s;
    s += L"ExplorerF11 " EF11_VERSION;
    s += T(L" · 足迹报告\n", L" - footprint report\n");

    s += T(L"程序：", L"program: ");
    s += ExePath();
    s += L"\n";

    SYSTEMTIME st;
    GetLocalTime(&st);
    wchar_t when[64];
    swprintf_s(when, L"%04d-%02d-%02d %02d:%02d:%02d",
               st.wYear, st.wMonth, st.wDay, st.wHour, st.wMinute, st.wSecond);
    s += T(L"时间：", L"time:    ");
    s += when;
    s += T(L"（本机时间） · 界面语言：中文\n", L" (local) - UI language: English\n");

    s += T(L"范围：", L"scope:   ");
    s += Pad2((int)f.size());
    s += T(L" 个可能位置，分 4 组；下列每一项都会逐一核对，缺的也列出来。\n",
           L" possible locations in 4 groups; each one is checked below, including the "
           L"ones that are absent.\n");
    s += L"================================================================\n\n";

    // Verdict first: "how dirty is it" must be answerable without reading on.
    if (t.Clean()) {
        s += T(L"结论：干净 —— 系统里找不到任何与它相关的记录（0 项需要清理）。\n",
               L"Verdict: clean - no trace of it anywhere (0 items to remove).\n");
    } else {
        s += T(L"结论：共 ", L"Verdict: ");
        s += FormatItemCount(t.Total());
        s += T(L"需要清理，合计 ", L" to remove, ");
        s += FmtBytes(t.Bytes());
        s += T(L"。\n      ", L" in total.\n      ");
        s += T(L"本程序 ", L"this program: ");
        s += ItemsBytes(t.ours, t.ourBytes);
        s += T(L"；Windows 自动记录 ", L"; recorded by Windows: ");
        s += ItemsBytes(t.windows, t.winBytes);
        s += T(L"；旧版本 ", L"; legacy: ");
        s += FormatItemCount(t.legacy);
        s += T(L"。\n", L".\n");
    }
    s += T(L"      标注「可清理」的项目会被「清除全部痕迹并退出」删除；程序本体不删除。\n\n",
           L"      Items marked \"removable\" are deleted by \"clear all traces and exit\"; "
           L"the exe is not.\n\n");

    const wchar_t *titles[4] = {
        T(L"── 一、本程序写入", L"-- 1. written by this program"),
        T(L"── 二、Windows 自动记录", L"-- 2. recorded by Windows"),
        T(L"── 三、旧版本残留（v4 及更早）", L"-- 3. legacy leftovers (v4 and earlier)"),
        T(L"── 四、程序文件", L"-- 4. program file"),
    };
    const Group order[4] = {Group::Ours, Group::Windows, Group::Legacy, Group::File};

    for (int g = 0; g < 4; ++g) {
        bool header = false;
        int  idx    = 0;
        for (size_t i = 0; i < f.size(); ++i) {
            const Footprint &x = f[i];
            if (x.group != order[g]) continue;
            if (!header) { s += titles[g]; s += L"\n\n"; header = true; }

            ++idx;
            s += L"[";
            s += Pad2(idx);
            s += L"] ";
            s += x.label;
            s += x.present ? T(L" · 存在", L" - present") : T(L" · 不存在", L" - absent");
            if (x.present) {
                s += x.deletable ? T(L" · 可清理", L" - removable")
                                 : T(L" · 不清理", L" - kept");
            }
            s += L"\n";

            s += T(L"      谁写：", L"      who:    "); s += x.writer; s += L"\n";
            s += T(L"      位置：", L"      where:  "); s += x.where;  s += L"\n";
            if (x.present) {
                s += T(L"      内容：", L"      what:   ");
                s += x.content;
                s += L"\n";
            }
            s += T(L"      说明：", L"      note:   "); s += x.note; s += L"\n\n";
        }
    }

    s += T(L"注 1：注册表本身还有固定开销（每个键约 1 KB，每个值还有名称与头部开销），"
           L"这里只统计值数据与名称的字节数。\n"
           L"注 2：Windows 自动记录的那几项删掉之后，下次运行还会重新生成 —— 这是系统行为，不是残留。\n"
           L"注 3：本报告只读：生成报告不会修改任何一项。\n",
           L"Note 1: the registry adds fixed overhead (about 1 KB per key, plus per-value headers); "
           L"only value data and names are counted here.\n"
           L"Note 2: items recorded by Windows come back on the next run - that is OS behaviour, "
           L"not residue.\n"
           L"Note 3: this report is read-only: generating it changes nothing.\n");

    if (placesOut) *placesOut = t.Total();
    if (bytesOut)  *bytesOut  = t.Bytes();
    return s;
}

CleanReport CleanAll() {
    CleanReport r;
    r.run        = DeleteRunValue(RUN_VALUE) ? 1 : 0;
    r.cfg        = RegDeleteKeyW(HKEY_CURRENT_USER, CFG_KEY) == ERROR_SUCCESS ? 1 : 0;
    r.logFile    = DeleteFileW(LogPath().c_str()) ? 1 : 0;

    HKEY k;
    if (RegOpenKeyExW(HKEY_CURRENT_USER, APPROVED_KEY, 0, KEY_SET_VALUE, &k) == ERROR_SUCCESS) {
        if (RegDeleteValueW(k, RUN_VALUE) == ERROR_SUCCESS) ++r.approved;
        RegCloseKey(k);
    }

    r.tray       = CleanTrayIcons();
    r.compat     = DeleteMatchingValues(COMPAT_KEY, EXE_BASE, false);
    r.mui        = DeleteMatchingValues(MUI_KEY, EXE_BASE, false);
    r.userAssist = CleanUserAssist();
    r.prefetch   = CleanPrefetch();
    r.legacy     = CleanLegacy();
    return r;
}

}  // namespace ef11
