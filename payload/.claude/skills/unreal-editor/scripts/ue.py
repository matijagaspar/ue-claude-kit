#!/usr/bin/env python3
"""ue - drive the Unreal editor for Claude Code (ue-claude-kit).

Run `ue <command> -h` for details. First run discovers paths and writes
ue_local_config.local (gitignored YAML) in the project root.
"""
import argparse
import base64
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from uekit import KIT_VERSION, discover as disc, editor, gpu, project, rexec  # noqa: E402
from uekit.mcpclient import Client, McpError  # noqa: E402

EXIT_GPU_BUSY = 3
ROOT = disc.find_project_root(os.path.dirname(os.path.abspath(__file__)))


def log(msg):
    print(msg, flush=True)


def die(msg, code=1):
    print("ue: " + msg, file=sys.stderr, flush=True)
    sys.exit(code)


# ---------------------------------------------------------------- config

def get_cfg(rediscover=False):
    cfg = disc.load_config(ROOT)
    stale = (cfg is None or cfg.get("kit_version") != KIT_VERSION
             or not os.path.isdir((cfg.get("engine") or {}).get("root") or "")
             or (not (cfg.get("project") or {}).get("uproject") and disc.find_uprojects(ROOT))
             or ((cfg.get("project") or {}).get("uproject") and not os.path.exists(cfg["project"]["uproject"])))
    if rediscover or stale:
        if cfg is None:
            log("First run: discovering project and engine ...")
        cfg = disc.discover(ROOT, cfg)
        disc.write_config(ROOT, cfg)
        log("Wrote %s" % disc.config_path(ROOT))
    return cfg


def need_project(cfg):
    if not cfg["project"]["uproject"]:
        die("No .uproject found under %s. Create one with `ue new --template TP_FirstPersonBP --name MyGame`." % ROOT)


def running(cfg):
    return editor.list_editors(cfg["project"]["uproject"]) if cfg["project"]["uproject"] else []


def mcp(cfg):
    return Client(cfg["mcp"]["url"]).connect()


# ---------------------------------------------------------------- commands

def cmd_discover(a):
    cfg = disc.discover(ROOT, disc.load_config(ROOT), port=a.port)
    disc.write_config(ROOT, cfg)
    e, p = cfg["engine"], cfg["project"]
    log("Project : %s" % (p["uproject"] or "(none yet - use `ue new`)"))
    log("Engine  : %s at %s (%s)" % (e["version"], e["root"], e["source"]))
    log("MCP     : %s  plugin=%s" % (cfg["mcp"]["url"], "yes" if e["mcp_plugin"] else "MISSING"))
    log("RemoteEx: %s" % ("enabled" if cfg["remote_exec"]["enabled"] else "unavailable"))
    log("GPU     : %s" % (cfg["gpu"]["name"] or "unknown"))
    log("Config  : %s" % disc.config_path(ROOT))


def cmd_setup(a):
    cfg = get_cfg()
    need_project(cfg)
    added, skipped = project.enable_plugins(cfg["project"]["uproject"], cfg["setup"]["plugins"], set(cfg["setup"]["plugins_available"]))
    log("Plugins enabled: %s" % (", ".join(added) or "(already enabled)"))
    if skipped:
        log("Plugins not in this engine (skipped): %s" % ", ".join(skipped))
    if project.write_mcp_json(ROOT, cfg["mcp"]["server_name"], cfg["mcp"]["url"]):
        log(".mcp.json: %s -> %s (restart Claude Code to load it)" % (cfg["mcp"]["server_name"], cfg["mcp"]["url"]))
    gi = project.update_gitignore(ROOT)
    if gi:
        log(".gitignore: added %s" % ", ".join(gi))
    if not a.no_claude_md and project.update_claude_md(ROOT):
        log("CLAUDE.md: added/updated ue-claude-kit section")
    if running(cfg) and added:
        log("Note: the editor is running; restart it to load newly enabled plugins (`ue restart`).")


