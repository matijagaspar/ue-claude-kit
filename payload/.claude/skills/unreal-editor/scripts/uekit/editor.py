"""Editor process control: find, start (nullrhi / offscreen / gui), wait for MCP, stop."""
import json
import os
import socket
import subprocess
import sys
import time

IS_WIN = sys.platform == "win32"
MODES = ("nullrhi", "offscreen", "gui")


class EditorError(RuntimeError):
    pass


def _norm(p):
    return os.path.normcase(os.path.normpath(p)).replace("\\", "/") if p else ""


def list_editors(uproject):
    """Running editor processes that have `uproject` open: [{pid, mode, cmdline, started}]."""
    target = _norm(uproject)
    procs = []
    if IS_WIN:
        ps = ("Get-CimInstance Win32_Process -Filter \"Name LIKE 'UnrealEditor%.exe'\" | "
              "Select-Object ProcessId,CommandLine,@{n='Started';e={$_.CreationDate.ToString('o')}} | ConvertTo-Json -Compress")
        out = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
                             capture_output=True, text=True, timeout=30).stdout.strip()
        if out:
            rows = json.loads(out)
            for r in rows if isinstance(rows, list) else [rows]:
                procs.append((r["ProcessId"], r.get("CommandLine") or "", r.get("Started")))
    else:
        out = subprocess.run(["ps", "-eo", "pid=,lstart=,args="], capture_output=True, text=True).stdout
        for line in out.splitlines():
            parts = line.split(None, 6)
            if len(parts) == 7 and "UnrealEditor" in parts[6]:
                procs.append((int(parts[0]), parts[6], " ".join(parts[1:6])))
    hits = []
    for pid, cmd, started in procs:
        if target and target in _norm(cmd.replace('"', "")):
            hits.append({"pid": pid, "mode": mode_of(cmd), "cmdline": cmd, "started": started})
    return hits


def mode_of(cmdline):
    c = cmdline.lower()
    if "-nullrhi" in c:
        return "nullrhi"
    if "-renderoffscreen" in c:
        return "offscreen"
    return "gui"


def port_open(port, timeout=0.5):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(timeout)
        return s.connect_ex(("127.0.0.1", port)) == 0


def pid_alive(pid):
    if IS_WIN:
        out = subprocess.run(["tasklist", "/FI", "PID eq %d" % pid, "/NH"], capture_output=True, text=True).stdout
        return str(pid) in out
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def build_args(cfg, mode):
    eng, mcp = cfg["engine"], cfg["mcp"]
    uproject = cfg["project"]["uproject"]
    exe = eng["editor"] if mode == "gui" else eng["editor_cmd"]
    args = [exe, uproject,
            "-ModelContextProtocolStartServer",
            "-ModelContextProtocolPort=%d" % mcp["port"]]
    if cfg["remote_exec"].get("enabled"):
        # Command-line ini override keeps this out of the project's committed config.
        args.append("-ini:Engine:[/Script/PythonScriptPlugin.PythonScriptPluginSettings]:bRemoteExecution=True")
    if mode == "nullrhi":
        args += ["-nullrhi", "-unattended", "-nosplash", "-nosound"]
    elif mode == "offscreen":
        args += ["-RenderOffscreen", "-unattended", "-nosplash", "-nosound"]
    extra = (cfg["launch"].get("extra_args") or "").split()
    return args + extra


def spawn(args, mode):
    kw = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL, "close_fds": True}
    if IS_WIN:
        flags = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
        if mode != "gui":
            flags |= 0x08000000  # CREATE_NO_WINDOW
        try:
            return subprocess.Popen(args, creationflags=flags | 0x01000000, **kw)  # + CREATE_BREAKAWAY_FROM_JOB
        except OSError:
            return subprocess.Popen(args, creationflags=flags, **kw)
    return subprocess.Popen(args, start_new_session=True, **kw)


def start(cfg, mode, log=print):
    if mode not in MODES:
        raise EditorError("mode must be one of %s" % (MODES,))
    if not cfg["project"]["uproject"]:
        raise EditorError("No .uproject in this project yet; create one with `ue new` and re-run `ue discover`.")
    running = list_editors(cfg["project"]["uproject"])
    if running:
        return running[0], False
    port = cfg["mcp"]["port"]
    if port_open(port):
        raise EditorError("Port %d is already in use by another process; change mcp.port (and .mcp.json via `ue setup`)." % port)
    t0 = time.time()
    proc = spawn(build_args(cfg, mode), mode)
    log("Started editor in '%s' mode (pid %d); waiting for MCP on port %d ..." % (mode, proc.pid, port))
    deadline = t0 + float(cfg["launch"].get("start_timeout_s", 900))
    while time.time() < deadline:
        if port_open(port):
            # The listener opens before the editor finishes initializing; the first request
            # blocks until it has. Do that warm-up here so "ready" means calls are fast.
            from .mcpclient import Client, McpError
            try:
                Client(cfg["mcp"]["url"], timeout=max(5, deadline - time.time())).connect().list_toolsets()
            except (McpError, OSError, ValueError):
                time.sleep(1)
                continue
            log("MCP server is ready after %.1fs." % (time.time() - t0))
            return {"pid": proc.pid, "mode": mode, "seconds": round(time.time() - t0, 1)}, True
        if proc.poll() is not None:
            raise EditorError("Editor exited (code %s) before MCP came up. See %s" % (proc.returncode, cfg["project"]["log"]))
        time.sleep(0.5)
    raise EditorError("Timed out after %ss waiting for MCP; editor still running (pid %d). See %s"
                      % (cfg["launch"]["start_timeout_s"], proc.pid, cfg["project"]["log"]))


def kill(pid):
    if IS_WIN:
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)
    else:
        try:
            os.kill(pid, 9)
        except OSError:
            pass


def wait_exit(pid, timeout):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not pid_alive(pid):
            return True
        time.sleep(0.5)
    return False
