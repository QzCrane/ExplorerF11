#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A fingerprint of the tree a gate run applied to.

The release pipeline used to run the whole suite twice: once inside
`make refresh-facts`, which needs each suite's assertion count, and again as the
`gates` stage, which needs to know that the suite passes. Two runs of the same
thirteen commands on the same tree prove the same thing, and the second one
proved it about a tree that had meanwhile changed only in the two files the
first run wrote.

This module is how the second run is skipped without weakening the claim. The
first run records the fingerprint of the tree it ran against; the `gates` stage
recomputes it and compares. Same digest means the record describes this tree
byte for byte, so re-running would ask the same questions of the same bytes.

Contents, not timestamps: a file restored from a backup with an old mtime must
still change the digest, and a file rewritten with identical bytes must not.
"""

import hashlib
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Directories that hold either version-control internals, ignored build output,
# or this project's own working notes. None of them can change a gate's verdict.
SKIP_DIRS = {".git", ".workbuddy", ".workbuddy-ai", "dist", "__pycache__",
             ".pytest_cache", ".mypy_cache"}


def files(root=ROOT):
    """Every file a gate could read, as paths relative to the root, sorted."""
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
        for name in sorted(filenames):
            full = os.path.join(dirpath, name)
            out.append(os.path.relpath(full, root).replace("\\", "/"))
    return out


def fingerprint(root=ROOT):
    """SHA-256 over (path, size, content) of every file under the root."""
    h = hashlib.sha256()
    for rel in files(root):
        full = os.path.join(root, rel)
        try:
            with open(full, "rb") as fh:
                data = fh.read()
        except OSError:
            # A file that vanished between the walk and the read cannot be
            # fingerprinted; record the fact rather than silently skipping it.
            data = None
        h.update(rel.encode("utf-8"))
        h.update(b"\x00")
        if data is None:
            h.update(b"\x00missing")
        else:
            h.update(str(len(data)).encode("ascii"))
            h.update(b"\x00")
            h.update(data)
    return h.hexdigest()


if __name__ == "__main__":
    print(fingerprint())
