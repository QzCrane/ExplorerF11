#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Guard the translation pipeline. Non-zero exit = build must fail.

Checks:
  1. Every T(zh, en) call site's zh key appears in translations.json.
  2. Every source key is in i18n_strings.json and vice versa (no stale rows).
  3. Every translation is non-empty and keeps %d / %TEMP% / %WINDIR% balanced.
  4. src/i18n_extra.cpp matches a fresh generation (no stale table shipped).

Run:  python tools/check_i18n.py
"""
import io, json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import extract_i18n_pairs as ex
import gen_i18n

SRC = [os.path.join(ROOT, 'src', 'main.cpp'),
       os.path.join(ROOT, 'src', 'residue.cpp')]
STRINGS = os.path.join(HERE, 'i18n_strings.json')
TRANS = os.path.join(HERE, 'translations.json')
CPP = os.path.join(ROOT, 'src', 'i18n_extra.cpp')

errors = []
def fail(msg):
    errors.append(msg)
    print('FAIL', msg)

# --- 1. keys from source ----------------------------------------------------
pairs = []
for p in SRC:
    pairs.extend(ex.extract(p))
src_keys = set(z for z, e in pairs)

# --- 2. load data -----------------------------------------------------------
frames = json.load(io.open(STRINGS, encoding='utf-8'))
trans = json.load(io.open(TRANS, encoding='utf-8'))
frame_keys = set(r['zh'] for r in frames)
trans_keys = set(trans.keys())

for k in sorted(src_keys - frame_keys):
    fail('source key missing from i18n_strings.json: %r' % k[:70])
for k in sorted(frame_keys - src_keys):
    fail('stale key in i18n_strings.json: %r' % k[:70])
for k in sorted(src_keys - trans_keys):
    fail('source key missing translation: %r' % k[:70])
for k in sorted(trans_keys - src_keys):
    fail('orphan translation (key not in source): %r' % k[:70])

# --- 3. translation quality -------------------------------------------------
for zh, t in trans.items():
    if not isinstance(t, list) or len(t) != 3:
        fail('bad translation shape for %r' % zh[:60]); continue
    for name, val in zip(('zhHant', 'ja', 'ko'), t):
        if not val or not val.strip():
            fail('%s empty for %r' % (name, zh[:60])); continue
        for ph in ('%d', '%TEMP%', '%WINDIR%'):
            if val.count(ph) != zh.count(ph):
                fail('%s placeholder %s mismatch for %r (zh=%d, t=%d)' % (
                    name, ph, zh[:50], zh.count(ph), val.count(ph)))

# --- 4. generated file current ----------------------------------------------
expected = '\n'.join(gen_i18n.build_lines(frames, trans))
actual = io.open(CPP, encoding='utf-8').read()
if actual.rstrip('\n') != expected.rstrip('\n'):
    fail('src/i18n_extra.cpp is stale - run python tools/gen_i18n.py')

if errors:
    print('\n%d problem(s). Translation gate FAILED.' % len(errors))
    sys.exit(1)
print('i18n OK: %d call sites, %d unique keys, %d languages, table current.' %
      (len(pairs), len(src_keys), 5))
