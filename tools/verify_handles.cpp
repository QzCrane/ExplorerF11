// Does the residue pass leak handles?
//
// The report opens a dozen registry keys per row and walks the UserAssist tree
// value by value. Every RegOpenKeyExW has a matching RegCloseKey on every return
// path by inspection, but inspection is how leaks survive. This calls the real
// collection and report builders many times in one process and watches the
// handle count: a leak of one handle per pass shows up as a straight line, a
// correct implementation stays flat.
//
//   verify_handles.exe [iterations]

#define WIN32_LEAN_AND_MEAN
#ifndef UNICODE
#define UNICODE
#endif
#ifndef _UNICODE
#define _UNICODE
#endif
#include <windows.h>
#include <psapi.h>
#include <cstdio>
#include <cstdlib>

#include "residue.h"
using namespace ef11;

static DWORD Handles() {
    DWORD n = 0;
    GetProcessHandleCount(GetCurrentProcess(), &n);
    return n;
}

static void PrivateBytes(unsigned long long *privateKb, unsigned long long *peakKb) {
    PROCESS_MEMORY_COUNTERS_EX mc = {};
    if (GetProcessMemoryInfo(GetCurrentProcess(), (PROCESS_MEMORY_COUNTERS *)&mc,
                             sizeof(mc))) {
        *privateKb = mc.PrivateUsage / 1024;
        *peakKb = mc.PeakWorkingSetSize / 1024;
    }
}

static int failures = 0;

static void Check(const char *what, DWORD got, DWORD want) {
    const bool ok = (got <= want);   // may free something, must never grow
    std::printf("  %-40s %4lu -> %4lu  %s\n", what, (unsigned long)want,
                (unsigned long)got, ok ? "ok" : "GROWTH");
    if (!ok) ++failures;
}

int main(int argc, char **argv) {
    const int iters = (argc > 1) ? atoi(argv[1]) : 1000;

    // Touch everything once so lazy one-time allocations (CRT locale, registry
    // caches) are already done when the baseline is taken.
    CollectResidues();
    BuildResidueReport();

    const DWORD base = Handles();
    unsigned long long priv0 = 0, peak0 = 0;
    PrivateBytes(&priv0, &peak0);
    std::printf("baseline: %lu handles, %llu KB private\n\n",
                (unsigned long)base, priv0);

    // 1. Full collection, the path behind --status and the report window.
    for (int i = 0; i < iters; ++i) CollectResidues();
    const DWORD afterCollect = Handles();
    Check("CollectResidues", afterCollect, base);

    // 2. Presence-only collection, the path behind the tray menu label.
    for (int i = 0; i < iters; ++i) CollectResidues(NULL, true);
    const DWORD afterPresence = Handles();
    Check("CollectResidues(presenceOnly)", afterPresence, afterCollect);

    // 3. Full report build, the path behind --status and a report refresh.
    for (int i = 0; i < iters; ++i) BuildResidueReport();
    const DWORD afterReport = Handles();
    Check("BuildResidueReport", afterReport, afterPresence);

    // 4. Totals and category count.
    for (int i = 0; i < iters; ++i) {
        CurrentTotals();
        CurrentResidueCategories();
    }
    const DWORD afterTotals = Handles();
    Check("CurrentTotals + Categories", afterTotals, afterReport);

    // 5. Window mark reads, which the new maintained set made cheap.
    for (int i = 0; i < iters; ++i) MarkedWindows();
    const DWORD afterMarks = Handles();
    Check("MarkedWindows", afterMarks, afterTotals);

    unsigned long long priv1 = 0, peak1 = 0;
    PrivateBytes(&priv1, &peak1);
    std::printf("\nprivate after %d passes of each: %llu KB (was %llu KB), "
                "peak working set %llu KB\n",
                iters, priv1, priv0, peak1);

    // A handle count that returns to baseline but private bytes that climb
    // would be a cache or an arena, not a leak; report both.
    std::printf("\n%s\n", failures == 0 ? "ALL PASS - no handle growth"
                                        : "FAILURES - handle count grew");
    return failures == 0 ? 0 : 1;
}
