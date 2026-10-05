"""First-run discovery: find the project, the engine it uses, MCP support, a free
port and the GPU, then write ue_local_config.local (machine-local, gitignored)."""
import datetime
import glob
import json
import os
import shutil
import socket
import sys

from . import yamlite, KIT_VERSION

CONFIG_NAME = "ue_local_config.local"
IS_WIN = sys.platform == "win32"

# Toolset plugins enabled by `ue setup` when present in the engine. Edit
# `setup.plugins` in the config to change what a project gets.
DEFAULT_PLUGINS = [
    "PythonScriptPlugin", "ModelContextProtocol", "EditorToolset", "UMGToolSet",
    "ConfigSettingsToolset", "AutomationTestToolset", "StateTreeToolset", "AIModuleToolset",
    "AnimationAssistantToolset", "NiagaraToolsets", "PhysicsToolsets", "GameplayTagsToolset",
    "PluginToolset",
]


class DiscoveryError(RuntimeError):
    pass


def norm(p):
    return os.path.normpath(p).replace("\\", "/") if p else p


def find_project_root(start):
    """Walk up from `start` to the directory holding the kit (.claude/skills/unreal-editor)."""
    d = os.path.abspath(start)
    while True:
        if os.path.isdir(os.path.join(d, ".claude", "skills", "unreal-editor")):
            return d
        parent = os.path.dirname(d)
        if parent == d:
            return os.path.abspath(start)
        d = parent


def find_uprojects(root):
    hits = glob.glob(os.path.join(root, "*.uproject"))
    if not hits:
        hits = glob.glob(os.path.join(root, "*", "*.uproject")) + glob.glob(os.path.join(root, "*", "*", "*.uproject"))
    return sorted(norm(h) for h in hits if "/Saved/" not in norm(h) and "/Intermediate/" not in norm(h))


# ---------------------------------------------------------------- engines

def _engine_version(root):
    try:
        with open(os.path.join(root, "Engine", "Build", "Build.version")) as f:
            b = json.load(f)
        return "%d.%d.%d" % (b["MajorVersion"], b["MinorVersion"], b["PatchVersion"])
    except (OSError, ValueError, KeyError):
        return None


def _add(found, root, source, key=None):
    root = norm(root.rstrip("\\/"))
    ver = _engine_version(root)
    if ver and root not in [e["root"] for e in found]:
        found.append({"root": root, "version": ver, "source": source, "key": key})


