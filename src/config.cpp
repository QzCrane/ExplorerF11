// SPDX-License-Identifier: MIT
#include "config.h"

#include "app.h"

namespace ef11 {
namespace {

// StartupApproved stores a 12-byte REG_BINARY per entry: 02 00 ... = enabled,
// 03 00 ... + FILETIME = disabled. Only the low bit matters.
bool AutostartBlocked() {
    HKEY k;
    if (RegOpenKeyExW(HKEY_CURRENT_USER, APPROVED_KEY, 0, KEY_QUERY_VALUE, &k) != ERROR_SUCCESS)
        return false;
    BYTE b[16] = {0};
    DWORD cb = sizeof(b), type = 0;
    bool blocked = false;
    if (RegQueryValueExW(k, RUN_VALUE, NULL, &type, b, &cb) == ERROR_SUCCESS &&
        type == REG_BINARY && cb >= 1)
        blocked = (b[0] & 1) != 0;
    RegCloseKey(k);
    return blocked;
}

}  // namespace

std::wstring ExePath() {
    wchar_t path[MAX_PATH * 2] = {0};
    DWORD n = GetModuleFileNameW(NULL, path, MAX_PATH * 2);
    return std::wstring(path, n);
}

std::wstring ExeDir() {
    std::wstring p = ExePath();
    size_t cut = p.find_last_of(L'\\');
    return cut == std::wstring::npos ? p : p.substr(0, cut);
}

std::wstring LogPath() {
    wchar_t dir[MAX_PATH] = {0};
    DWORD n = GetTempPathW(MAX_PATH, dir);
    std::wstring p(dir, n);
    if (!p.empty() && p.back() != L'\\') p += L'\\';
    p += L"ExplorerF11.log";
    return p;
}

// No value = enabled. Deleting the flag is therefore the cheapest way to undo a
// Task Manager "disable" and leaves nothing extra behind.
void DeleteApproved(const wchar_t *value) {
    HKEY k;
    if (RegOpenKeyExW(HKEY_CURRENT_USER, APPROVED_KEY, 0, KEY_SET_VALUE, &k) != ERROR_SUCCESS)
        return;
    RegDeleteValueW(k, value);
    RegCloseKey(k);
}

bool IsAutostartEnabled() {
    HKEY k;
    if (RegOpenKeyExW(HKEY_CURRENT_USER, RUN_KEY, 0, KEY_QUERY_VALUE, &k) != ERROR_SUCCESS)
        return false;
    wchar_t buf[1024];
    DWORD cb = sizeof(buf), type = 0;
    bool found = RegQueryValueExW(k, RUN_VALUE, NULL, &type, (BYTE *)buf, &cb) == ERROR_SUCCESS;
    RegCloseKey(k);
    return found && !AutostartBlocked();
}

void SetAutostart(bool on) {
    if (!on) {
        DeleteRunValue(RUN_VALUE);
        DeleteApproved(RUN_VALUE);   // Windows' flag must not outlive the entry
        return;
    }
    DeleteApproved(RUN_VALUE);       // clear a previous Task Manager "disable"
    HKEY k;
    if (RegCreateKeyExW(HKEY_CURRENT_USER, RUN_KEY, 0, NULL, 0, KEY_SET_VALUE, NULL, &k, NULL)
        != ERROR_SUCCESS)
        return;
    // Quoted: the path may contain spaces. No arguments: every preference is in
    // the registry, so autostart and a manual double-click behave identically.
    std::wstring v = L"\"" + ExePath() + L"\"";
    RegSetValueExW(k, RUN_VALUE, 0, REG_SZ, (const BYTE *)v.c_str(),
                   (DWORD)((v.size() + 1) * sizeof(wchar_t)));
    RegCloseKey(k);
}

bool DeleteRunValue(const wchar_t *value) {
    HKEY k;
    if (RegOpenKeyExW(HKEY_CURRENT_USER, RUN_KEY, 0, KEY_SET_VALUE, &k) != ERROR_SUCCESS)
        return false;
    bool ok = RegDeleteValueW(k, value) == ERROR_SUCCESS;
    RegCloseKey(k);
    return ok;
}

bool CfgRead(const wchar_t *name, bool def) {
    HKEY k;
    if (RegOpenKeyExW(HKEY_CURRENT_USER, CFG_KEY, 0, KEY_QUERY_VALUE, &k) != ERROR_SUCCESS)
        return def;
    DWORD v = def ? 1u : 0u, cb = sizeof(v), type = 0;
    if (RegQueryValueExW(k, name, NULL, &type, (BYTE *)&v, &cb) != ERROR_SUCCESS ||
        type != REG_DWORD)
        v = def ? 1u : 0u;
    RegCloseKey(k);
    return v != 0;
}

// Delete a value, then drop the key if nothing else lives in it.
void CfgForget(const wchar_t *name) {
    HKEY k;
    if (RegOpenKeyExW(HKEY_CURRENT_USER, CFG_KEY, 0, KEY_READ | KEY_SET_VALUE, &k)
        != ERROR_SUCCESS)
        return;
    RegDeleteValueW(k, name);
    DWORD sub = 0, val = 0;
    LSTATUS s = RegQueryInfoKeyW(k, NULL, NULL, NULL, &sub, NULL, NULL, &val,
                                 NULL, NULL, NULL, NULL);
    RegCloseKey(k);
    if (s == ERROR_SUCCESS && sub == 0 && val == 0)
        RegDeleteKeyW(HKEY_CURRENT_USER, CFG_KEY);
}

void CfgWrite(const wchar_t *name, bool value, bool def) {
    if (value == def) {         // back to default -> the value should not exist
        CfgForget(name);
        return;
    }
    HKEY k;
    if (RegCreateKeyExW(HKEY_CURRENT_USER, CFG_KEY, 0, NULL, 0, KEY_SET_VALUE,
                        NULL, &k, NULL) != ERROR_SUCCESS)
        return;
    DWORD v = value ? 1u : 0u;
    RegSetValueExW(k, name, 0, REG_DWORD, (const BYTE *)&v, sizeof(v));
    RegCloseKey(k);
}

}  // namespace ef11
