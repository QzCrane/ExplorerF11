// Address-space autopsy for a running ExplorerF11 process.
//
// Working set is mostly shared DLL pages and says little about what this program
// costs; private commit does. This walks the target's address space with
// VirtualQueryEx and groups committed pages by type and protecting, then lists
// the largest regions so the bytes can be attributed to a subsystem (heap, stack,
// image, mapped file) instead of guessed at.
//
//   cl /EHsc measure_mem.cpp                      (or the g++ line in the Makefile)
//   measure_mem.exe <pid> [topN]

#define WIN32_LEAN_AND_MEAN
#ifndef UNICODE
#define UNICODE
#endif
#ifndef _UNICODE
#define _UNICODE
#endif
#include <windows.h>
#include <psapi.h>
#include <algorithm>
#include <cstdio>
#include <cstdlib>
#include <map>
#include <string>
#include <vector>

static const wchar_t *TypeName(DWORD t) {
    switch (t) {
        case MEM_IMAGE:   return L"image";
        case MEM_MAPPED:  return L"mapped";
        case MEM_PRIVATE: return L"private";
        default:          return L"?";
    }
}

static std::wstring ProtectName(DWORD p) {
    // Strip the modifier bits for grouping.
    switch (p & 0xFF) {
        case PAGE_NOACCESS:          return L"noaccess";
        case PAGE_READONLY:          return L"r";
        case PAGE_READWRITE:         return L"rw";
        case PAGE_WRITECOPY:         return L"wc";
        case PAGE_EXECUTE:           return L"x";
        case PAGE_EXECUTE_READ:      return L"xr";
        case PAGE_EXECUTE_READWRITE: return L"xrw";
        case PAGE_EXECUTE_WRITECOPY: return L"xwc";
        default:                     return L"?";
    }
}

struct Region {
    ULONG_PTR base;
    SIZE_T    size;      // committed part
    SIZE_T    reserved;  // whole reservation
    DWORD     type;
    DWORD     protect;
    std::wstring module;
};

int wmain(int argc, wchar_t **argv) {
    if (argc < 2) {
        std::printf("usage: measure_mem.exe <pid> [topN]\n");
        return 2;
    }
    const DWORD pid = (DWORD)_wtoi(argv[1]);
    const int topN = (argc > 2) ? _wtoi(argv[2]) : 12;

    HANDLE h = OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, FALSE, pid);
    if (!h) {
        std::printf("OpenProcess failed: %lu\n", GetLastError());
        return 1;
    }

    PROCESS_MEMORY_COUNTERS_EX mc = {};
    if (GetProcessMemoryInfo(h, (PROCESS_MEMORY_COUNTERS *)&mc, sizeof(mc))) {
        std::printf("PrivateUsage      : %8llu KB\n",
                    (unsigned long long)(mc.PrivateUsage / 1024));
        std::printf("WorkingSetSize    : %8llu KB\n",
                    (unsigned long long)(mc.WorkingSetSize / 1024));
        std::printf("PeakWorkingSetSize: %8llu KB\n",
                    (unsigned long long)(mc.PeakWorkingSetSize / 1024));
        std::printf("PagefileUsage     : %8llu KB\n\n",
                    (unsigned long long)(mc.PagefileUsage / 1024));
    }

    std::vector<Region> regions;
    ULONG_PTR addr = 0;
    MEMORY_BASIC_INFORMATION mbi = {};

    while (VirtualQueryEx(h, (LPCVOID)addr, &mbi, sizeof(mbi)) == sizeof(mbi)) {
        if (mbi.State == MEM_COMMIT && mbi.RegionSize) {
            Region r;
            r.base     = (ULONG_PTR)mbi.BaseAddress;
            r.size     = mbi.RegionSize;
            r.reserved = mbi.RegionSize;
            r.type     = mbi.Type;
            r.protect  = mbi.Protect;
            wchar_t path[MAX_PATH * 2] = {0};
            if (mbi.Type == MEM_IMAGE &&
                GetMappedFileNameW(h, mbi.BaseAddress, path, MAX_PATH * 2)) {
                const wchar_t *slash = wcsrchr(path, L'\\');
                r.module = slash ? slash + 1 : path;
            }
            regions.push_back(r);
        }
        const ULONG_PTR next = (ULONG_PTR)mbi.BaseAddress + mbi.RegionSize;
        if (next <= addr) break;   // guard against a stalled query
        addr = next;
    }

    // Group by type and protecting.
    std::map<std::wstring, std::pair<SIZE_T, int>> groups;
    SIZE_T committedTotal = 0;
    for (const Region &r : regions) {
        wchar_t key[96];
        swprintf(key, 96, L"%-7ls %-7ls", TypeName(r.type), ProtectName(r.protect).c_str());
        groups[key].first += r.size;
        groups[key].second += 1;
        committedTotal += r.size;
    }

    std::printf("committed virtual: %llu KB across %zu regions\n\n",
                (unsigned long long)(committedTotal / 1024), regions.size());
    std::printf("%-18s %10s %8s\n", "type/prot", "KB", "regions");
    for (const auto &kv : groups)
        std::printf("%-18s %10llu %8d\n", kv.first.c_str(),
                    (unsigned long long)(kv.second.first / 1024), kv.second.second);

    // Per-module commit, so a heavy dependency is visible as a dependency.
    std::map<std::wstring, SIZE_T> byModule;
    for (const Region &r : regions)
        if (!r.module.empty()) byModule[r.module] += r.size;
    std::printf("\nimage commit by module (top 10):\n");
    std::vector<std::pair<SIZE_T, std::wstring>> mods;
    for (const auto &kv : byModule) mods.push_back({kv.second, kv.first});
    std::sort(mods.rbegin(), mods.rend());
    for (size_t i = 0; i < mods.size() && i < 10; ++i)
        std::printf("  %-28ls %9llu KB\n", mods[i].second.c_str(),
                    (unsigned long long)(mods[i].first / 1024));

    // Private regions only: this is the memory the program actually owns.
    std::vector<Region> priv;
    for (const Region &r : regions)
        if (r.type == MEM_PRIVATE) priv.push_back(r);
    std::sort(priv.begin(), priv.end(),
              [](const Region &a, const Region &b) { return a.size > b.size; });
    SIZE_T privTotal = 0;
    for (const Region &r : priv) privTotal += r.size;
    std::printf("\nMEM_PRIVATE total: %llu KB in %zu regions\n",
                (unsigned long long)(privTotal / 1024), priv.size());
    for (size_t i = 0; i < priv.size() && i < 12; ++i)
        std::printf("  0x%016llX %8llu KB  %-6ls\n",
                    (unsigned long long)priv[i].base,
                    (unsigned long long)(priv[i].size / 1024),
                    ProtectName(priv[i].protect).c_str());

    // Largest committed regions.
    std::sort(regions.begin(), regions.end(),
              [](const Region &a, const Region &b) { return a.size > b.size; });
    std::printf("\nlargest %d committed regions:\n", topN);
    std::printf("%-18s %10s  %-8s %-6s %s\n", "base", "KB", "type", "prot", "module");
    for (int i = 0; i < topN && i < (int)regions.size(); ++i) {
        const Region &r = regions[i];
        std::printf("0x%016llX %10llu  %-8ls %-6ls %ls\n",
                    (unsigned long long)r.base, (unsigned long long)(r.size / 1024),
                    TypeName(r.type), ProtectName(r.protect).c_str(),
                    r.module.empty() ? L"-" : r.module.c_str());
    }

    CloseHandle(h);
    return 0;
}
