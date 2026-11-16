#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Synchronise the translation key table with the T() calls in the sources.

The pipeline has four stages:

    src/*.cpp  --extract-->  tools/i18n_strings.json   (keys, in source order)
               --translate-> tools/translations.json   (the only hand-edited file)
               --generate--> src/i18n_extra.cpp        (compiled in)

This script owns stage one. It preserves the existing row order so that adding
one T() call does not reshuffle the generated table, appends genuinely new keys
at the end, and drops keys that no longer exist in the sources. It then reports
which new keys still need a translation, and regenerates the C++ table.

Run:  python tools/sync_i18n.py
"""

import sys as _sys

# These tools print translated strings, which are Chinese, Japanese or Korean on
# a machine whose console code page cannot represent them. Force UTF-8 so a
# finding is reported instead of turning into UnicodeEncodeError.
if hasattr(_sys.stdout, "reconfigure"):
    _sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import io
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import extract_i18n_pairs as ex
import gen_i18n

SRC = [os.path.join(ROOT, 'src', 'main.cpp'),
       os.path.join(ROOT, 'src', 'residue.cpp')]
STRINGS = os.path.join(HERE, 'i18n_strings.json')
TRANS = os.path.join(HERE, 'translations.json')


def main():
    # Source order, first occurrence wins: the same zh key may legitimately be
    # written at several call sites with different English (singular/plural).
    found = []
    seen = set()
    for path in SRC:
        for zh, en in ex.extract(path):
            if zh in seen:
                continue
            seen.add(zh)
            found.append((zh, en))

    frames = json.load(io.open(STRINGS, encoding='utf-8'))
    trans = json.load(io.open(TRANS, encoding='utf-8'))

    by_zh = {zh: en for zh, en in found}
    rows = []
    kept = set()
    for row in frames:
        zh = row['zh']
        if zh in by_zh:
            rows.append({'zh': zh, 'en': by_zh[zh]})
            kept.add(zh)
    added = [zh for zh, _ in found if zh not in kept]
    for zh in added:
        rows.append({'zh': zh, 'en': by_zh[zh]})
    dropped = [r['zh'] for r in frames if r['zh'] not in by_zh]

    with io.open(STRINGS, 'w', encoding='utf-8', newline='\n') as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)
        f.write('\n')

    untranslated = [zh for zh in by_zh if zh not in trans]
    for zh in untranslated:
        trans[zh] = ['', '', '']
    orphan = [zh for zh in trans if zh not in by_zh]
    for zh in orphan:
        del trans[zh]
    if untranslated or orphan:
        with io.open(TRANS, 'w', encoding='utf-8', newline='\n') as f:
            json.dump(trans, f, ensure_ascii=False, indent=2)
            f.write('\n')

    # Regenerate the compiled table only when every row is complete; otherwise
    # the empty strings would ship as untranslated fallbacks.
    incomplete = [zh for zh in by_zh if not all(v.strip() for v in trans[zh])]
    if not incomplete:
        gen_i18n.main()

    print('keys: %d (added %d, dropped %d)' % (len(rows), len(added), len(dropped)))
    for zh in added:
        print('  + %s' % zh.replace('\n', '\\n')[:90])
    for zh in dropped:
        print('  - %s' % zh.replace('\n', '\\n')[:90])
    if incomplete:
        print('\n%d key(s) still need a translation:' % len(incomplete))
        for zh in incomplete:
            print('  ? %s' % zh.replace('\n', '\\n')[:90])
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