def cmd_templates(a):
    cfg = get_cfg()
    for t in project.list_templates(cfg["engine"]["templates"]):
        log("%-22s %-20s %s%s" % (t["id"], t["name"], "C++" if t["cpp"] else "Blueprint",
                                  ("  variants: " + ", ".join(t["variants"])) if t["variants"] else ""))


def cmd_new(a):
    cfg = get_cfg()
    if cfg["project"]["uproject"]:
        die("This kit install already has a project: %s" % cfg["project"]["uproject"])
    t0 = time.time()
    up = project.new_project(cfg["engine"]["templates"], a.template, a.name, ROOT, a.variant, cfg["engine"]["version"])
    log("Created %s from %s in %.1fs" % (up, a.template, time.time() - t0))
    cfg = get_cfg(rediscover=True)
    cmd_setup(argparse.Namespace(no_claude_md=False))


def _status(cfg):
    procs = running(cfg)
    return {"project": cfg["project"]["uproject"], "running": bool(procs),
            "editors": [{"pid": p["pid"], "mode": p["mode"], "started": p["started"]} for p in procs],
            "mcp_url": cfg["mcp"]["url"], "mcp_listening": editor.port_open(cfg["mcp"]["port"])}


def cmd_status(a):
    cfg = get_cfg()
    s = _status(cfg)
    if a.json:
        print(json.dumps(s, indent=2))
        return
    if not s["editors"]:
        log("Editor: not running")
    for e in s["editors"]:
        log("Editor: running  pid=%s  mode=%s  started=%s" % (e["pid"], e["mode"], e["started"]))
    log("MCP:    %s  (%s)" % ("listening" if s["mcp_listening"] else "not listening", s["mcp_url"]))


def _gpu_gate(cfg, mode, force):
    if mode != "offscreen" or force:
        return
    g = gpu.sample(cfg)
    if g["busy"]:
        die("GPU looks busy (%s); not starting offscreen. Use nullrhi, wait, or pass --force-gpu."
            % "; ".join(g["reasons"]), EXIT_GPU_BUSY)


def _start(cfg, mode, force_gpu):
    _gpu_gate(cfg, mode, force_gpu)
    info, started = editor.start(cfg, mode, log)
    if not started:
        log("Already running: pid=%s mode=%s" % (info["pid"], info["mode"]))
    return info


def cmd_start(a):
    cfg = get_cfg()
    need_project(cfg)
    mode = a.mode or cfg["launch"]["default_mode"]
    procs = running(cfg)
    if procs and procs[0]["mode"] != mode:
        die("Editor already running in '%s' mode (pid %s). Use `ue ensure --mode %s` to switch (saves first)."
            % (procs[0]["mode"], procs[0]["pid"], mode))
    _start(cfg, mode, a.force_gpu)


SATISFIES = {"nullrhi": ("nullrhi", "offscreen", "gui"), "offscreen": ("offscreen", "gui"), "gui": ("gui",)}


def cmd_ensure(a):
    """Make sure an editor that can do `mode` work is running; switch modes (saving first) if not."""
    cfg = get_cfg()
    need_project(cfg)
    procs = running(cfg)
    if procs:
        cur = procs[0]["mode"]
        if cur in SATISFIES[a.mode]:
            log("OK: editor running in '%s' mode (pid %s) satisfies '%s'." % (cur, procs[0]["pid"], a.mode))
            return
        if cur == "gui":
            die("An interactive GUI editor is open; not replacing it. Close it or work in it.")
        log("Switching %s -> %s ..." % (cur, a.mode))
        _gpu_gate(cfg, a.mode, a.force_gpu)
        _stop(cfg, save=True, force=False)
    _start(cfg, a.mode, a.force_gpu)


