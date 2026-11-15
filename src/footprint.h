// SPDX-License-Identifier: MIT
//
// Footprint accounting.
//
// A tool that runs inside someone's shell has to be able to answer one
// question honestly: "what did you leave behind?" That means three groups, not
// one:
//
//   ours     written by this program, and only by this program
//   windows  created by Windows just because the exe ran (Task Manager flag,
//            tray icon cache, compatibility assistant, MuiCache, UserAssist,
//            Prefetch) — not authored by us, but still a residue of running us
//   legacy   left by v4 and earlier, which used a different product name
//
// The report lists every one of them with who wrote it, the exact location, the
// current contents and the byte count. Nothing is summarised away.
#ifndef EF11_FOOTPRINT_H
#define EF11_FOOTPRINT_H

#include <windows.h>
#include <string>
#include <vector>

namespace ef11 {

enum class Group { Ours, Windows, Legacy, File };

struct Footprint {
    Group        group     = Group::Ours;
    std::wstring label;                 // 【1】设置键
    std::wstring writer;                // who wrote it
    std::wstring where;                 // full path / file path
    std::wstring note;                  // plain-language explanation
    std::wstring content;               // current contents, empty when absent
    bool         present   = false;
    bool         deletable = true;      // the exe itself is not --clean's job
    DWORD        bytes     = 0;
};

// Result of a clean: how many of each kind were actually removed.
struct CleanReport {
    int cfg        = 0;   // HKCU\Software\ExplorerF11
    int run        = 0;   // HKCU\...\Run\ExplorerF11
    int logFile    = 0;   // %TEMP%\ExplorerF11.log
    int approved   = 0;   // Windows startup on/off flag
    int tray       = 0;   // Windows per-icon bookkeeping
    int compat     = 0;   // Compatibility Assistant store
    int mui        = 0;   // MuiCache friendly name
    int userAssist = 0;   // UserAssist launch counters
    int prefetch   = 0;   // C:\Windows\Prefetch\EXPLORERF11.EXE-*.pf
    int legacy     = 0;   // v4 key + Run value + approval flag

    bool Any() const {
        return cfg || run || logFile || approved || tray || compat || mui ||
               userAssist || prefetch || legacy;
    }
    int Total() const {
        return cfg + run + logFile + approved + tray + compat + mui +
               userAssist + prefetch + legacy;
    }
};

// Everything the tool can find, in report order.
std::vector<Footprint> CollectFootprints();

// Human-readable report. places/bytes (optional) receive the totals for
// "ours" + "windows" only — the exe itself is not residue.
std::wstring BuildFootprintReport(int *places = nullptr, DWORD *bytes = nullptr);

// Remove everything removable. The exe and the in-memory window marks are
// deliberately not touched.
CleanReport CleanAll();

// Folder windows currently carrying our acceleration mark. In-memory only.
int MarkedWindowCount();

}  // namespace ef11

#endif  // EF11_FOOTPRINT_H
