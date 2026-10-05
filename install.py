#!/usr/bin/env python3
"""Install ue-claude-kit into a project directory (usually run via bootstrap.py).

    python install.py <project_dir>                               # existing UE project (or empty dir)
    python install.py <dir> --new TP_FirstPersonBP --name MyGame  # also create a project from a template

Copies the kit payload (skill + CLI + ue/ue.cmd launchers), then runs `ue discover`
and `ue setup`. Once installed the kit belongs to the project and is maintained
there; re-installing over an existing copy needs --force (it overwrites local changes
to the kit files; ue_local_config.local is kept).
"""
import argparse
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PAYLOAD = os.path.join(HERE, "payload")
SKILL_REL = os.path.join(".claude", "skills", "unreal-editor")


def _kit_version():
    ns = {}
    exec(open(os.path.join(PAYLOAD, SKILL_REL, "scripts", "uekit", "__init__.py")).read(), ns)
    return ns["KIT_VERSION"]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("project_dir")
    ap.add_argument("--new", metavar="TEMPLATE", help="create a project from this engine template (e.g. TP_FirstPersonBP)")
    ap.add_argument("--name", help="project name for --new")
    ap.add_argument("--variant", help="template variant for --new")
    ap.add_argument("--port", type=int, help="preferred MCP port (default 8000)")
    ap.add_argument("--no-setup", action="store_true", help="only copy files and discover")
    ap.add_argument("--force", action="store_true", help="overwrite an existing kit install (local changes are lost)")
    ap.add_argument("--source", help=argparse.SUPPRESS)  # provenance, set by bootstrap.py
    a = ap.parse_args()
    if a.new and not a.name:
        ap.error("--new needs --name")

    dest = os.path.abspath(a.project_dir)
    os.makedirs(dest, exist_ok=True)

    skill_dst = os.path.join(dest, SKILL_REL)
    if os.path.isdir(skill_dst):
        if not a.force:
            sys.exit("ue-claude-kit is already installed in %s; it is maintained in the project now. "
                     "Use --force to overwrite it (local changes to the kit files are lost)." % dest)
        shutil.rmtree(skill_dst)  # wholesale replace so removed files don't linger
    shutil.copytree(os.path.join(PAYLOAD, SKILL_REL), skill_dst,
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    for launcher in ("ue.cmd", "ue"):
        shutil.copy2(os.path.join(PAYLOAD, launcher), os.path.join(dest, launcher))
    try:
        os.chmod(os.path.join(dest, "ue"), 0o755)
    except OSError:
        pass
    # Keep launcher line endings intact in the project's own git (sh needs LF, cmd needs CRLF).
    ga = os.path.join(dest, ".gitattributes")
    have = open(ga, encoding="utf-8").read().splitlines() if os.path.exists(ga) else []
    want = ["/ue text eol=lf", "/ue.cmd text eol=crlf"]
    missing = [l for l in want if l not in have]
    if missing:
        with open(ga, "a", encoding="utf-8") as f:
            f.write(("\n" if have and have[-1].strip() else "") + "# ue-claude-kit launchers\n" + "\n".join(missing) + "\n")
    with open(os.path.join(skill_dst, "KIT_SOURCE"), "w", encoding="utf-8") as f:
        f.write("Installed from: %s\nKit version: %s\n" % (a.source or HERE, _kit_version()))
    print("Installed ue-claude-kit into %s" % dest, flush=True)

    ue = [sys.executable, os.path.join(skill_dst, "scripts", "ue.py")]
    run = lambda *args: subprocess.run(ue + list(args), cwd=dest).returncode  # noqa: E731

    rc = run("discover", *(["--port", str(a.port)] if a.port else []))
    if rc:
        sys.exit(rc)
    if a.new:
        rc = run("new", "--template", a.new, "--name", a.name, *(["--variant", a.variant] if a.variant else []))
    elif not a.no_setup:
        has_project = any(f.endswith(".uproject") for f in os.listdir(dest)) or \
            any(f.endswith(".uproject") for d in os.listdir(dest) if os.path.isdir(os.path.join(dest, d))
                for f in os.listdir(os.path.join(dest, d)))
        if has_project:
            rc = run("setup")
        else:
            print("No .uproject yet. Create one with:  ue new --template TP_FirstPersonBP --name MyGame")
    if rc:
        sys.exit(rc)
    print("\nNext: start Claude Code in %s and approve the 'unreal-mcp' server (or just ask Claude to use the ue CLI)." % dest)


if __name__ == "__main__":
    main()
