"""Python remote execution into the running editor (full `unreal` API), using the
engine's own remote_execution.py from PythonScriptPlugin. Local-host only (TTL 0)."""
import os
import sys
import time


class RemoteExecError(RuntimeError):
    pass


def _module(cfg):
    d = cfg["remote_exec"].get("module_dir")
    if not cfg["remote_exec"].get("enabled") or not d:
        raise RemoteExecError("Remote execution is disabled or unavailable (remote_exec in %s)." % "ue_local_config.local")
    if d not in sys.path:
        sys.path.insert(0, d)
    import remote_execution
    return remote_execution


def run(cfg, code, discover_timeout=15):
    """Execute `code` (a script, may contain multiple statements) in the editor of this project.
    Returns (success, output_text, result)."""
    rx = _module(cfg)
    conf = rx.RemoteExecutionConfig()
    host, port = cfg["remote_exec"].get("multicast_group", "239.0.0.1:6766").split(":")
    conf.multicast_group_endpoint = (host, int(port))
    r = rx.RemoteExecution(conf)
    r.start()
    try:
        want = os.path.normcase(os.path.normpath(cfg["project"]["dir"]))
        node, deadline = None, time.time() + discover_timeout
        while time.time() < deadline and not node:
            for n in r.remote_nodes:
                if os.path.normcase(os.path.normpath(n.get("project_root", ""))) == want:
                    node = n
            time.sleep(0.1)
        if not node:
            raise RemoteExecError("Editor for %s not found via remote execution (is it running with remote_exec enabled?)" % want)
        r.open_command_connection(node["node_id"])
        res = r.run_command(code, unattended=True, exec_mode=rx.MODE_EXEC_FILE)
        out = "".join(o.get("output", "") for o in res.get("output", []))
        return bool(res.get("success")), out, res.get("result")
    finally:
        r.stop()


SAVE_ALL = """
import unreal
dirty = [p.get_name() for p in unreal.EditorLoadingAndSavingUtils.get_dirty_content_packages()]
dirty += [p.get_name() for p in unreal.EditorLoadingAndSavingUtils.get_dirty_map_packages()]
ok = unreal.EditorLoadingAndSavingUtils.save_dirty_packages(True, True) if dirty else True
print("saved=%s packages=%d %s" % (ok, len(dirty), dirty[:20]))
"""

DIRTY = """
import unreal
d = [p.get_name() for p in unreal.EditorLoadingAndSavingUtils.get_dirty_content_packages()]
d += [p.get_name() for p in unreal.EditorLoadingAndSavingUtils.get_dirty_map_packages()]
print("dirty=%d %s" % (len(d), d[:20]))
"""

QUIT = """
import unreal
unreal.SystemLibrary.quit_editor()
"""
