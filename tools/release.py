#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Take a clean checkout to a published, re-verified release in one command.

    make release                 # or: python tools/release.py
    make release ARGS=--dry-run  # build, gate and check, publish nothing

The manual checklist in docs/RELEASING.md is still the specification. This is
that checklist executed by a program, in the same order, with the same stops.

Why a program and not a document: every incident this repository has had was a
step executed out of order or a number copied by hand. v1.0.1 shipped the
previous release's body, hash and filename. v1.0.4 left its tag one commit
behind the notes. Both are ordering and transcription failures, and neither is
prevented by writing the rule down more firmly.

Two structural changes make them impossible here:

  * The release body is a template. Every fact in it - version, asset name,
    byte count, KiB, SHA-256, assertion count - is a placeholder filled from
    this build's measurements after the build succeeds. A hash cannot be
    transcribed wrongly because it is never transcribed.
  * The rendered body is committed before the tag. The tag's tree therefore
    contains the exact text that the release page shows, and
    check_github_sync.py compares them.

Stages are idempotent and resumable. `--from <stage>` re-enters at a stage after
an interruption; each one inspects the world before acting, so re-running is
always safe. `--dry-run` runs everything local and reversible — build, facts,
gates, captures, notes — then stops before `commit`. Nothing is committed,
pushed, tagged or published, and the tree is left as the run found it.

