"""GPU busy check used to keep the offscreen editor from competing with other GPU work.

On Windows (WDDM) nvidia-smi cannot attribute usage per process, so the check uses
sampled overall utilization plus an optional watch-list of process names."""
import subprocess
import sys
import time


def sample(cfg, samples=4, interval=0.5):
    g = cfg.get("gpu") or {}
    info = {"vendor": g.get("vendor"), "name": g.get("name"), "util_percent": None, "vram_used_mb": None,
            "vram_total_mb": None, "watched_running": [], "busy": False, "reasons": []}
    smi = g.get("smi")
    if smi:
        utils = []
        for i in range(samples):
            try:
                out = subprocess.run([smi, "--query-gpu=utilization.gpu,memory.used,memory.total",
                                      "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=10).stdout
                u, used, total = [float(x) for x in out.strip().splitlines()[0].split(",")]
                utils.append(u)
                info["vram_used_mb"], info["vram_total_mb"] = int(used), int(total)
            except (OSError, ValueError, IndexError, subprocess.SubprocessError):
                break
            if i < samples - 1:
                time.sleep(interval)
        if utils:
            info["util_percent"] = round(sum(utils) / len(utils), 1)
            if info["util_percent"] >= float(g.get("busy_util_percent", 40)):
                info["reasons"].append("GPU utilization %.0f%% >= %s%%" % (info["util_percent"], g.get("busy_util_percent", 40)))
    watch = [w.lower() for w in (g.get("watch_processes") or [])]
    if watch:
        running = _process_names()
        info["watched_running"] = sorted({w for w in watch if w in running})
        if info["watched_running"]:
            info["reasons"].append("watched GPU process running: %s" % ", ".join(info["watched_running"]))
    info["busy"] = bool(info["reasons"])
    return info


def _process_names():
    if sys.platform == "win32":
        out = subprocess.run(["tasklist", "/FO", "CSV", "/NH"], capture_output=True, text=True).stdout
        return {l.split('","')[0].strip('"').lower() for l in out.splitlines() if l}
    out = subprocess.run(["ps", "-eo", "comm="], capture_output=True, text=True).stdout
    return {l.strip().rsplit("/", 1)[-1].lower() for l in out.splitlines()}
