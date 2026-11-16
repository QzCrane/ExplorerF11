#!/usr/bin/env python3
"""Rewrite the small images in an .ico from PNG to BMP, keeping the large ones.

Why: Windows decodes a PNG-compressed icon through WIC, and that single call
loads WindowsCodecs.dll into the process - 2.3 MB of code pages for a 16x16 tray
bitmap. A DIB-compressed image needs no decoder; the pixels are identical, only
the container changes.

The large sizes stay PNG. Explorer decodes those in its own process when it draws
a 256x256 thumbnail, so they cost this program nothing and keep the file small.

This is both a library (`rewrite_file`, called by make-icons.py so a regenerated
icon is correct by construction) and a command:

    make_ico_bmp.py <in.ico> <out.ico> [--convert 16,20,24,32,40,48]

The rewrite is byte-faithful in pixels: each PNG is decoded, its RGBA copied, and
written back as BI_RGB with a 32-bit DIB plus the AND mask the format requires.
Every converted image is then decoded again and compared byte for byte against
the source, so a silent colour or alpha change cannot slip through.
"""

import io
import struct
import sys

try:
    from PIL import Image
except ImportError:                                   # pragma: no cover
    sys.exit("Pillow is required: python -m pip install pillow")

# The sizes this program asks for: every DPI a tray icon and a title bar use.
# 64 and up stay PNG for Explorer's larger views.
SMALL_SIZES = frozenset({(16, 16), (20, 20), (24, 24), (32, 32), (40, 40), (48, 48)})


def read_ico(data):
    """Return (list of entries, list of blobs). Entries keep the raw header fields."""
    reserved, kind, count = struct.unpack_from("<HHH", data, 0)
    if reserved != 0 or kind != 1:
        raise ValueError("not an icon file")
    entries, blobs = [], []
    for i in range(count):
        off = 6 + i * 16
        w, h, colors, res, planes, bpp, size, img_off = struct.unpack_from(
            "<BBBBHHII", data, off)
        entries.append({
            "w": w or 256, "h": h or 256, "colors": colors, "reserved": res,
            "planes": planes, "bpp": bpp, "size": size, "offset": img_off,
        })
        blobs.append(data[img_off:img_off + size])
    return entries, blobs