Exit codes: 0 published and verified, 1 a stage failed (the log names it),
2 the command line or the checkout is not releasable.
"""

import argparse
import datetime
from concurrent.futures import ThreadPoolExecutor
import hashlib
import importlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import release_facts as F  # noqa: E402
import treefp  # noqa: E402

STAGES = (
    "preflight",   # checkout, version, notes source, tag absence, gh auth
    "build",       # make -B, measure the artefact
    "sign",        # optional Authenticode signing, before anything is measured
    "facts",       # refresh release_facts.py + measurement.json from this build
    "gates",       # make test - all fourteen, on this exact tree
    "screenshots", # documentation captures; they carry the version in a header
    "notes",       # render the body from this build's numbers, verify it
    "commit",      # commit anything the stages above changed
    "push",        # push main
    "ci",          # wait for the CI run on this commit to pass
    "tag",         # annotated tag, pushed
    "package",     # asset name + SHA256SUMS.txt (signed first, if configured)
    "publish",     # gh release create
    "verify",      # download the published asset and run it
    "remote",      # check_github_sync.py - every surface on GitHub
    "done",
)

# A dry run rehearses every stage that is local and reversible: it builds,
# gates, captures and renders the notes. It stops at the first stage that would
# leave a mark. It used to stop only at `publish`, so a rehearsal committed the
# regenerated screenshots, pushed them, and waited 48 s for CI before dying on
# the tag - a dry run that wrote to main.
DRY_STAGES = frozenset(("preflight", "build", "sign", "facts", "gates",
                        "screenshots", "notes"))

STATE = os.path.join(ROOT, "dist", ".release-state.json")
LATEST_MARK = re.compile(r"(?m)^## (\d+\.\d+\.\d+) - ")


# --------------------------------------------------------------------------
# output


class Log(object):
    def __init__(self):
        self.lines = []
        self.path = None

    def say(self, text, prefix="   "):
        line = prefix + text
        print(line)
        self.lines.append(line)

    def head(self, text):
        print()
        self.say(text, "== ")
        self.lines.append("")

    def flush(self):
        if self.path:
            with open(self.path, "w", encoding="utf-8", newline="\n") as fh:
                fh.write("\n".join(self.lines) + "\n")


LOG = Log()


class Fail(Exception):
    """A stage could not complete. The message says what to do about it."""


def note(text):
    LOG.say(text)


# --------------------------------------------------------------------------
# process helpers


def run(cmd, cwd=ROOT, check=True, quiet=False, env=None, timeout=None):
    """Run a command, echo it, and keep its output in the log."""
    LOG.lines.append("$ " + " ".join(cmd))
    if not quiet:
        LOG.say("$ " + " ".join(cmd), "     ")
    proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", env=env,
                          timeout=timeout)
    for stream in (proc.stdout, proc.stderr):
        if stream and stream.strip():
            for line in stream.rstrip().splitlines():
                LOG.lines.append("    | " + line)
                if not quiet:
                    print("     | " + line)
    if check and proc.returncode != 0:
        raise Fail("command failed (%d): %s" % (proc.returncode, " ".join(cmd)))
    return proc


def git(*args, **kw):
    out = run(["git"] + list(args), **kw)
    return out.stdout if kw.get("check", True) else out


def gh(*args, **kw):
    return run(["gh"] + list(args), **kw)


def git_out(*args):
    return run(["git"] + list(args), quiet=True).stdout.strip()


def sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as fh:
        return fh.read()


def write(rel, text):
    path = os.path.join(ROOT, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def rel(*parts):
    return "/".join(parts)


# --------------------------------------------------------------------------
# context


class Ctx(object):
    def __init__(self, version, dry_run, skip_screenshots=False):
        self.version = version
        self.tag = "v" + version
        self.dry_run = dry_run
        self.skip_screenshots = skip_screenshots
        self.sha256 = None
        self.size = None
        self.signed = False
        self.asset = F.ASSET
        self.notes_src = rel("docs", "release-notes", version + ".md")
        self.notes_out = os.path.join(ROOT, "dist",
                                      "release-notes-%s.md" % version)
        self.pkg_dir = os.path.join(ROOT, "dist", "release")
        self.remote_ok = None

    # persisted between runs so --from works after a crash
    def save(self):
        os.makedirs(os.path.dirname(STATE), exist_ok=True)
        data = {k: getattr(self, k) for k in
                ("version", "sha256", "size", "signed", "remote_ok")}
        with open(STATE, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(data, fh, indent=1)

    def load(self):
        if not os.path.exists(STATE):
            return False
        try:
            data = json.load(open(STATE, encoding="utf-8"))
        except (ValueError, OSError):
            return False
        if data.get("version") != self.version:
            return False
        for k, v in data.items():
            if hasattr(self, k):
                setattr(self, k, v)
        return True


# --------------------------------------------------------------------------
# stages


def stage_preflight(cfg):
    """Refuse to start on a checkout that is not ready to be released."""
    for tool in ("git", "gh", "make", "python"):
        if shutil.which(tool) is None:
            raise Fail("%s is not on PATH" % tool)

    branch = git_out("rev-parse", "--abbrev-ref", "HEAD")
    if branch != "main":
        raise Fail("on branch %r, releases come from main" % branch)

    dirty = git_out("status", "--porcelain")
    if dirty:
        raise Fail("working tree is not clean; commit or stash first:\n" + dirty)

    # Three read-only round trips that do not depend on each other: fetching the
    # refs (1.2 s), listing the remote's tags (1.0 s) and asking gh who we are
    # (0.9 s). Serially they were 3.1 s of the 12.6 s rehearsal; overlapped, the
    # cost is the slowest one. `git fetch` also writes refs, so its result is
    # awaited before anything reads HEAD or a local tag.
    with ThreadPoolExecutor(max_workers=3) as pool:
        fetched = pool.submit(run, ["git", "fetch", "origin", "--tags", "--prune"],
                              quiet=True)
        remote = pool.submit(run, ["git", "ls-remote", "--tags", "origin"],
                             quiet=True)
        auth = pool.submit(run, ["gh", "auth", "status"], check=False, quiet=True)
        fetched.result()
        remote_listing = remote.result().stdout if remote.result().returncode == 0 else None
        if auth.result().returncode != 0:
            raise Fail("gh is not authenticated; `gh auth login` first")

    head = git_out("rev-parse", "HEAD")
    upstream = git_out("rev-parse", "origin/main")
    if head != upstream:
        raise Fail("HEAD %s is not origin/main %s; push and let CI pass first"
                   % (head[:7], upstream[:7]))
    note("HEAD = origin/main = " + head[:7])

    # version: src/app.h is the authority, release_facts.py is derived
    app_h = read("src/app.h")
    m = re.search(r'#define\s+EF11_VERSION\s+L"([^"]+)"', app_h)
    if not m:
        raise Fail("no EF11_VERSION in src/app.h")
    if m.group(1) != cfg.version:
        raise Fail("src/app.h says %s but release_facts.py says %s; run "
                   "`make refresh-facts` and commit" % (m.group(1), cfg.version))

    if not re.search(r"(?m)^## %s - \d{4}-\d{2}-\d{2}$" % re.escape(cfg.version),
                     read("CHANGELOG.md")):
        raise Fail("CHANGELOG.md has no `## %s - YYYY-MM-DD` heading"
                   % cfg.version)
    released = re.search(r"(?m)^## %s - (\d{4}-\d{2}-\d{2})$"
                         % re.escape(cfg.version), read("CHANGELOG.md")).group(1)
    today = datetime.date.today().isoformat()
    if released != today:
        note("WARNING: the CHANGELOG dates this release %s; today is %s. "
             "Correct if it shipped later than planned." % (released, today))

    if not os.path.exists(os.path.join(ROOT, cfg.notes_src)):
        raise Fail("no release notes at %s\n"
                   "       create it with: python tools/release.py --init-notes"
                   % cfg.notes_src)

    # the version must move forward; the tag must not exist yet. A dry run is
    # allowed to reuse an already-tagged version, because that is the only way to
    # rehearse the pipeline against a real release.
    tags = [t for t in git_out("tag", "--list", "v*").split() if t]
    if tags:
        newest = max(tags, key=lambda t: semver(t[1:]))
        order, newest_v = semver(cfg.version), semver(newest[1:])
        if order < newest_v:
            raise Fail("version %s is older than the newest tag %s"
                       % (cfg.version, newest))
        if order == newest_v and not cfg.dry_run:
            raise Fail("version %s is already tagged as %s; a version is used "
                       "once. (A --dry-run may reuse it to rehearse.)"
                       % (cfg.version, newest))
    for where, exists in (("local", _tag_exists_local(cfg.tag)),
                          ("remote", _tag_exists_remote(cfg.tag, remote_listing))):
        if exists:
            if cfg.dry_run:
                note("WARNING: tag %s already exists %s; dry run continues"
                     % (cfg.tag, where))
            else:
                raise Fail("tag %s already exists %s; a version is used once"
                           % (cfg.tag, where))

    note("version %s, notes source %s" % (cfg.version, cfg.notes_src))


def stage_build(cfg):
    """Rebuild from scratch, never from a stale dist/."""
    exe = os.path.join(ROOT, "dist", "ExplorerF11.exe")
    if os.path.exists(exe):
        # A running instance holds the image and the linker cannot replace it.
        running = run(["tasklist", "/FI", "IMAGENAME eq ExplorerF11.exe"],
                      check=False, quiet=True).stdout
        if "ExplorerF11.exe" in running:
            raise Fail("a running ExplorerF11.exe holds dist\\ExplorerF11.exe; "
                       "quit it from the tray and run again")
    run(["make", "-B"], timeout=900)
    if not os.path.exists(exe):
        raise Fail("make -B produced no dist/ExplorerF11.exe")
    cfg.size = os.path.getsize(exe)
    cfg.sha256 = sha256_of(exe)
    note("built %s bytes (%d KiB), sha256 %s"
         % (cfg.size, round(cfg.size / 1024), cfg.sha256))


def stage_sign(cfg):
    """Sign before anything is measured, so the facts describe the asset.

    A signature is the last thing that changes the file, which is why it sits
    between the build and every measurement. If it ran later, the byte count,
    the KiB figure and the SHA-256 in the notes would all describe a file that
    was never uploaded.
    """
    exe = os.path.join(ROOT, "dist", "ExplorerF11.exe")
    if not os.path.exists(exe):
        raise Fail("no dist/ExplorerF11.exe; resume from --from build")
    signed = _pe_has_signature(exe)
    cmd = os.environ.get("EF11_SIGN_CMD", "").strip()

    if not cmd:
        if signed:
            raise Fail("dist/ExplorerF11.exe carries a signature but "
                       "EF11_SIGN_CMD is not set; set it so the release is "
                       "reproducible, or rebuild with --from build")
        cfg.signed = False
        note("no EF11_SIGN_CMD: this build ships unsigned")
        return

    env = dict(os.environ, EF11_FILE=exe)
    run([cmd], env=env, timeout=900)
    if not _pe_has_signature(exe):
        raise Fail("EF11_SIGN_CMD ran but the image still has an empty security "
                   "directory; check its output above")
    cfg.signed = True
    cfg.size = os.path.getsize(exe)
    cfg.sha256 = sha256_of(exe)
    note("signed: %d bytes, sha256 %s" % (cfg.size, cfg.sha256))


def stage_facts(cfg):
    """Re-derive every published number from this build, then reload them."""
    manifest = os.path.join(ROOT, "tools", "measurement.json")
    if not os.path.exists(os.path.join(ROOT, "dist", "ExplorerF11.exe")):
        raise Fail("no dist/ExplorerF11.exe; resume from --from build")
    before = read("tools/release_facts.py")
    run(["make", "refresh-facts"], timeout=1800)
    importlib.reload(F)
    after = read("tools/release_facts.py")
    if F.VERSION != cfg.version:
        raise Fail("refresh-facts changed the version to %s" % F.VERSION)
    if round(cfg.size / 1024) != F.SIZE_KIB:
        raise Fail("binary is %d KiB but the facts say %d KiB; refresh-facts "
                   "did not settle" % (round(cfg.size / 1024), F.SIZE_KIB))
    if not os.path.exists(manifest):
        raise Fail("refresh-facts wrote no measurement.json")

    changed = before != after
    note("facts: %d KiB, %d handles, %d assertions%s"
         % (F.SIZE_KIB, F.HANDLES, F.ASSERTIONS,
            " (rewritten)" if changed else " (unchanged)"))
    if changed:
        note("release_facts.py changed; the consistency gate in the same run "
             "compared the prose against the new numbers")


def stage_gates(cfg):
    """The full suite, on the tree that will be tagged.

    `facts` has already run every one of these commands - it has to, because it
    derives the assertion count from them - and it recorded the fingerprint of
    the tree it ran against. If that fingerprint still describes this tree, the
    answer cannot change: same bytes, same questions, same result. Re-running
    cost 62 s and proved nothing new.

    Anything that moves a byte invalidates the record, including the four
    documentation screenshots, so this is a strict reuse and not a shortcut.
    """
    record = read_gate_record()
    here = treefp.fingerprint()
    if record and record.get("fingerprint") == here:
        note("gates: %d commands, %d assertions, all green on this exact tree "
             "(recorded by `facts` in %.1fs)"
             % (len(record.get("gates", [])), record.get("assertions_total", 0),
                record.get("seconds", 0.0)))
        return
    why = ("no gate record in dist/" if not record else
           "the tree changed since `facts` ran")
    note("re-running the suite: " + why)
    started = time.time()
    run(["make", "test"], timeout=1800)
    note("thirteen gates passed on this tree in %.1fs" % (time.time() - started))


def stage_screenshots(cfg):
    """Regenerate the documentation captures.

    They are photographs of the running binary and their headers carry the
    version number, so a release that skips this ships documentation showing the
    previous version. The step was a sentence in RELEASING.md until now, which
    is exactly the kind of instruction that gets skipped at 1 a.m.
    """
    if cfg.skip_screenshots:
        note("--skip-screenshots: docs/images left unchanged")
        return
    script = os.path.join(ROOT, "tools", "capture-screenshots.py")
    if not os.path.exists(script):
        note("no capture-screenshots.py; nothing to regenerate")
        return
    for lang in ("zh", "en"):
        run(["python", "tools/capture-screenshots.py", lang], timeout=600)
    changed = git_out("status", "--porcelain", "--", "docs/images")
    if changed:
        note("regenerated: " + ", ".join(l.split()[-1] for l in
                                         changed.splitlines()))
    else:
        note("captures came out byte-identical")


def stage_notes(cfg):
    """Render the body from measurements, or verify an already-rendered one."""
    values = placeholder_values(cfg)
    path = os.path.join(ROOT, cfg.notes_src)
    text = read(cfg.notes_src)
    placeholders = re.findall(r"\{\{[a-z_]+\}\}", text)

    if placeholders:
        unknown = sorted(set(placeholders) - set(values))
        if unknown:
            raise Fail("unknown placeholder(s) in %s: %s"
                       % (cfg.notes_src, ", ".join(unknown)))
        for key, value in values.items():
            text = text.replace(key, value)
        if "{{" in text:
            raise Fail("placeholder left unsubstituted in " + cfg.notes_src)
        write(cfg.notes_src, text)
        note("rendered %s from this build's measurements" % cfg.notes_src)
    else:
        note("%s is already rendered; verifying it against this build"
             % cfg.notes_src)

    problems = validate_notes(text, cfg)
    if problems:
        raise Fail("%s does not describe this build:\n  - %s"
                   % (cfg.notes_src, "\n  - ".join(problems)))

    if cfg.dry_run:
        # The rendered body is an input to `publish`, which a rehearsal never
        # reaches. Writing it anyway left a stale copy in dist/ that the next
        # rehearsal could pick up as if it were this build's text.
        note("dry run: body rendered and verified, not written to dist/")
        return

    os.makedirs(os.path.dirname(cfg.notes_out), exist_ok=True)
    with open(cfg.notes_out, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    note("body: %d bytes, %d lines" % (len(text.encode("utf-8")),
                                       text.count("\n") + 1))


def stage_commit(cfg):
    """Commit whatever the stages above changed, if anything."""
    if cfg.dry_run:
        note("dry run: not committing")
        return
    run(["git", "add", "-A"])
    staged = git_out("diff", "--cached", "--name-only")
    if not staged:
        note("nothing to commit")
        return
    for name in staged.splitlines():
        note("  " + name)
    body = changelog_body(cfg.version)
    run(["git", "commit", "-m", "release: %s" % cfg.version, "-m", body])
    note("committed " + git_out("rev-parse", "--short", "HEAD"))


def stage_push(cfg):
    head = git_out("rev-parse", "HEAD")
    if cfg.dry_run:
        note("dry run: would push " + head[:7])
        return
    upstream = git_out("rev-parse", "origin/main")
    if head == upstream:
        note("already pushed")
        return
    run(["git", "push", "origin", "main"], timeout=300)
    note("pushed " + head[:7])


def stage_ci(cfg):
    """Wait for the run on this exact commit; a tag on red CI ships an untested build."""
    head = git_out("rev-parse", "HEAD")
    if cfg.dry_run:
        note("dry run: would wait for CI on " + head[:7])
        return
    deadline = time.time() + 45 * 60
    warned = False
    while time.time() < deadline:
        raw = run(["gh", "run", "list", "--limit", "20", "--json",
                   "databaseId,headSha,status,conclusion,url"],
                  quiet=True).stdout
        runs = json.loads(raw or "[]")
        mine = [r for r in runs if r.get("headSha") == head]
        if not mine:
            if not warned:
                note("no run for %s yet; waiting for it to appear" % head[:7])
                warned = True
            time.sleep(10)
            continue
        r = mine[0]
        state, conclusion = r.get("status"), r.get("conclusion")
        if state == "completed":
            if conclusion != "success":
                raise Fail("CI on %s finished %s: %s"
                           % (head[:7], conclusion, r.get("url")))
            note("CI green on %s" % head[:7])
            return
        note("CI %s (%s), waiting" % (state, head[:7]))
        time.sleep(15)
    raise Fail("CI did not finish within 45 minutes; check `gh run list`")


def stage_tag(cfg):
    head = git_out("rev-parse", "HEAD")
    if cfg.dry_run:
        note("dry run: would tag " + head[:7] + " as " + cfg.tag)
        return
    if _tag_exists_local(cfg.tag):
        target = git_out("rev-parse", cfg.tag + "^{commit}")
        if target != head:
            # The rule check_github_sync.py enforces, in one place: a tag may
            # sit behind HEAD while release plumbing, screenshots and prose
            # follow it. Only src/ moving invalidates the tagged tree.
            moved = git_out("diff", "--name-only", cfg.tag + "..HEAD", "--", "src")
            if moved.strip():
                raise Fail("tag %s is behind HEAD and src/ changed since (%s); a "
                           "published tag is not moved for build changes - cut the "
                           "next version instead"
                           % (cfg.tag, ", ".join(moved.split())))
            note("tag %s stays at %s; src/ is unchanged since"
                 % (cfg.tag, target[:7]))
        else:
            note("tag %s already points at HEAD" % cfg.tag)
    else:
        run(["git", "tag", "-a", cfg.tag, "-m", "ExplorerF11 " + cfg.version])
        note("created " + cfg.tag)
    if _tag_exists_remote(cfg.tag):
        note("remote tag already present")
    else:
        run(["git", "push", "origin", cfg.tag], timeout=300)
        note("pushed " + cfg.tag)


def stage_package(cfg):
    """Give the artefact its published name and the checksum that pins it."""
    src = os.path.join(ROOT, "dist", "ExplorerF11.exe")
    if not os.path.exists(src):
        raise Fail("no dist/ExplorerF11.exe; resume from --from build")
    os.makedirs(cfg.pkg_dir, exist_ok=True)
    asset = os.path.join(cfg.pkg_dir, cfg.asset)
    shutil.copyfile(src, asset)

    cfg.signed = _pe_has_signature(asset)
    size = os.path.getsize(asset)
    digest = sha256_of(asset)
    if cfg.size is not None and size != cfg.size:
        raise Fail("packaged asset is %d bytes but the build was %d; something "
                   "rewrote the binary after it was measured"
                   % (size, cfg.size))
    cfg.size, cfg.sha256 = size, digest

    sums = os.path.join(cfg.pkg_dir, F.CHECKSUM)
    with open(sums, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("%s  %s\n" % (digest, cfg.asset))
    note("%s  %s" % (digest, cfg.asset))
    note("%d bytes, %d KiB, signature: %s"
         % (size, round(size / 1024), "yes" if cfg.signed else "none"))


def stage_publish(cfg):
    existing = run(["gh", "release", "view", cfg.tag, "--json", "assets"],
                   check=False, quiet=True)
    if existing.returncode == 0:
        note("release %s already exists; not creating it again" % cfg.tag)
    else:
        if cfg.dry_run:
            raise Fail("dry run reached publish; rerun without --dry-run")
        run(["gh", "release", "create", cfg.tag,
             os.path.join(cfg.pkg_dir, cfg.asset),
             os.path.join(cfg.pkg_dir, F.CHECKSUM),
             "--title", "ExplorerF11 " + cfg.version,
             "--notes-file", cfg.notes_out], timeout=600)
        note("release created: https://github.com/QzCrane/ExplorerF11/"
             "releases/tag/" + cfg.tag)

    # the asset on GitHub must be the file that was just measured
    info = json.loads(run(["gh", "release", "view", cfg.tag, "--json",
                           "assets"], quiet=True).stdout or "{}")
    names = [a["name"] for a in info.get("assets", [])]
    for required in (cfg.asset, F.CHECKSUM):
        if required not in names:
            raise Fail("release has no asset named %s (found: %s)"
                       % (required, ", ".join(names) or "none"))
    note("assets present: " + ", ".join(sorted(names)))


def stage_verify(cfg):
    """Download what the world downloads, check it, and run it."""
    tmp = tempfile.mkdtemp(prefix="ef11-verify-")
    try:
        run(["gh", "release", "download", cfg.tag, "--dir", tmp,
             "--pattern", cfg.asset, "--pattern", F.CHECKSUM], timeout=600)
        asset = os.path.join(tmp, cfg.asset)
        sums = os.path.join(tmp, F.CHECKSUM)

        expected = open(sums, encoding="utf-8").read().split()[0]
        actual = sha256_of(asset)
        if actual != expected:
            raise Fail("downloaded asset hashes to %s, SHA256SUMS says %s"
                       % (actual, expected))
        if actual != cfg.sha256:
            raise Fail("downloaded asset hashes to %s, the build was %s"
                       % (actual, cfg.sha256))
        note("sha256 matches SHA256SUMS.txt and the build")

        size = os.path.getsize(asset)
        if size != cfg.size:
            raise Fail("downloaded asset is %d bytes, the build was %d"
                       % (size, cfg.size))

        ver = run([asset, "--version"], quiet=True).stdout.strip()
        if cfg.version not in ver:
            raise Fail("downloaded asset reports %r, expected %s"
                       % (ver, cfg.version))
        note(ver)

        status = run([asset, "--status", "--quiet"], check=False, timeout=120)
        if status.returncode != 0:
            raise Fail("downloaded asset exits %d on --status"
                       % status.returncode)
        note("--status exits 0")

        if cfg.signed:
            signtool = shutil.which("signtool")
            if signtool:
                run([signtool, "verify", "/pa", "/q", asset], timeout=120)
                note("signtool verify /pa passed")
            else:
                note("WARNING: signed asset but no signtool on PATH to verify it")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def stage_remote(cfg):
    run(["python", "tools/check_github_sync.py"], timeout=300)
    cfg.remote_ok = True
    note("every surface on GitHub describes this checkout")


def stage_done(cfg):
    LOG.head("released")
    note("version   %s" % cfg.version)
    note("asset     %s" % cfg.asset)
    note("bytes     %d (%d KiB)" % (cfg.size, round(cfg.size / 1024)))
    note("sha256    %s" % cfg.sha256)
    note("signed    %s" % ("yes" if cfg.signed else "no"))
    note("url       https://github.com/QzCrane/ExplorerF11/releases/tag/%s"
         % cfg.tag)
    note("")
    note("To re-prove any of it later: make check-remote")


HANDLERS = {
    "preflight": stage_preflight,
    "build": stage_build,
    "sign": stage_sign,
    "facts": stage_facts,
    "gates": stage_gates,
    "screenshots": stage_screenshots,
    "notes": stage_notes,
    "commit": stage_commit,
    "push": stage_push,
    "ci": stage_ci,
    "tag": stage_tag,
    "package": stage_package,
    "publish": stage_publish,
    "verify": stage_verify,
    "remote": stage_remote,
    "done": stage_done,
}


# --------------------------------------------------------------------------
# facts, notes and small helpers


def semver(text):
    return tuple(int(p) for p in text.split(".")[:3])


def _tag_exists_local(tag):
    return run(["git", "rev-parse", "-q", "--verify", "refs/tags/" + tag],
               check=False, quiet=True).returncode == 0


def _tag_exists_remote(tag, listing=None):
    """Is the tag on origin? `listing` is a prefetched `ls-remote --tags` output;
    pass it when the caller has already paid for the round trip."""
    if listing is not None:
        return re.search(r"(?m)^\S+\s+refs/tags/%s(\^\{\})?$" % re.escape(tag),
                         listing) is not None
    out = run(["git", "ls-remote", "--tags", "origin", "refs/tags/" + tag],
              check=False, quiet=True).stdout
    return bool(out.strip())


def _pe_has_signature(path):
    """A PE image carries an Authenticode signature iff its security data
    directory is non-empty. No parser needed beyond the headers."""
    import struct
    with open(path, "rb") as fh:
        data = fh.read(4096)
    if len(data) < 0x40 or data[:2] != b"MZ":
        return False
    e = struct.unpack_from("<I", data, 0x3C)[0]
    if data[e:e + 4] != b"PE\0\0":
        return False
    opt = e + 24
    magic = struct.unpack_from("<H", data, opt)[0]
    dd = opt + (96 if magic == 0x10B else 112)  # PE32 vs PE32+
    size = struct.unpack_from("<I", data, dd + 4 * 8 + 4)[0]
    return size > 0


def read_gate_record():
    """The gate run `refresh-facts` recorded, or None.

    Lives in dist/ because it describes one build of one tree; `make clean`
    removing it is correct, and the next facts stage writes a fresh one.
    """
    try:
        with open(os.path.join(ROOT, "dist", "gates.json"), encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    if isinstance(data, dict) and data.get("fingerprint"):
        return data
    return None


def placeholder_values(cfg):
    return {
        "{{version}}": cfg.version,
        "{{asset}}": cfg.asset,
        "{{sha256}}": cfg.sha256,
        "{{bytes}}": str(cfg.size),
        "{{bytes_grouped}}": format(cfg.size, ","),
        "{{kib}}": str(F.SIZE_KIB),
        "{{gates}}": str(F.GATES),
        "{{assertions}}": str(F.ASSERTIONS),
        "{{handles}}": str(F.HANDLES),
        "{{private_mb}}": str(_manifest_private_mb()),
    }


def _manifest_private_mb():
    path = os.path.join(ROOT, "tools", "measurement.json")
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return "?"
    return str(data.get("private_mb", "?"))


def validate_notes(text, cfg):
    """The body must describe this build, not a remembered one."""
    problems = []
    if cfg.asset not in text:
        problems.append("never names the asset " + cfg.asset)
    if cfg.sha256 and cfg.sha256 not in text:
        problems.append("never quotes this build's SHA-256")
    if str(cfg.size) not in text and format(cfg.size, ",") not in text:
        problems.append("never quotes this build's byte count (%d)" % cfg.size)
    if "%d KiB" % F.SIZE_KIB not in text:
        problems.append("never quotes this build's size (%d KiB)" % F.SIZE_KIB)
    if str(F.ASSERTIONS) not in text:
        problems.append("never quotes the assertion count (%d)" % F.ASSERTIONS)

    for m in re.finditer(r"ExplorerF11 (\d+\.\d+\.\d+)", text):
        if m.group(1) != cfg.version:
            problems.append("mentions ExplorerF11 %s, this release is %s"
                            % (m.group(1), cfg.version))

    says_unsigned = re.search(r"\bunsigned\b|未做代码签名|未签名", text)
    claims_signed = re.search(r"(?<!un)\bsigned\b", text)
    if claims_signed and not says_unsigned:
        problems.append("claims the binary is signed but the build is not")
    if says_unsigned and cfg.signed:
        problems.append("says the binary is unsigned but it is signed")
    return problems


def changelog_body(version):
    """The CHANGELOG section, flattened into a commit message."""
    text = read("CHANGELOG.md")
    m = re.search(r"(?ms)^## %s - [^\n]*\n(.*?)(?=^## |\Z)" % re.escape(version),
                  text)
    if not m:
        return "See CHANGELOG.md."
    body = m.group(1)
    body = re.sub(r"(?m)^### .*$", "", body)
    body = re.sub(r"\*\*(.+?)\*\*", r"\1", body)
    body = re.sub(r"`([^`]+)`", r"\1", body)
    body = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", body)
    lines = [l.rstrip() for l in body.splitlines()]
    lines = [l for l in lines if l.strip()]
    return "\n".join(lines).strip() or "See CHANGELOG.md."


NOTES_SKELETON = """\
ExplorerF11 {{version}} is a single-file Windows 11 utility that sends F11 to
Explorer windows so they go full screen. No installer, no runtime, no polling.

