#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Gate: the published GitHub surfaces agree with this checkout.

``check_release_facts.py`` guarantees the repository's prose matches
``tools/release_facts.py``. It cannot see the surfaces that exist only on
GitHub:

  * the repository description ("About", right-hand column),
  * the release body and title,
  * the tag's tree, which is what "Browse files" and the source archive show,
  * the uploaded assets and their checksums.

Those are exactly where drift has happened twice: the v1.0.1 release body
shipped as a copy of 1.0.0's, and v1.0.4's tag was left one documentation
commit behind, so the source archive still quoted 1808 KB while the release
notes quoted 1812 KB. Both were found by a person reading the page, not by the
build. This script closes that gap.

  python tools/check_github_sync.py            # verify
  python tools/check_github_sync.py --verbose  # also print every value read

Exit code 0 means the checkout, the tag, the release and the description all
describe the same build. Run it before announcing a release and after any
commit that lands once one is published. A failure is meant to be read, not
skipped: it names the surface and both values.
"""

import json
import os
import re
import subprocess
import sys
import tempfile

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import release_facts as F

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO = "QzCrane/ExplorerF11"
TAG = "v" + F.VERSION
VERBOSE = "--verbose" in sys.argv

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    suffix = ("  [" + str(detail) + "]") if detail else ""
    print(("PASS  " if ok else "FAIL  ") + name + suffix)


def note(text):
    if VERBOSE:
        print("      " + text)


def run(*args, cwd=ROOT, text=True):
    try:
        p = subprocess.run(args, cwd=cwd, capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return 127, "", args[0] + ": not found"
    return p.returncode, (p.stdout or "").strip(), (p.stderr or "").strip()


def git(*args):
    return run("git", *args)


def gh(*args):
    return run("gh", *args)


def gh_json(*args):
    code, out, err = gh(*args)
    if code != 0:
        return None, err or out
    try:
        return json.loads(out), ""
    except json.JSONDecodeError as exc:
        return None, "invalid JSON: %s" % exc


def read_local(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as fh:
        return fh.read()


def local_size_bytes():
    path = os.path.join(ROOT, "dist", F.ASSET if os.path.exists(
        os.path.join(ROOT, "dist", F.ASSET)) else "ExplorerF11.exe")
    return os.path.getsize(path) if os.path.exists(path) else None


def local_sha256():
    import hashlib
    for name in (F.ASSET, "ExplorerF11.exe"):
        path = os.path.join(ROOT, "dist", name)
        if os.path.exists(path):
            with open(path, "rb") as fh:
                return hashlib.sha256(fh.read()).hexdigest()
    return None


# ---- prefetch -------------------------------------------------------------
# Seven independent read-only queries, each a network round trip of about 0.8 s.
# None of them depends on another, so running them at once changes nothing but
# the wall clock: 8.0 s -> 2.4 s for the whole gate. The checks below still
# consume them in order and print in order.
import concurrent.futures
import fnmatch


def _fetch_release():
    return gh_json("release", "view", TAG, "--json",
                   "tagName,name,isDraft,isPrerelease,body,assets")


def _fetch_latest():
    return gh_json("api", "repos/%s/releases/latest" % REPO)


def _fetch_repo():
    return gh_json("api", "repos/" + REPO)


def _fetch_topics():
    return gh_json("api", "repos/%s/topics" % REPO)


def _fetch_sums():
    """Download the checksum file and return its text, not its path.

    The temporary directory is gone once this returns, so the read happens
    inside the worker.
    """
    with tempfile.TemporaryDirectory() as tmp:
        code, out, err = gh("release", "download", TAG, "--repo", REPO,
                            "--pattern", F.CHECKSUM, "--dir", tmp, "--clobber")
        path = os.path.join(tmp, F.CHECKSUM)
        if code == 0 and os.path.exists(path):
            with open(path, encoding="utf-8") as fh:
                return fh.read(), ""
        return None, err or out


def _fetch_rulesets():
    """The repository's rulesets, with their rules expanded.

    The list endpoint returns names and targets but not the rules, so each one
    is fetched. Both calls happen inside this worker, which keeps them off the
    critical path: the six other queries are already in flight.
    """
    code, out, err = gh("api", "repos/%s/rulesets" % REPO)
    if code != 0:
        return None, err or out
    details = []
    for summary in json.loads(out or "[]"):
        code, out, err = gh("api", "repos/%s/rulesets/%s" % (REPO, summary["id"]))
        if code != 0:
            return None, err or out
        details.append(json.loads(out))
    return details, ""


_pool = concurrent.futures.ThreadPoolExecutor(max_workers=7)
FETCH = {
    "auth": _pool.submit(gh, "auth", "status"),
    "release": _pool.submit(_fetch_release),
    "latest": _pool.submit(_fetch_latest),
    "repo": _pool.submit(_fetch_repo),
    "topics": _pool.submit(_fetch_topics),
    "rulesets": _pool.submit(_fetch_rulesets),
    "sums": _pool.submit(_fetch_sums),
}


print("==== 0. 前置条件 ====")
code, _, err = FETCH["auth"].result()
check("gh 已登录", code == 0, "" if code == 0 else err.splitlines()[:1])

code, head, err = git("rev-parse", "HEAD")
check("能解析 HEAD", code == 0, head[:7] if code == 0 else err)
_, dirty, _ = git("status", "--porcelain")
check("工作区干净（否则检查的不是将要发布的内容）", dirty == "",
      "" if dirty == "" else dirty.splitlines()[0])
print("==== 1. 标签指向的源码 ====")
# Two things matter here, and "the tag is HEAD" is not one of them. Requiring
# equality forced every post-release commit — a typo, a screenshot, a build
# tweak — to rewrite a public tag; v1.0.4 needed that five times. What the tag
# actually has to guarantee is narrower:
#
#   * it is an ancestor of HEAD, so it names this line of history and not some
#     other branch's commit;
#   * `src/` has not moved since, so the tagged tree still holds the code the
#     release notes describe. Prose, screenshots and build plumbing may follow
#     the tag: if any of them changed the output, the digest check below goes
#     red on its own.
code, tag_commit, err = git("rev-parse", TAG + "^{commit}")
check("本地存在标签 " + TAG, code == 0, tag_commit[:7] if code == 0 else err)
code, _, _ = git("merge-base", "--is-ancestor", TAG, "HEAD")
check("标签是本分支的祖先（不是别的分支上的提交）", code == 0,
      "%s..%s" % (tag_commit[:7], head[:7]))

code, moved, _ = git("diff", "--name-only", TAG + "..HEAD", "--", "src")
moved = moved.strip() if code == 0 else ""
check("标签之后 src/ 未变动（源码一变就是下一个版本）", moved == "",
      "" if moved == "" else moved.replace("\n", ", "))

code, behind, _ = git("rev-list", "--count", TAG + "..HEAD")
print("INFO  标签之后有 %s 个提交；文档与截图允许跟进，源码不允许"
      % (behind.strip() or "?"))

code, remote_tags, err = git("ls-remote", "origin",
                             "refs/tags/" + TAG, "refs/tags/" + TAG + "^{}")
remote_commit = ""
for line in remote_tags.splitlines():
    parts = line.split()
    if len(parts) == 2 and parts[1].endswith("^{}"):
        remote_commit = parts[0]
if not remote_commit:
    for line in remote_tags.splitlines():
        parts = line.split()
        if len(parts) == 2:
            remote_commit = parts[0]
check("远端标签已推送且与本地同一提交", remote_commit == tag_commit,
      "%s vs %s" % (remote_commit[:7] or "-", tag_commit[:7]))

print("==== 2. 发行版 ====")
release, err = FETCH["release"].result()
check("发行版 " + TAG + " 存在", release is not None, "" if release else err)
release = release or {}
body = release.get("body") or ""
title = release.get("name") or ""
assets = release.get("assets") or []

check("标题含版本号", F.VERSION in title, title)
check("非草稿、非预发布", not release.get("isDraft") and not release.get("isPrerelease"),
      "draft=%s pre=%s" % (release.get("isDraft"), release.get("isPrerelease")))
latest, err = FETCH["latest"].result()
check("是仓库的 Latest release",
      (latest or {}).get("tag_name") == TAG, (latest or {}).get("tag_name", err))

# The body has a version-controlled copy, so "what the release page says" and
# "what the repository says" cannot drift. The release script renders this file
# from the build's measurements and commits it before tagging.
notes_path = os.path.join(ROOT, "docs", "release-notes", F.VERSION + ".md")
if os.path.exists(notes_path):
    with open(notes_path, encoding="utf-8") as fh:
        local_body = fh.read().replace("\r\n", "\n").strip()
    remote_body = body.replace("\r\n", "\n").strip()
    check("仓库 docs/release-notes/%s.md 等于线上正文" % F.VERSION,
          local_body == remote_body,
          "" if local_body == remote_body
          else "%d vs %d bytes" % (len(local_body), len(remote_body)))
    if local_body != remote_body:
        import difflib
        diff = list(difflib.unified_diff(local_body.splitlines(),
                                         remote_body.splitlines(),
                                         "repository", "github", n=0, lineterm=""))
        for line in diff[:12]:
            print("      " + line)
else:
    note("仓库无 docs/release-notes/%s.md，跳过正文比对" % F.VERSION)

print("==== 3. 资产 ====")
names = sorted(a.get("name", "") for a in assets)
check("资产恰好是 exe + 校验文件", names == sorted([F.ASSET, F.CHECKSUM]), ", ".join(names))

exe_asset = next((a for a in assets if a.get("name") == F.ASSET), None)
check("exe 资产存在", exe_asset is not None)
if exe_asset:
    size = exe_asset.get("size") or 0
    note("asset size = %s bytes" % size)
    check("资产大小 = %d KiB" % F.SIZE_KIB,
          round(size / 1024) == F.SIZE_KIB,
          "%.1f KiB" % (size / 1024))
    local = local_size_bytes()
    if local is not None:
        check("资产大小 = 本地构建", size == local, "%s vs %s" % (size, local))
    else:
        note("本地无 dist 构建，跳过大小比对")

downloaded, download_err = FETCH["sums"].result()
if downloaded is None:
    first = (download_err or "").splitlines()
    print("      (" + F.CHECKSUM + " 下载失败: " + (first[0] if first else "no output") + ")")

if downloaded is not None:
    lines = [ln for ln in downloaded.splitlines() if ln.strip()]
    check("校验文件只有一行", len(lines) == 1, "%d lines" % len(lines))
    m = re.match(r"^([0-9a-f]{64})\s+\*?(\S+)$", lines[0]) if lines else None
    check("校验文件格式为 <sha256>  <文件名>", m is not None, lines[0] if lines else "")
    if m:
        digest, name_in_sums = m.group(1), m.group(2)
        check("校验文件指向 " + F.ASSET, name_in_sums == F.ASSET, name_in_sums)
        check("正文引用的 SHA-256 与校验文件一致", digest in body, digest[:12] + "...")
        local_digest = local_sha256()
        if local_digest is None:
            note("本地无 dist 构建，跳过哈希比对")
        else:
            check("本地构建的 SHA-256 = 已发布资产", local_digest == digest,
                  local_digest[:12] + " vs " + digest[:12])
        if exe_asset:
            check("正文引用的字节数与资产一致",
                  "{:,}".format(exe_asset.get("size", 0)) in body
                  or str(exe_asset.get("size", 0)) in body,
                  str(exe_asset.get("size")))

print("==== 4. 正文事实 ====")
check("正文含版本号", F.VERSION in body, F.VERSION)
check("正文含资产名", F.ASSET in body, F.ASSET)
# The assertion and gate counts describe the released build, and they are the
# two numbers that legitimately move after a tag: adding a gate, or one more
# assertion to a suite, changes HEAD's facts while the published body still
# correctly describes the build it shipped. Comparing them against HEAD is what
# made this gate unusable between releases. The archived notes are the frozen
# copy of those numbers - section 2 already requires the archive to be
# byte-identical to the body - so they are only checked here when no archive
# exists and the facts file is the only remaining witness.
if not os.path.exists(notes_path):
    check("正文含断言数 %d" % F.ASSERTIONS, str(F.ASSERTIONS) in body)
    check("正文含闸门数 %d" % F.GATES, re.search(r"\b%d gates\b" % F.GATES, body) is not None)
for stale in ("1808", "10352", "366 KiB", "367 KiB", "410 KiB", "372 KiB",
              "135 handles", "1.76 MB"):
    check("正文无陈旧数字 " + stale, stale not in body,
          "found" if stale in body else "")

print("==== 5. 仓库描述 ====")
repo, err = FETCH["repo"].result()
check("能读取仓库元数据", repo is not None, "" if repo else err)
description = (repo or {}).get("description") or ""
note("description = " + description)
for m in re.finditer(r"(\d+)\s*KiB", description):
    check("描述中的 %s KiB 等于 %d" % (m.group(1), F.SIZE_KIB),
          int(m.group(1)) == F.SIZE_KIB, m.group(0))
for m in re.finditer(r"\b(\d+\.\d+\.\d+)\b", description):
    check("描述中的版本号 %s 等于 %s" % (m.group(1), F.VERSION),
          m.group(1) == F.VERSION, m.group(0))
if not re.search(r"\d+\s*KiB", description):
    note("描述未写体积，跳过体积比对")

print("==== 6. 构建文件版本断言 ====")
workflow = read_local(".github/workflows/build.yml")
check("CI 版本断言 = " + F.VERSION,
      ('"ExplorerF11 %s"' % F.VERSION) in workflow, F.VERSION)

print("==== 7. 仓库主题 ====")
# Topics live outside git too, and docs/RELEASING.md gives the command that sets
# them. Nothing checked that the command had ever been run, or that a later edit
# dropped one. The set below is the published one; additions are allowed,
# removals are not.
EXPECTED_TOPICS = {"cpp", "cpp23", "file-explorer", "i18n", "mingw-w64",
                   "performance", "shell-hook", "tray-icon", "win32",
                   "windows-11"}
topics, err = FETCH["topics"].result()
names = set((topics or {}).get("names") or [])
missing = sorted(EXPECTED_TOPICS - names)
check("主题包含全部 %d 项" % len(EXPECTED_TOPICS), not missing,
      ("missing: " + ", ".join(missing)) if missing else
      ("%d topics" % len(names)))

print("==== 8. 服务端规则 ====")
# "A published tag never moves" was a rule in docs/RELEASING.md and in this
# script, which is a convention: anyone with push access could still rewrite a
# tag and the rule would only notice afterwards. Two rulesets now enforce it
# where the push happens. A rule that nobody checks is a rule that gets deleted
# by accident, so the enforcement itself is a published surface.
rulesets, err = FETCH["rulesets"].result()
check("能读取规则集", rulesets is not None, "" if rulesets is not None else (err or "")[:120])
rulesets = rulesets or []


def _rule_types(predicate):
    found = set()
    for rs in rulesets:
        if rs.get("enforcement") != "active" or not predicate(rs):
            continue
        found |= {r.get("type") for r in (rs.get("rules") or [])}
    return found


def _covers(rs, ref):
    include = ((rs.get("conditions") or {}).get("ref_name") or {}).get("include") or []
    return any(fnmatch.fnmatch(ref, pattern) for pattern in include)


tag_rules = _rule_types(lambda rs: rs.get("target") == "tag"
                        and _covers(rs, "refs/tags/%s" % TAG))
check("活动规则：标签禁止删除", "deletion" in tag_rules, ", ".join(sorted(tag_rules)))
check("活动规则：标签禁止改写", "non_fast_forward" in tag_rules, ", ".join(sorted(tag_rules)))

branch_rules = _rule_types(lambda rs: rs.get("target") == "branch"
                           and _covers(rs, "refs/heads/main"))
check("活动规则：main 禁止删除", "deletion" in branch_rules, ", ".join(sorted(branch_rules)))
check("活动规则：main 禁止非快进推送", "non_fast_forward" in branch_rules,
      ", ".join(sorted(branch_rules)))

_pool.shutdown()

passed = sum(1 for r in results if r)
total = len(results)
print()
print("%d/%d checks passed" % (passed, total))
if passed != total:
    print("FAILED: the published surfaces do not describe this checkout yet.")
    sys.exit(1)
print("ALL SYNCED: tag, release, assets and description describe this checkout.")
