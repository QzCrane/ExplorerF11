// Which icon-loading API drags in the imaging stack?
//
// The suspect was the PNG-compressed frames in the .ico, and that is what it
// was: loading a PNG frame through LoadImageW brings WindowsCodecs.dll into the
// process, and loading a DIB frame through the same call does not. The other two
// APIs agree - neither loads the decoder for a DIB frame - so the container, not
// the API, is the variable. This tool builds the same 16x16 icon three ways -
// LoadImageW from a file, CreateIconFromResourceEx from the raw DIB, and
// CreateIconIndirect from manually parsed pixels - and parks for a few seconds so
// an outside observer can list the modules each one leaves behind.
//
//   icon_probe.exe <mode> <ico path> [hash]   mode: load | resource | indirect

#define WIN32_LEAN_AND_MEAN
#ifndef UNICODE
#define UNICODE
#endif
#ifndef _UNICODE
#define _UNICODE
#endif
#include <windows.h>
#include <cstdio>
#include <cstdlib>
#include <vector>

struct Entry {
    int w, h;
    unsigned size, offset;
};

static std::vector<Entry> ReadDir(const std::vector<unsigned char> &data) {
    std::vector<Entry> out;
    if (data.size() < 6) return out;
    const unsigned count = *(const unsigned short *)(data.data() + 4);
    for (unsigned i = 0; i < count; ++i) {
        const unsigned char *p = data.data() + 6 + i * 16;
        Entry e;
        e.w = p[0] ? p[0] : 256;
        e.h = p[1] ? p[1] : 256;
        e.size = *(const unsigned *)(p + 8);
        e.offset = *(const unsigned *)(p + 12);
        out.push_back(e);
    }
    return out;
}

int wmain(int argc, wchar_t **argv) {
    if (argc < 3) {
        std::printf("usage: icon_probe.exe <load|resource|indirect> <ico>\n");
        return 2;
    }
    const wchar_t *mode = argv[1];

    HANDLE f = CreateFileW(argv[2], GENERIC_READ, FILE_SHARE_READ, NULL,
                           OPEN_EXISTING, 0, NULL);
    if (f == INVALID_HANDLE_VALUE) {
        std::printf("cannot open %ls\n", argv[2]);
        return 1;
    }
    LARGE_INTEGER sz = {};
    GetFileSizeEx(f, &sz);
    std::vector<unsigned char> data((size_t)sz.QuadPart);
    DWORD got = 0;
    ReadFile(f, data.data(), (DWORD)data.size(), &got, NULL);
    CloseHandle(f);
    data.resize(got);

    auto dir = ReadDir(data);
    // Pick 16x16 if present, else the smallest.
    const Entry *pick = NULL;
    for (const auto &e : dir)
        if (e.w == 16 && e.h == 16) { pick = &e; break; }
    if (!pick)
        for (const auto &e : dir)
            if (!pick || e.w < pick->w) pick = &e;
    if (!pick) {
        std::printf("no images in file\n");
        return 1;
    }
    std::printf("using %dx%d, %u bytes at %u\n", pick->w, pick->h, pick->size,
                pick->offset);
    const unsigned char *blob = data.data() + pick->offset;

    HICON icon = NULL;
    if (wcscmp(mode, L"load") == 0) {
        icon = (HICON)LoadImageW(NULL, argv[2], IMAGE_ICON, pick->w, pick->h,
                                 LR_LOADFROMFILE);
    } else if (wcscmp(mode, L"resource") == 0) {
        // The DIB blob as stored in an .ico is exactly what this API expects.
        icon = (HICON)CreateIconFromResourceEx((PBYTE)blob, pick->size, TRUE,
                                               0x00030000, pick->w, pick->h, 0);
    } else if (wcscmp(mode, L"indirect") == 0) {
        // Parse the DIB by hand: header, BGRA pixels bottom-up, then an
        // all-zero AND mask. Same job the shell would do, no decoder involved.
        const BITMAPINFOHEADER *bi = (const BITMAPINFOHEADER *)blob;
        if (bi->biSize != 40 || bi->biBitCount != 32) {
            std::printf("unexpected DIB %u/%u\n", bi->biSize, bi->biBitCount);
            return 1;
        }
        const int w = bi->biWidth, h = bi->biHeight / 2;
        const unsigned char *px = blob + bi->biSize;
        BITMAPV5HEADER bh = {};
        bh.bV5Size = sizeof(bh);
        bh.bV5Width = w;
        bh.bV5Height = h;
        bh.bV5Planes = 1;
        bh.bV5BitCount = 32;
        bh.bV5Compression = BI_BITFIELDS;
        bh.bV5RedMask = 0x00FF0000;
        bh.bV5GreenMask = 0x0000FF00;
        bh.bV5BlueMask = 0x000000FF;
        bh.bV5AlphaMask = 0xFF000000;
        void *bits = NULL;
        HDC dc = GetDC(NULL);
        HBITMAP color = CreateDIBSection(dc, (BITMAPINFO *)&bh, DIB_RGB_COLORS,
                                         &bits, NULL, 0);
        ReleaseDC(NULL, dc);
        if (color && bits) memcpy(bits, px, (size_t)w * h * 4);
        HBITMAP mask = CreateBitmap(w, h, 1, 1, NULL);
        ICONINFO ii = {};
        ii.fIcon = TRUE;
        ii.hbmMask = mask;
        ii.hbmColor = color;
        icon = CreateIconIndirect(&ii);
        if (color) DeleteObject(color);
        if (mask) DeleteObject(mask);
    } else {
        std::printf("unknown mode\n");
        return 2;
    }

    std::printf("icon = %p\n", (void *)icon);

    if (icon && argc > 3 && wcscmp(argv[3], L"hash") == 0) {
        // Read the pixels back out of the HICON the way a painter sees them:
        // GetIconInfo hands over the colour bitmap, GetDIBits reads it as 32-bit
        // BGRA top-down. This hash must equal the source image's, otherwise
        // "same bytes" was only true of the file, not of what gets drawn.
        ICONINFO ii = {};
        if (GetIconInfo(icon, &ii)) {
            BITMAP bm = {};
            GetObjectW(ii.hbmColor, sizeof(bm), &bm);
            BITMAPINFO bi = {};
            bi.bmiHeader.biSize = sizeof(BITMAPINFOHEADER);
            bi.bmiHeader.biWidth = bm.bmWidth;
            bi.bmiHeader.biHeight = -bm.bmHeight;   // top-down
            bi.bmiHeader.biPlanes = 1;
            bi.bmiHeader.biBitCount = 32;
            bi.bmiHeader.biCompression = BI_RGB;
            std::vector<unsigned char> px((size_t)bm.bmWidth * bm.bmHeight * 4);
            HDC dc = GetDC(NULL);
            int lines = GetDIBits(dc, ii.hbmColor, 0, bm.bmHeight, px.data(), &bi,
                                  DIB_RGB_COLORS);
            ReleaseDC(NULL, dc);
            unsigned long long h = 1469598103934665603ULL;
            for (unsigned char c : px) { h ^= c; h *= 1099511628211ULL; }
            std::printf("pixels %ldx%ld, %d lines, fnv %016llx\n", bm.bmWidth,
                        bm.bmHeight, lines, h);
            DeleteObject(ii.hbmColor);
            DeleteObject(ii.hbmMask);
        }
    }
    // Stay alive so the modules this call pulled in can be observed.
    Sleep(3000);
    if (icon) DestroyIcon(icon);
    return 0;
}