## What changed

<!-- Two or three paragraphs in user-facing language. See CHANGELOG.md for the
     complete list; do not copy the previous release's text. -->

## The build

| | |
|---|---|
| Version | {{version}} |
| Asset | {{asset}} |
| Bytes | {{bytes}} ({{bytes_grouped}}) |
| Size | {{kib}} KiB |
| SHA-256 | `{{sha256}}` |
| Gates | {{gates}} gates, {{assertions}} assertions |
| Signing | unsigned - SmartScreen warns on first run |

Verify what you downloaded before running it:

```
sha256sum ExplorerF11-{{version}}-win64.exe
```

The binary is unsigned, so SmartScreen will warn on first run. Compare the hash
above with the published `SHA256SUMS.txt`, or build from source.

## Residue

`--clean` removes only this program's own records. Anything Explorer left behind
on its own is reported, not touched. See `docs/RESIDUE.md`.

## Documentation

- [Usage, English](https://github.com/QzCrane/ExplorerF11/blob/main/docs/USAGE.en.md)
- [使用说明, 中文](https://github.com/QzCrane/ExplorerF11/blob/main/docs/USAGE.zh-CN.md)
- [Changelog](https://github.com/QzCrane/ExplorerF11/blob/main/CHANGELOG.md)

Previous releases stay available; GitHub marks the newest as Latest.
"""


# --------------------------------------------------------------------------
# main


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Build, gate, tag, publish and verify a release.")
    parser.add_argument("--version", help="version to release (default: facts)")
    parser.add_argument("--dry-run", action="store_true",
                        help="stop before the first public mutation")
    parser.add_argument("--from", dest="start", choices=STAGES,
                        help="resume at this stage")
    parser.add_argument("--to", dest="stop", choices=STAGES,
                        help="stop after this stage")
    parser.add_argument("--init-notes", action="store_true",
                        help="write the release-notes skeleton and stop")
    parser.add_argument("--skip-screenshots", action="store_true",
                        help="leave docs/images alone (they carry the version)")
    args = parser.parse_args(argv)

    cfg = Ctx(args.version or F.VERSION, args.dry_run, args.skip_screenshots)

    if args.init_notes:
        path = os.path.join(ROOT, cfg.notes_src)
        if os.path.exists(path):
            print("already exists: " + cfg.notes_src)
            return 2
        write(cfg.notes_src, NOTES_SKELETON)
        print("wrote " + cfg.notes_src)
        print("Fill in '## What changed'. Leave every {{placeholder}} in place;")
        print("`make release` substitutes them from this build's measurements.")
        return 0

    os.makedirs(os.path.join(ROOT, "dist"), exist_ok=True)
    LOG.path = os.path.join(ROOT, "dist", "release-%s.log" % cfg.version)
    if args.start and args.start != "preflight":
        cfg.load()

    LOG.head("ExplorerF11 %s%s" % (cfg.version,
                                   " (dry run)" if cfg.dry_run else ""))

    started = time.time()
    timings = []
    for name in STAGES:
        if args.start and STAGES.index(name) < STAGES.index(args.start):
            continue
        if args.dry_run and name not in DRY_STAGES:
            LOG.head("dry run stopped before " + name)
            note("build, facts, gates, screenshots and notes all passed.")
            note("Nothing was committed, pushed, tagged, uploaded or published.")
            # The rehearsal is not free of writes: `facts` rewrites the measured
            # numbers and the captures embed the build's own timestamp in the
            # report header, so the PNGs differ every run. preflight proved the
            # tree was clean, so everything dirty now was written by this run and
            # can go back. Without this, the next rehearsal fails at preflight on
            # its predecessor's output.
            stray = git_out("status", "--porcelain")
            if stray.strip():
                run(["git", "checkout", "--", "."], quiet=True)
                note("reverted %d file(s) this run rewrote; the tree is where the "
                     "dry run found it" % len(stray.splitlines()))
            report_timings(timings)
            LOG.flush()
            return 0
        LOG.head("%s" % name)
        t0 = time.time()
        try:
            HANDLERS[name](cfg)
        except Fail as exc:
            timings.append((name, time.time() - t0))
            LOG.head("FAILED at " + name)
            note(str(exc))
            note("")
            note("Nothing after this stage ran. Fix the cause, then resume with:")
            note("    python tools/release.py --from %s" % name)
            report_timings(timings)
            cfg.save()
            LOG.flush()
            return 1
        except subprocess.TimeoutExpired as exc:
            timings.append((name, time.time() - t0))
            LOG.head("FAILED at " + name)
            note("timed out: %s" % exc)
            report_timings(timings)
            cfg.save()
            LOG.flush()
            return 1
        timings.append((name, time.time() - t0))
        cfg.save()
        LOG.flush()
        if args.stop == name:
            note("stopped after %s as requested" % name)
            report_timings(timings)
            return 0

    note("elapsed %.1fs" % (time.time() - started))
    report_timings(timings)
    note("log " + os.path.relpath(LOG.path, ROOT))
    LOG.flush()
    return 0


def report_timings(timings):
    """Print where the wall clock went.

    A pipeline that only reports its total cannot be argued with: "the release
    takes four minutes" was true for a year because nothing measured the parts.
    Printing every stage means the next person can see which one got slower
    instead of guessing, and `elapsed` is the sum of things that were actually
    timed rather than a number in a document.
    """
    if not timings:
        return
    total = sum(seconds for _, seconds in timings)
    note("stage times, %.1fs in %d stages:" % (total, len(timings)))
    width = max(len(name) for name, _ in timings)
    for name, seconds in sorted(timings, key=lambda t: -t[1]):
        note("    %-*s %6.2fs  %4.1f%%"
             % (width, name, seconds, 100.0 * seconds / total if total else 0.0))


if __name__ == "__main__":
    sys.exit(main())
