#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Extract (zh, en) pairs from every T() call with a robust two-arg lexer."""
import re, sys, json, os

def parse_wstring(src, i):
    # i points at 'L'
    assert src[i] == 'L' and src[i+1] == '"'
    i += 2
    out = []
    n = len(src)
    while i < n:
        c = src[i]
        if c == '"':
            i += 1
            j = i
            while j < n and src[j] in ' \t\r\n':
                j += 1
            if j + 1 < n and src[j] == 'L' and src[j+1] == '"':
                i = j + 2
                continue
            return ''.join(out), i
        if c == '\\':
            i += 1
            e = src[i]
            if e == 'u': out.append(chr(int(src[i+1:i+5],16))); i += 5
            elif e == 'U': out.append(chr(int(src[i+1:i+9],16))); i += 9
            elif e == 'n': out.append('\n'); i += 1
            elif e == 't': out.append('\t'); i += 1
            elif e == 'r': out.append('\r'); i += 1
            elif e == '\\': out.append('\\'); i += 1
            elif e == '"': out.append('"'); i += 1
            else: out.append(e); i += 1
        else:
            out.append(c); i += 1
    raise RuntimeError('unterminated')

def skip_ws(src, i):
    while i < len(src) and src[i] in ' \t\r\n': i += 1
    return i

def read_arg(src, i):
    i = skip_ws(src, i)
    if i + 1 < len(src) and src[i] == 'L' and src[i+1] == '"':
        return parse_wstring(src, i)
    return None, i  # non-literal arg (variable) -> skip

def extract(path):
    src = open(path, encoding='utf-8').read()
    pairs = []
    for m in re.finditer(r'\bT\s*\(', src):
        i = m.end()
        a, i = read_arg(src, i)
        if a is None: continue
        i = skip_ws(src, i)
        if i >= len(src) or src[i] != ',': continue
        b, i = read_arg(src, i + 1)
        if b is None: continue
        pairs.append((a, b))
    return pairs

if __name__ == '__main__':
    pairs = []
    for p in sys.argv[1:]:
        pairs.extend(extract(p))
    json.dump(pairs, open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                       '_i18n_pairs.json'), 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1)
    print('pairs:', len(pairs))
