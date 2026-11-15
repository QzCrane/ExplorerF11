// SPDX-License-Identifier: MIT
//
// Settings and autostart. Both live in HKCU, so no elevation is ever needed.
//
// Design rule: only deviations from the defaults are stored. A setting that is
// back at its default is deleted, and an empty settings key is deleted too.
// That is what makes "default configuration" identical to "no trace at all".
#ifndef EF11_CONFIG_H
#define EF11_CONFIG_H

#include <windows.h>
#include <string>

namespace ef11 {

std::wstring ExePath();
std::wstring ExeDir();
std::wstring LogPath();          // %TEMP%\ExplorerF11.log (only with --log)

bool CfgRead(const wchar_t *name, bool def);
void CfgWrite(const wchar_t *name, bool value, bool def);
void CfgForget(const wchar_t *name);

bool IsAutostartEnabled();       // Run value present AND not disabled
void SetAutostart(bool on);      // never touches the shared Run key itself
bool DeleteRunValue(const wchar_t *value);
void DeleteApproved(const wchar_t *value);

}  // namespace ef11

#endif  // EF11_CONFIG_H
