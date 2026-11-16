// SPDX-License-Identifier: MIT
//
// Residue accounting.
//
// A tool that runs inside someone's shell has to be able to answer one
// question honestly: "what did you leave behind?" That means three groups, not
// one:
//
//   ours     written by this program, and only by this program
//   windows  created by Windows just because the exe ran (Task Manager flag,
//            tray icon cache, compatibility assistant, MuiCache, UserAssist,
//            Prefetch) - not authored by us, but still a residue of running us
//   file     the exe itself: the program, not a residue of itself
//
// The report lists every possible location, present or not, with who writes it,
// where it is, what it currently holds, how many bytes it costs and whether the
// cleaner will remove it. Nothing is summarised away; nothing is guessed.
#ifndef EF11_RESIDUE_H
#define EF11_RESIDUE_H

#include <windows.h>
#include <string>
#include <vector>

namespace ef11 {

enum class Group { Ours, Windows, File };

struct Residue {
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
struct ResidueTotals {
    int   ours     = 0;   // written by this program
    int   windows  = 0;   // recorded by Windows because the exe ran
    DWORD ourBytes = 0;   // written by this program
    DWORD winBytes = 0;

    int   Total() const { return ours + windows; }
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

    bool Any() const { return Total() > 0; }
    int Total() const {
        return cfg + run + logFile + approved + tray + compat + mui +
               userAssist + prefetch;
    }
};

// Everything the tool can find, in report order.
std::vector<Residue> CollectResidues();

ResidueTotals Summarize(const std::vector<Residue> &items);

// Totals only, for callers that need a number and not the prose (the tray menu
// shows the count on every open).
ResidueTotals CurrentTotals();

// "3 项" / "3 items". Exposed so the menu label and the report body agree on how
// a count is spelled, plurals included.
std::wstring FormatItemCount(int n);

// Human-readable report in the current UI language. places/bytes (optional)
// receive the same totals as CurrentTotals().
std::wstring BuildResidueReport(int *places = nullptr, DWORD *bytes = nullptr);

// Remove everything removable. The exe and the in-memory window marks are
// deliberately not touched.
CleanReport CleanAll();

// Live state of the acceleration marks. In-memory only: nothing here touches
// disk, and everything disappears with the explorer process.
//
// The unit is the WINDOW, not the tab: F11 is handled by the window frame, so
// one round trip covers every tab in that window at once. `tabs` is the number
// of tabs those marked windows currently hold - it describes their contents,
// not a second thing that was accelerated separately.
struct WindowMarks {
    int windows = 0;
    int tabs    = 0;
};

WindowMarks MarkedWindows();

// "已加速 1 个窗口（含 2 个选项卡）" / "1 window accelerated (2 tabs)".
// The single source of this sentence: the tooltip, the menu header and the
// residue report all call it, so the three can never disagree.
std::wstring AcceleratedText(const WindowMarks &m);

}  // namespace ef11

#endif  // EF11_RESIDUE_H