def _stop(cfg, save, force, discard=False):
    procs = running(cfg)
    if not procs:
        log("Editor is not running.")
        return
    t_all = time.time()
    for p in procs:
        pid, mode = p["pid"], p["mode"]
        rx_ok = cfg["remote_exec"]["enabled"] and not force
        if rx_ok:
            try:
                if mode == "gui" and not save and not discard:
                    ok, out, _ = rexec.run(cfg, rexec.DIRTY)
                    if not out.startswith("dirty=0"):
                        die("GUI editor has unsaved changes (%s). Re-run with --save or --no-save." % out.strip())
                if save:
                    ok, out, _ = rexec.run(cfg, rexec.SAVE_ALL)
                    log("Save: " + out.strip())
                    if not ok:
                        die("Saving failed; editor left running. Output: %s" % out)
                try:
                    rexec.run(cfg, rexec.QUIT)
                except (OSError, RuntimeError):
                    pass  # the editor may drop the connection while quitting
                log("Asked editor pid %s (%s) to quit ..." % (pid, mode))
                if editor.wait_exit(pid, float(cfg["launch"].get("stop_timeout_s", 90))):
                    log("Stopped pid %s in %.1fs." % (pid, time.time() - t_all))
                    continue
                log("Editor did not exit in time; killing.")
            except rexec.RemoteExecError as e:
                if mode == "gui":
                    die("Cannot reach GUI editor via remote execution (%s); close it yourself or use --force." % e)
                log("Remote execution unavailable (%s); killing headless editor%s." % (e, "" if not save else " - UNSAVED CHANGES ARE LOST"))
        elif mode == "gui" and not force:
            die("Remote execution disabled; close the GUI editor yourself or use --force (unsaved changes are lost).")
        editor.kill(pid)
        editor.wait_exit(pid, 30)
        log("Killed pid %s." % pid)


def cmd_stop(a):
    cfg = get_cfg()
    need_project(cfg)
    procs = running(cfg)
    headless = all(p["mode"] != "gui" for p in procs)
    save = a.save if a.save is not None else headless
    _stop(cfg, save=save, force=a.force, discard=(a.save is False))


def cmd_restart(a):
    cfg = get_cfg()
    need_project(cfg)
    procs = running(cfg)
    mode = a.mode or (procs[0]["mode"] if procs else cfg["launch"]["default_mode"])
    _gpu_gate(cfg, mode, a.force_gpu)
    _stop(cfg, save=True, force=False)
    _start(cfg, mode, a.force_gpu)


def cmd_yield_gpu(a):
    """Free the GPU for other work: stop an offscreen editor (saving), optionally relaunch nullrhi."""
    cfg = get_cfg()
    need_project(cfg)
    procs = running(cfg)
    if not procs or procs[0]["mode"] == "nullrhi":
        log("No offscreen editor running; GPU is not used by Unreal.")
        return
    if procs[0]["mode"] == "gui":
        die("An interactive GUI editor is open; ask the user before closing it.")
    _stop(cfg, save=True, force=False)
    if a.nullrhi:
        _start(cfg, "nullrhi", False)


def cmd_gpu(a):
    cfg = get_cfg()
    g = gpu.sample(cfg)
    procs = running(cfg)
    g["unreal_offscreen_running"] = any(p["mode"] in ("offscreen", "gui") for p in procs)
    if a.json:
        print(json.dumps(g, indent=2))
        return
    log("GPU: %s  util=%s%%  vram=%s/%s MB" % (g["name"], g["util_percent"], g["vram_used_mb"], g["vram_total_mb"]))
    if g["unreal_offscreen_running"]:
        log("Note: an Unreal editor with a renderer is running and contributes to these numbers.")
    log("Busy: %s%s" % (g["busy"], (" (" + "; ".join(g["reasons"]) + ")") if g["reasons"] else ""))


def cmd_save(a):
    cfg = get_cfg()
    ok, out, _ = rexec.run(cfg, rexec.SAVE_ALL)
    log(out.strip())
    sys.exit(0 if ok else 1)


def cmd_dirty(a):
    cfg = get_cfg()
    ok, out, _ = rexec.run(cfg, rexec.DIRTY)
    log(out.strip())


def cmd_py(a):
    cfg = get_cfg()
    code = open(a.file, encoding="utf-8").read() if a.file else a.code
    if not code:
        die("Give code as an argument or with -f FILE.", 2)
    ok, out, result = rexec.run(cfg, code)
    if out:
        sys.stdout.write(out if out.endswith("\n") else out + "\n")
    if not ok:
        die("Python failed: %s" % result)


