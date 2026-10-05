#!/usr/bin/env python3
"""Fetch ue-claude-kit from GitHub into a temp folder and install it into a project.

    python bootstrap.py <project_dir> [install.py options...]
    python bootstrap.py . --new TP_FirstPersonBP --name MyGame
    python bootstrap.py . --ref v1.0.0

Options of its own: --repo URL (default below), --ref BRANCH_OR_TAG (default main).
Everything else is passed to install.py. Uses `git clone` when git is available
(works for private repos with your git credentials), otherwise downloads the
GitHub zip (public repos only). The fetched copy is deleted afterwards: once
installed, the kit is part of the project and maintained there.
"""
import io
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile

DEFAULT_REPO = "https://github.com/matijagaspar/ue-claude-kit.git"


def take(argv, flag, default):
    if flag in argv:
        i = argv.index(flag)
        value = argv[i + 1]
        del argv[i:i + 2]
        return value
    return default


def fetch_git(repo, ref, dest):
    subprocess.run(["git", "clone", "--quiet", "--depth", "1", "--branch", ref, repo, dest], check=True)
    commit = subprocess.run(["git", "-C", dest, "rev-parse", "--short", "HEAD"],
                            capture_output=True, text=True).stdout.strip()
    return commit


def fetch_zip(repo, ref, dest):
    m = re.match(r"https://(?:[^@/]+@)?github\.com/([^/]+)/([^/.]+)", repo)
    if not m:
        raise SystemExit("bootstrap: git not found and %s is not a github.com URL to download." % repo)
    url = "https://codeload.github.com/%s/%s/zip/%s" % (m.group(1), m.group(2), ref)
    with urllib.request.urlopen(url, timeout=60) as r:
        zipfile.ZipFile(io.BytesIO(r.read())).extractall(dest)
    inner = os.path.join(dest, os.listdir(dest)[0])
    return inner, None


def main():
    argv = sys.argv[1:]
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return
    repo = take(argv, "--repo", DEFAULT_REPO)
    ref = take(argv, "--ref", "main")
    tmp = tempfile.mkdtemp(prefix="ue-claude-kit-")
    try:
        if shutil.which("git"):
            src = os.path.join(tmp, "kit")
            commit = fetch_git(repo, ref, src)
        else:
            src, commit = fetch_zip(repo, ref, tmp)
        source = "%s@%s%s" % (re.sub(r"https://[^@/]+@", "https://", repo), ref, (" (" + commit + ")") if commit else "")
        print("Fetched ue-claude-kit %s" % source, flush=True)
        rc = subprocess.run([sys.executable, os.path.join(src, "install.py")] + argv + ["--source", source]).returncode
        sys.exit(rc)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
