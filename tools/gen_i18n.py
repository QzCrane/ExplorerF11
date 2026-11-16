#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Generate src/i18n_extra.cpp from the translation data.

Data sources (both keyed by Simplified Chinese, NOT by position):
  tools/i18n_strings.json   ordered list of {zh, en} keys (order = table order)
  tools/translations.json   { zh: [zhHant, ja, ko] }

Keying by text makes the table immune to source reordering and to new T() calls
appearing in the middle of a file. tools/check_i18n.py fails if any source key
is absent from translations.json, so a missing translation cannot ship.

Run:  python tools/gen_i18n.py
"""
import io, json, os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

def cwstr(s):
    """Escape a Python str as a C++ wide string literal body (no L prefix)."""
    out = []
    for ch in s:
        o = ord(ch)
        if ch == '\\': out.append('\\\\')
        elif ch == '"': out.append('\\"')
        elif ch == '\n': out.append('\\n')
        elif ch == '\r': out.append('\\r')
        elif ch == '\t': out.append('\\t')
        elif 0x20 <= o < 0x7f: out.append(ch)
        else: out.append('\\u%04X' % o)
    return ''.join(out)

def load():
    frames = json.load(io.open(os.path.join(HERE, 'i18n_strings.json'), encoding='utf-8'))
    trans = json.load(io.open(os.path.join(HERE, 'translations.json'), encoding='utf-8'))
    return frames, trans

def build_lines(frames, trans):
    L = []
    add = L.append
    add('// SPDX-License-Identifier: MIT')
    add('// GENERATED FILE - do not edit. Run: python tools/gen_i18n.py')
    add('// Sources: tools/i18n_strings.json + tools/translations.json')
    add('//')
    add('// Translation table for the three languages not inlined at the T() call')
    add('// site. Keyed by the Simplified Chinese original. A miss returns nullptr')
    add('// and T() falls back to the inline English text.')
    add('#include "i18n.h"')
    add('')
    add('namespace ef11 {')
    add('namespace {')
    add('')
    add('struct Row { const wchar_t *zh, *zhHant, *ja, *ko; };')
    add('')
    add('// Order matches tools/i18n_strings.json; lookup is by zh text.')
    add('static const Row ROWS[] = {')
    for row in frames:
        zh = row['zh']
        hant, ja, ko = trans[zh]
        add('    { L"%s", L"%s", L"%s", L"%s" },' % (
            cwstr(zh), cwstr(hant), cwstr(ja), cwstr(ko)))
    add('};')
    add('static const int ROW_COUNT = (int)(sizeof(ROWS) / sizeof(ROWS[0]));')
    add('')
    add('}  // namespace')
    add('')
    add('const wchar_t *TranslateExtra(const wchar_t *zh, Lang lang) {')
    add('    if (!zh) return nullptr;')
    add('    for (int i = 0; i < ROW_COUNT; ++i) {')
    add('        if (wcscmp(ROWS[i].zh, zh) != 0) continue;')
    add('        switch (lang) {')
    add('        case Lang::ZhHant: return ROWS[i].zhHant;')
    add('        case Lang::Ja:     return ROWS[i].ja;')
    add('        case Lang::Ko:     return ROWS[i].ko;')
    add('        default:           return nullptr;')
    add('        }')
    add('    }')
    add('    return nullptr;')
    add('}')
    add('')
    add('}  // namespace ef11')
    add('')
    return L

def main():
    frames, trans = load()
    lines = build_lines(frames, trans)
    out = os.path.join(ROOT, 'src', 'i18n_extra.cpp')
    with io.open(out, 'w', encoding='utf-8', newline='\n') as f:
        f.write('\n'.join(lines))
    print('generated', out, 'with', len(frames), 'rows')

if __name__ == '__main__':
    main()