def cmd_mcp(a):
    cfg = get_cfg()
    c = mcp(cfg)
    if a.action == "toolsets":
        log(c.list_toolsets())
    elif a.action == "describe":
        d = c.describe(a.toolset)
        if a.json:
            print(json.dumps(d, indent=2))
            return
        log("%s: %s" % (d["name"], d.get("description", "").strip()))
        for t in d["tools"]:
            props = t["inputSchema"].get("properties", {})
            req = set(t["inputSchema"].get("required", []))
            args = ", ".join(("%s" if k in req else "[%s]") % k for k in props)
            log("  %s(%s)  %s" % (t["name"].split(".")[-1], args, (t.get("description") or "").strip().splitlines()[0][:100]))
    elif a.action == "call":
        args = json.loads(a.args) if a.args else {}
        try:
            r = c.call(a.toolset, a.tool, args)
        except McpError as e:
            die(str(e))
        print(json.dumps(r, indent=2) if not isinstance(r, str) else r)


ANNOTATE = {"gridSpacing": 500, "gridExtent": 5000, "gridHeight": 0, "maxLabelDistance": 5000,
            "classFilter": None, "maxLabels": 20}


def cmd_render(a):
    cfg = get_cfg()
    procs = running(cfg)
    if not procs or procs[0]["mode"] == "nullrhi":
        die("Rendering needs a renderer: run `ue ensure --mode offscreen` first (batch your render work).")
    c = mcp(cfg)
    app = "EditorToolset.EditorAppToolset"
    cams = []
    for spec in a.camera or [None]:
        if spec:
            x, y, z, pitch, yaw, roll = [float(v) for v in spec.split(",")]
            cams.append({"location": {"x": x, "y": y, "z": z}, "rotation": {"pitch": pitch, "yaw": yaw, "roll": roll},
                         "scale": {"x": 1, "y": 1, "z": 1}})
        else:
            cams.append(c.call(app, "GetCameraTransform")["returnValue"])
    base, ext = os.path.splitext(a.out)
    for i, cam in enumerate(cams):
        out = a.out if len(cams) == 1 else "%s_%d%s" % (base, i + 1, ext or ".png")
        t0 = time.time()
        rv = c.call(app, "CaptureViewport", {"captureTransform": cam, "annotations": ANNOTATE if a.annotate else None,
                                             "bShowUI": a.show_ui})["returnValue"]
        os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
        with open(out, "wb") as f:
            f.write(base64.b64decode(rv["image"]["data"]))
        log("%s  (%.1fs, camera %s)" % (os.path.abspath(out), time.time() - t0, json.dumps(cam["location"])))


def cmd_logs(a):
    cfg = get_cfg()
    p = cfg["project"]["log"]
    if not p or not os.path.exists(p):
        die("No log yet at %s" % p)
    with open(p, encoding="utf-8", errors="replace") as f:
        lines = f.readlines()
    if a.grep:
        import re
        rx = re.compile(a.grep, re.I)
        lines = [l for l in lines if rx.search(l)]
    sys.stdout.write("".join(lines[-a.tail:]))


def cmd_config(a):
    cfg = get_cfg()
    if not a.key:
        with open(disc.config_path(ROOT), encoding="utf-8") as f:
            sys.stdout.write(f.read())
        return
    v = cfg
    for part in a.key.split("."):
        v = v.get(part) if isinstance(v, dict) else None
    print(json.dumps(v) if isinstance(v, (dict, list)) else ("" if v is None else v))