def find_engines():
    """All engine installs on this machine: env override, Epic launcher, registry, source builds."""
    found = []
    if os.environ.get("UE_ENGINE_ROOT"):
        _add(found, os.environ["UE_ENGINE_ROOT"], "env:UE_ENGINE_ROOT")
    if IS_WIN:
        dat = os.path.join(os.environ.get("ProgramData", r"C:\ProgramData"), "Epic", "UnrealEngineLauncher", "LauncherInstalled.dat")
        try:
            with open(dat, encoding="utf-8") as f:
                for item in json.load(f).get("InstallationList", []):
                    if item.get("AppName", "").startswith("UE_"):
                        _add(found, item["InstallLocation"], "launcher", item["AppName"][3:])
        except (OSError, ValueError):
            pass
        try:
            import winreg
            for hive, path, src in ((winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\EpicGames\Unreal Engine", "registry"),):
                try:
                    with winreg.OpenKey(hive, path) as k:
                        for i in range(winreg.QueryInfoKey(k)[0]):
                            sub = winreg.EnumKey(k, i)
                            try:
                                with winreg.OpenKey(k, sub) as sk:
                                    _add(found, winreg.QueryValueEx(sk, "InstalledDirectory")[0], src, sub)
                            except OSError:
                                pass
                except OSError:
                    pass
            try:  # source / custom builds registered by UnrealVersionSelector: {GUID} -> path
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Epic Games\Unreal Engine\Builds") as k:
                    for i in range(winreg.QueryInfoKey(k)[1]):
                        name, val, _ = winreg.EnumValue(k, i)
                        _add(found, val, "source-build", name)
            except OSError:
                pass
        except ImportError:
            pass
    else:
        ini = os.path.expanduser("~/.config/Epic/UnrealEngine/Install.ini")
        if os.path.exists(ini):
            section = None
            for line in open(ini, encoding="utf-8", errors="ignore"):
                line = line.strip()
                if line.startswith("["):
                    section = line
                elif section == "[Installations]" and "=" in line:
                    name, path = line.split("=", 1)
                    _add(found, path, "source-build", name)
        for pattern in ("/Users/Shared/Epic Games/UE_*", os.path.expanduser("~/UnrealEngine*")):
            for p in glob.glob(pattern):
                _add(found, p, "scan")
    return found


def _vkey(v):
    return tuple(int(x) for x in v.split("."))


def resolve_engine(association, engines):
    if os.environ.get("UE_ENGINE_ROOT"):
        hit = [e for e in engines if e["source"] == "env:UE_ENGINE_ROOT"]
        if hit:
            return hit[0]
    if not engines:
        raise DiscoveryError("No Unreal Engine install found. Install one via the Epic launcher, "
                             "or set UE_ENGINE_ROOT to the engine directory (the one containing Engine/).")
    if association:
        a = association.strip("{}").upper()
        for e in engines:  # GUID-registered source build
            if e["key"] and e["key"].strip("{}").upper() == a:
                return e
        matches = [e for e in engines if e["version"] == association or e["version"].startswith(association + ".")
                   or (e["key"] or "") == association]
        if matches:
            return sorted(matches, key=lambda e: _vkey(e["version"]))[-1]
        raise DiscoveryError("Project wants engine '%s' but only these were found: %s. Set UE_ENGINE_ROOT to override."
                             % (association, ", ".join("%s (%s)" % (e["version"], e["root"]) for e in engines)))
    return sorted(engines, key=lambda e: _vkey(e["version"]))[-1]


def engine_paths(root):
    plat = "Win64" if IS_WIN else ("Mac" if sys.platform == "darwin" else "Linux")
    b = os.path.join(root, "Engine", "Binaries", plat)
    if IS_WIN:
        editor, editor_cmd = os.path.join(b, "UnrealEditor.exe"), os.path.join(b, "UnrealEditor-Cmd.exe")
        python = os.path.join(root, "Engine", "Binaries", "ThirdParty", "Python3", "Win64", "python.exe")
    elif sys.platform == "darwin":
        editor = os.path.join(b, "UnrealEditor.app", "Contents", "MacOS", "UnrealEditor")
        editor_cmd = editor
        python = os.path.join(root, "Engine", "Binaries", "ThirdParty", "Python3", "Mac", "bin", "python3")
    else:
        editor, editor_cmd = os.path.join(b, "UnrealEditor"), os.path.join(b, "UnrealEditor-Cmd")
        python = os.path.join(root, "Engine", "Binaries", "ThirdParty", "Python3", "Linux", "bin", "python3")
    return norm(editor), norm(editor_cmd if os.path.exists(editor_cmd) else editor), norm(python) if os.path.exists(python) else None


def find_engine_plugins(root, names):
    """Map plugin name -> .uplugin path for the names we care about."""
    want, hits = set(names), {}
    for dirpath, dirnames, filenames in os.walk(os.path.join(root, "Engine", "Plugins")):
        dirnames[:] = [d for d in dirnames if d not in ("Source", "Content", "Binaries", "Intermediate", "Resources", "Shaders")]
        for fn in filenames:
            if fn.endswith(".uplugin") and fn[:-8] in want:
                hits[fn[:-8]] = norm(os.path.join(dirpath, fn))
    return hits


# ---------------------------------------------------------------- misc probes

def port_free(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.3)
        return s.connect_ex(("127.0.0.1", port)) != 0


def pick_port(preferred, editor_running):
    if editor_running or port_free(preferred):
        return preferred
    for p in range(preferred + 1, preferred + 50):
        if port_free(p):
            return p
    raise DiscoveryError("No free port near %d for the MCP server." % preferred)


def find_gpu():
    smi = shutil.which("nvidia-smi")
    if not smi and IS_WIN:
        for c in (r"C:\Windows\System32\nvidia-smi.exe", r"C:\Program Files\NVIDIA Corporation\NVSMI\nvidia-smi.exe"):
            if os.path.exists(c):
                smi = c
    if not smi:
        return {"vendor": "unknown", "name": None, "smi": None}
    import subprocess
    try:
        name = subprocess.run([smi, "--query-gpu=name", "--format=csv,noheader"], capture_output=True, text=True, timeout=10).stdout.strip().splitlines()[0]
    except (OSError, subprocess.SubprocessError, IndexError):
        name = None
    return {"vendor": "nvidia", "name": name, "smi": norm(smi)}


# ---------------------------------------------------------------- config

def config_path(root):
    return os.path.join(root, CONFIG_NAME)


def load_config(root):
    p = config_path(root)
    if not os.path.exists(p):
        return None
    with open(p, encoding="utf-8-sig") as f:  # tolerate a BOM (PowerShell / Notepad edits)
        return yamlite.loads(f.read())


COMMENTS = {
    "python_exe": "Python used to run the kit (read by the ue.cmd / ue launchers).",
    "project.uproject": "null until a project exists; create one with `ue new`.",
    "engine.root": "Engine directory (contains Engine/). Override discovery with the UE_ENGINE_ROOT env var.",
    "mcp.port": "HTTP port for the in-editor MCP server; .mcp.json must point at the same port.",
    "remote_exec.enabled": "Python remote execution: full `unreal` API for save-all, graceful quit, `ue py`.",
    "launch.default_mode": "nullrhi = no renderer (default) | offscreen = GPU rendering, no window | gui = interactive.",
    "launch.extra_args": "Extra editor command-line args appended to every launch.",
    "gpu.busy_util_percent": "Offscreen launches are refused while GPU utilization (sampled) is at or above this.",
    "gpu.watch_processes": "Process names that mean 'GPU busy' when running, e.g. [blender.exe, ollama.exe].",
    "setup.plugins": "Plugins `ue setup` enables in the .uproject (only those present in the engine).",
}


def discover(root, previous=None, port=None):
    from . import editor as editor_mod  # local import: editor imports discover
    previous = previous or {}
    uprojects = find_uprojects(root)
    uproject = uprojects[0] if len(uprojects) == 1 else None
    if len(uprojects) > 1:
        prev = (previous.get("project") or {}).get("uproject")
        if prev in uprojects:
            uproject = prev
        else:
            raise DiscoveryError("Several .uproject files found; keep one per kit install or set project.uproject: %s" % uprojects)
    association = None
    if uproject:
        with open(uproject, encoding="utf-8-sig") as f:
            association = json.load(f).get("EngineAssociation") or None
    engines = find_engines()
    eng = resolve_engine(association, engines)
    editor, editor_cmd, py = engine_paths(eng["root"])
    plugin_names = DEFAULT_PLUGINS + list(((previous.get("setup") or {}).get("plugins")) or [])
    plugins = find_engine_plugins(eng["root"], set(plugin_names) | {"ModelContextProtocol", "PythonScriptPlugin"})
    rx_dir = None
    if "PythonScriptPlugin" in plugins:
        cand = os.path.join(os.path.dirname(plugins["PythonScriptPlugin"]), "Content", "Python")
        rx_dir = norm(cand) if os.path.exists(os.path.join(cand, "remote_execution.py")) else None

    name = os.path.splitext(os.path.basename(uproject))[0] if uproject else None
    proj_dir = norm(os.path.dirname(uproject)) if uproject else norm(root)
    prev_mcp = previous.get("mcp") or {}
    preferred = port or prev_mcp.get("port") or 8000
    running = bool(uproject and editor_mod.list_editors(uproject))
    chosen = pick_port(int(preferred), running)
    prev_launch, prev_gpu, prev_setup = previous.get("launch") or {}, previous.get("gpu") or {}, previous.get("setup") or {}

    cfg = {
        "kit_version": KIT_VERSION,
        "generated": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "python_exe": norm(sys.executable),
        "project": {
            "root": norm(root),
            "uproject": uproject,
            "name": name,
            "dir": proj_dir,
            "log": norm(os.path.join(proj_dir, "Saved", "Logs", name + ".log")) if name else None,
        },
        "engine": {
            "association": association,
            "version": eng["version"],
            "root": eng["root"],
            "source": eng["source"],
            "editor": editor,
            "editor_cmd": editor_cmd,
            "python": py,
            "templates": norm(os.path.join(eng["root"], "Templates")),
            "mcp_plugin": "ModelContextProtocol" in plugins,
            "available_engines": ["%s=%s" % (e["version"], e["root"]) for e in engines],
        },
        "mcp": {
            "server_name": prev_mcp.get("server_name", "unreal-mcp"),
            "port": chosen,
            "url": "http://127.0.0.1:%d/mcp" % chosen,
        },
        "remote_exec": {
            "enabled": bool(rx_dir) and (previous.get("remote_exec") or {}).get("enabled", True),
            "module_dir": rx_dir,
            "multicast_group": (previous.get("remote_exec") or {}).get("multicast_group", "239.0.0.1:6766"),
        },
        "launch": {
            "default_mode": prev_launch.get("default_mode", "nullrhi"),
            "start_timeout_s": prev_launch.get("start_timeout_s", 900),
            "stop_timeout_s": prev_launch.get("stop_timeout_s", 90),
            "extra_args": prev_launch.get("extra_args", ""),
        },
        "gpu": dict(find_gpu(), **{
            "busy_util_percent": prev_gpu.get("busy_util_percent", 40),
            "watch_processes": prev_gpu.get("watch_processes", []),
        }),
        "setup": {
            "plugins": prev_setup.get("plugins", DEFAULT_PLUGINS),
            "plugins_available": sorted(plugins),
        },
    }
    if not cfg["engine"]["mcp_plugin"]:
        cfg["engine"]["note"] = "This engine has no ModelContextProtocol plugin (added in UE 5.8); MCP commands will not work."
    return cfg


def write_config(root, cfg):
    header = ("ue-claude-kit machine-local config (gitignored). Generated by `ue discover`.\n"
              "Safe to edit; re-running discover keeps your edits to launch/gpu/setup/mcp.port.")
    with open(config_path(root), "w", encoding="utf-8", newline="\n") as f:
        f.write(yamlite.dumps(cfg, COMMENTS, header))
