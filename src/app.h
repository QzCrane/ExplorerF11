// SPDX-License-Identifier: MIT
//
// Shared constants. One place for every name the tool writes into the system,
// so a rename can never leave an orphan behind in a second file.
#ifndef EF11_APP_H
#define EF11_APP_H

#include <windows.h>

#define EF11_VERSION      L"1.0.2"

namespace ef11 {

// Identity
inline const wchar_t *APP_NAME       = L"ExplorerF11";
inline const wchar_t *MUTEX_NAME     = L"Local\\ExplorerF11_SingleInstance";
inline const wchar_t *WINDOW_CLASS   = L"ExplorerF11Window";
inline const wchar_t *STATUS_CLASS   = L"ExplorerF11StatusWindow";

// Shell window classes we act on
inline const wchar_t *EXPLORER_CLASS = L"CabinetWClass";
inline const wchar_t *TAB_CLASS      = L"ShellTabWindowClass";

// Marks we put on someone else's window. In-memory only: never touches disk,
// disappears when explorer restarts.
inline const wchar_t *PROP_MARK      = L"ExplorerF11.Marked";
inline const wchar_t *PROP_TICK      = L"ExplorerF11.Tick";

// Registry locations
inline const wchar_t *RUN_KEY        = L"Software\\Microsoft\\Windows\\CurrentVersion\\Run";
inline const wchar_t *RUN_VALUE      = L"ExplorerF11";
inline const wchar_t *APPROVED_KEY   = L"Software\\Microsoft\\Windows\\CurrentVersion\\Explorer\\StartupApproved\\Run";
inline const wchar_t *CFG_KEY        = L"Software\\ExplorerF11";
inline const wchar_t *TRAY_KEY       = L"Control Panel\\NotifyIconSettings";
inline const wchar_t *COMPAT_KEY     = L"Software\\Microsoft\\Windows NT\\CurrentVersion\\AppCompatFlags\\Compatibility Assistant\\Store";
inline const wchar_t *MUI_KEY        = L"Software\\Classes\\Local Settings\\Software\\Microsoft\\Windows\\Shell\\MuiCache";
inline const wchar_t *USERASSIST_KEY = L"Software\\Microsoft\\Windows\\CurrentVersion\\Explorer\\UserAssist";

// Value names inside CFG_KEY. Kept here so the residue report and the writer
// can never disagree about what a key may contain.
inline const wchar_t *CFG_TABS       = L"Tabs";
inline const wchar_t *CFG_INITIAL    = L"InitialSweep";
inline const wchar_t *CFG_LANG       = L"Language";   // REG_SZ: "zh" | "zh-Hant" | "en" | "ja" | "ko"

// Defaults. A setting equal to its default is *deleted* from the registry
// instead of being stored, which is what keeps the default state at zero
// writes.
inline const bool DEF_TABS    = true;
inline const bool DEF_INITIAL = true;

}  // namespace ef11

#endif  // EF11_APP_H