# ---------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(prog="ue", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    modes = editor.MODES

    s = sub.add_parser("discover", help="(re)discover paths and write ue_local_config.local")
    s.add_argument("--port", type=int, help="preferred MCP port (default 8000)")
    s.set_defaults(fn=cmd_discover)
    s = sub.add_parser("setup", help="enable plugins, write .mcp.json, .gitignore, CLAUDE.md section")
    s.add_argument("--no-claude-md", action="store_true")
    s.set_defaults(fn=cmd_setup)
    sub.add_parser("templates", help="list engine project templates").set_defaults(fn=cmd_templates)
    s = sub.add_parser("new", help="create a project here from an engine template, then run setup")
    s.add_argument("--template", required=True, help="template id, e.g. TP_FirstPersonBP (see `ue templates`)")
    s.add_argument("--name", required=True)
    s.add_argument("--variant", help="template variant, e.g. ArenaShooter")
    s.set_defaults(fn=cmd_new)
    s = sub.add_parser("status", help="editor and MCP status")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_status)
    for name, fn, hlp in (("start", cmd_start, "start the editor (default mode from config)"),
                          ("restart", cmd_restart, "save, stop and start again")):
        s = sub.add_parser(name, help=hlp)
        s.add_argument("--mode", choices=modes)
        s.add_argument("--force-gpu", action="store_true", help="start offscreen even if the GPU looks busy")
        s.set_defaults(fn=fn)
    s = sub.add_parser("ensure", help="make sure an editor able to do MODE work is running (switches, saving first)")
    s.add_argument("--mode", choices=modes, required=True)
    s.add_argument("--force-gpu", action="store_true")
    s.set_defaults(fn=cmd_ensure)
    s = sub.add_parser("stop", help="save (headless default) and quit the editor gracefully")
    g = s.add_mutually_exclusive_group()
    g.add_argument("--save", dest="save", action="store_true", default=None)
    g.add_argument("--no-save", dest="save", action="store_false")
    s.add_argument("--force", action="store_true", help="kill without saving")
    s.set_defaults(fn=cmd_stop)
    s = sub.add_parser("yield-gpu", help="stop an offscreen editor so other processes get the GPU")
    s.add_argument("--nullrhi", action="store_true", help="relaunch headless without renderer afterwards")
    s.set_defaults(fn=cmd_yield_gpu)
    s = sub.add_parser("gpu", help="sample GPU load (is it safe to run offscreen?)")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_gpu)
    sub.add_parser("save", help="save all dirty packages").set_defaults(fn=cmd_save)
    sub.add_parser("dirty", help="list unsaved packages").set_defaults(fn=cmd_dirty)
    s = sub.add_parser("py", help="run Python in the editor (full `unreal` API)")
    s.add_argument("code", nargs="?")
    s.add_argument("-f", "--file")
    s.set_defaults(fn=cmd_py)
    s = sub.add_parser("mcp", help="call the editor's MCP server without a Claude Code MCP connection")
    msub = s.add_subparsers(dest="action", required=True)
    msub.add_parser("toolsets")
    d = msub.add_parser("describe")
    d.add_argument("toolset")
    d.add_argument("--json", action="store_true")
    c = msub.add_parser("call")
    c.add_argument("toolset")
    c.add_argument("tool")
    c.add_argument("args", nargs="?", help="JSON object of tool arguments")
    s.set_defaults(fn=cmd_mcp)
    s = sub.add_parser("render", help="capture the level viewport to PNG (needs offscreen/gui)")
    s.add_argument("out")
    s.add_argument("--camera", action="append",
                   help="x,y,z,pitch,yaw,roll; write as --camera=-400,0,300,-20,0,0 when it starts with '-' (repeat for several shots)")
    s.add_argument("--annotate", action="store_true", help="overlay grid + actor labels")
    s.add_argument("--show-ui", action="store_true")
    s.set_defaults(fn=cmd_render)
    s = sub.add_parser("logs", help="tail the editor log")
    s.add_argument("--tail", type=int, default=60)
    s.add_argument("--grep")
    s.set_defaults(fn=cmd_logs)
    s = sub.add_parser("config", help="print config, or one dotted key (e.g. mcp.url)")
    s.add_argument("key", nargs="?")
    s.set_defaults(fn=cmd_config)

    a = ap.parse_args()
    try:
        a.fn(a)
    except (disc.DiscoveryError, editor.EditorError, rexec.RemoteExecError, McpError, ValueError) as e:
        die(str(e))


if __name__ == "__main__":
    main()