def png_to_dib(png_bytes):
    """PNG bytes -> (32-bit BI_RGB DIB body, AND mask), bottom-up as the format wants."""
    im = Image.open(io.BytesIO(png_bytes)).convert("RGBA")
    w, h = im.size
    px = im.load()

    # XOR bitmap: 32 bpp BGRA, rows bottom-up.
    rows = []
    for y in range(h - 1, -1, -1):
        row = bytearray()
        for x in range(w):
            r, g, b, a = px[x, y]
            row += bytes((b, g, r, a))
        rows.append(bytes(row))
    xor = b"".join(rows)

    # AND mask: 1 bpp, every pixel opaque because alpha is in the XOR bitmap.
    # The mask row is padded to a 4-byte boundary; zeros mean "draw the XOR data".
    mask_stride = ((w + 31) // 32) * 4
    mask = b"\x00" * (mask_stride * h)

    header = struct.pack("<IiiHHIIiiII",
                         40,        # biSize
                         w,         # biWidth
                         h * 2,     # biHeight: XOR + AND stacked
                         1,         # biPlanes
                         32,        # biBitCount
                         0,         # biCompression = BI_RGB
                         len(xor),  # biSizeImage
                         0, 0, 0, 0)
    return header + xor + mask


def is_png(blob):
    return blob[:8] == b"\x89PNG\r\n\x1a\n"


def dib_to_rgba(dib):
    """Pixels out of an .ico DIB.

    Not opened through PIL: an icon DIB declares biHeight = 2 * height (XOR plus
    AND), which a standalone BMP reader interprets as twice as many 32-bit rows
    and rejects as truncated. Reading it directly is both simpler and stricter.
    """
    size, w, h2, planes, bpp, comp, _img = struct.unpack_from("<IiiHHII", dib, 0)
    if size != 40 or bpp != 32 or comp != 0 or h2 % 2:
        raise ValueError("unexpected DIB header: %d/%d/%d" % (size, bpp, comp))
    h = h2 // 2
    stride = w * 4
    if len(dib) < 40 + stride * h:
        raise ValueError("DIB shorter than its header claims")
    out = bytearray()
    for y in range(h):
        row = 40 + (h - 1 - y) * stride      # stored bottom-up
        for x in range(w):
            b, g, r, a = dib[row + x * 4: row + x * 4 + 4]
            out += bytes((r, g, b, a))
    return bytes(out), (w, h)


def build_ico(entries, blobs, convert_set):
    """Reassemble with the converted images as DIB and the rest untouched."""
    out_blobs = []
    for e, blob in zip(entries, blobs):
        if (e["w"], e["h"]) in convert_set and is_png(blob):
            out_blobs.append((png_to_dib(blob), 32))
        else:
            out_blobs.append((blob, e["bpp"]))

    header = struct.pack("<HHH", 0, 1, len(entries))
    offset = 6 + 16 * len(entries)
    dir_entries = b""
    body = b""
    for e, (blob, bpp) in zip(entries, out_blobs):
        w = 0 if e["w"] == 256 else e["w"]
        h = 0 if e["h"] == 256 else e["h"]
        dir_entries += struct.pack("<BBBBHHII", w, h, e["colors"], e["reserved"],
                                   e["planes"], bpp, len(blob), offset)
        body += blob
        offset += len(blob)
    return header + dir_entries + body


def verify(entries, blobs, out, convert_set, quiet=False):
    """Every converted image must decode back to the pixels it came from."""
    new_entries, new_blobs = read_ico(out)
    if len(new_entries) != len(entries):
        raise SystemExit("entry count changed")
    for e, old_blob, new_blob in zip(entries, blobs, new_blobs):
        size = (e["w"], e["h"])
        if size not in convert_set or not is_png(old_blob):
            continue
        a = Image.open(io.BytesIO(old_blob)).convert("RGBA")
        b_pixels, b_size = dib_to_rgba(new_blob)
        if a.size != b_size:
            raise SystemExit("size mismatch at %s: %s" % (size, b_size))
        if a.tobytes() != b_pixels:
            diff = sum(1 for x, y in zip(a.tobytes(), b_pixels) if x != y)
            raise SystemExit("pixel mismatch at %s: %d bytes" % (size, diff))
        if not quiet:
            print("  %2dx%-2d  PNG %6d B -> DIB %6d B   pixels identical"
                  % (e["w"], e["h"], len(old_blob), len(new_blob)))


def rewrite_bytes(data, convert_set=SMALL_SIZES, quiet=False):
    """PNG-compressed icon bytes -> the same icon with small sizes as DIB."""
    entries, blobs = read_ico(data)
    out = build_ico(entries, blobs, convert_set)
    verify(entries, blobs, out, convert_set, quiet)
    return out


def rewrite_file(src, dst=None, convert_set=SMALL_SIZES, quiet=False):
    """Rewrite an .ico on disk. `dst` defaults to rewriting in place."""
    src = str(src)
    dst = str(dst if dst is not None else src)
    with open(src, "rb") as f:
        data = f.read()
    out = rewrite_bytes(data, convert_set, quiet)
    with open(dst, "wb") as f:
        f.write(out)
    if not quiet:
        print("%s -> %s  (%d -> %d bytes)" % (src, dst, len(data), len(out)))
    return out


def main():
    if len(sys.argv) < 3:
        raise SystemExit(__doc__)
    convert = set(SMALL_SIZES)
    if "--convert" in sys.argv:
        spec = sys.argv[sys.argv.index("--convert") + 1]
        convert = set()
        for part in spec.split(","):
            n = int(part)
            convert.add((n, n))
    rewrite_file(sys.argv[1], sys.argv[2], convert)


if __name__ == "__main__":
    main()
