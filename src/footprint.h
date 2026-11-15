// SPDX-License-Identifier: MIT
//
// Footprint accounting.
//
// A tool that runs inside someone's shell has to be able to answer one
// question honestly: "what did you leave behind?" That means four groups, not
// one:
//
//   ours     written by this program, and only by this program
//   windows  created by Windows just because the exe ran (Task Manager flag,
//            tray icon cache, compatibility assistant, MuiCache, UserAssist,
//            Prefetch) - not authored by us, but still a residue of running us
//   legacy   left by v4 and earlier, which used a different product name
//   file     the exe itself: the program, not a trace of it
//
// The report lists every possible location, present or not, with who writes it,
// where it is, what it currently holds, how many bytes it costs and whether the
// cleaner will remove it. Nothing is summarised away; nothing is guessed.
#ifndef EF11_FOOTPRINT_H
#define EF11_FOOTPRINT_H

#include <windows.h>
#include <string>
#include <vector>

namespace ef11 {

enum class Group { Ours, Windows, Legacy, File };

struct Footprint {
    Group        group     = Group::Ours;
    std::wstring label;                 // 设置键
    std::wstring writer;                // who writes it, and when
    std::wstring where;                 // full key/value path or file path
    std::wstring note;                  // what it is, and what cleanup does
    std::wstring content;               // current contents, empty when absent
    bool         present   = false;
    bool         deletable = true;      // the exe itself is not --clean's job
    DWORD        bytes     = 0;
};

// Counts over a collected set. Only residue counts: the program file (it is the
// program) and in-memory window marks (they vanish with explorer) are excluded.
struct FootprintTotals {
    int   ours     = 0;   // written by this program
    int   legacy   = 0;   // written by v4 and earlier
    int   windows  = 0;   // recorded by Windows because the exe ran
    DWORD ourBytes = 0;   // ours + legacy
    DWORD winBytes = 0;

    int   Total() const { return ours + legacy + windows; }
    DWORD Bytes() const { return ourBytes + winBytes; }
    bool  Clean() const { return Total() == 0; }
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
    int prefetch   = 0;   // %WINDIR%\Prefetch\EXPLORERF11.EXE-*.pf
    int legacy     = 0;   // v4 key + Run value + approval flag

    bool Any() const { return Total() > 0; }
    int Total() const {
        return cfg + run + logFile + approved + tray + compat + mui +
               userAssist + prefetch + legacy;
    }
};

// Everything the tool can find, in report order.
std::vector<Footprint> CollectFootprints();

FootprintTotals Summarize(const std::vector<Footprint> &items);

// Totals only, for callers that need a number and not the prose (the tray menu
// shows the count on every open).
FootprintTotals CurrentTotals();

// "3 项" / "3 items". Exposed so the menu label and the report body agree on how
// a count is spelled, plurals included.
std::wstring FormatItemCount(int n);

// Human-readable report in the current UI language. places/bytes (optional)
// receive the same totals as CurrentTotals().
std::wstring BuildFootprintReport(int *places = nullptr, DWORD *bytes = nullptr);

// Remove everything removable. The exe and the in-memory window marks are
// deliberately not touched.
CleanReport CleanAll();

// Folder windows currently carrying our acceleration mark. In-memory only.
int MarkedWindowCount();

}  // namespace ef11

#endif  // EF11_FOOTPRINT_H
