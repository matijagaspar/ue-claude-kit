# ue-claude-kit

Lets Claude Code drive the Unreal editor of a project automatically: it starts the editor
on demand (headless without a renderer, offscreen with a renderer, or GUI), talks to Epic's
built-in **Unreal MCP** server, runs Python with the full `unreal` API, saves, and captures
viewport renders. Everything machine-specific is discovered on first run.

Requirements: Unreal Engine **5.8+** (ships the experimental ModelContextProtocol plugin),
Python 3.8+ (any; Unreal's bundled one works), Windows (tested). Linux/macOS paths are
implemented but untested.

## Install into a project

The kit is fetched once and copied into the project. From then on it is part of the
project (commit it) and maintained there; it does not track this repository.

**Ask Claude** (in Claude Code, inside the project):

> Install ue-claude-kit from https://github.com/matijagaspar/ue-claude-kit into this project.

Claude should run the clone + install command below, then start using the `unreal-editor` skill.
If you already have a checkout of the kit anywhere, `python <kit>/bootstrap.py <project_dir>` does
the same (fresh clone of `main`, install, cleanup; `--ref` picks a branch/tag).

**Or run it yourself** from the project directory:

```sh
# clone + install + clean up (uses your git credentials, so it works while the repo is private)
git clone --depth 1 https://github.com/matijagaspar/ue-claude-kit.git /tmp/uck && python /tmp/uck/install.py . --source "ue-claude-kit@$(git -C /tmp/uck rev-parse --short HEAD)" && rm -rf /tmp/uck

# one-liner - ONLY if the repo is public (raw.githubusercontent.com rejects private repos):
# downloads bootstrap.py, which fetches the kit into a temp folder, installs it, deletes the temp copy
python -c "import urllib.request as u; exec(u.urlopen('https://raw.githubusercontent.com/matijagaspar/ue-claude-kit/main/bootstrap.py').read())" .
```

PowerShell: `git clone --depth 1 https://github.com/matijagaspar/ue-claude-kit.git $env:TEMP\uck; python $env:TEMP\uck\install.py .; Remove-Item -Recurse -Force $env:TEMP\uck`

Options (passed to `install.py`):

```
--new TP_FirstPersonBP --name MyGame   create the project from an engine template (empty dir)
--variant ArenaShooter                 template variant
--port 8010                            preferred MCP port (default 8000)
--no-setup                             copy + discover only, don't touch the .uproject/.mcp.json
--force                                overwrite an existing kit install (local changes are lost)
--ref v1.0.0                           (bootstrap) branch or tag to fetch, default main
```

No Python on PATH? Use the engine's: `<Engine>\Engine\Binaries\ThirdParty\Python3\Win64\python.exe bootstrap.py .`
From a local checkout you can also run `python install.py <project_dir>` directly.

The installer:

1. copies `.claude/skills/unreal-editor/` (skill + CLI) and the `ue` / `ue.cmd` launchers into the project,
2. runs `ue discover` -> writes **`ue_local_config.local`** (YAML, gitignored): engine install
   (from the `.uproject` EngineAssociation via the Epic launcher, registry, source-build registry
   or `UE_ENGINE_ROOT`), editor binaries, bundled Python, MCP plugin presence, a free MCP port,
   remote-execution module, GPU,
3. runs `ue setup` -> enables the MCP + toolset + Python plugins in the `.uproject` (only those the
   engine has), writes/merges `.mcp.json`, adds `.gitignore` entries, and adds a short
   ue-claude-kit section to `CLAUDE.md`.

Then start Claude Code in the project and approve the `unreal-mcp` server when asked.
`.claude/skills/unreal-editor/KIT_SOURCE` records which repo/commit was installed.

Commit: `.claude/skills/unreal-editor/`, `ue`, `ue.cmd`, `.mcp.json`, the `.uproject` change, `CLAUDE.md`.
Don't commit: `ue_local_config.local` (already gitignored).

## What Claude does with it

`CLAUDE.md` and the skill give Claude these rules:

- work that doesn't need the renderer -> `-nullrhi`
- work that needs it (renders, PIE, visual checks) -> `-RenderOffscreen`, batched into one session
- while other processes use the GPU -> no offscreen editor (`ue yield-gpu`; offscreen starts are refused when `ue gpu` reports busy)
- interactive GUI editor only when you ask for it

## CLI cheatsheet

```
ue status                     ue ensure --mode nullrhi|offscreen|gui
ue stop | restart             ue yield-gpu [--nullrhi]      ue gpu
ue mcp toolsets               ue mcp describe <toolset>     ue mcp call <toolset> <tool> '<json>'
ue py "print(unreal.SystemLibrary.get_engine_version())"
ue save | dirty               ue render out.png [--camera x,y,z,pitch,yaw,roll]
ue logs --grep Error          ue config [key]               ue discover | setup | templates | new
```

## Design notes

- **Vendored, not a plugin**: the kit lives inside the project's git so teammates and CI get the
  exact same scripts; each project still needs its own `.uproject`/`.mcp.json` wiring anyway.
- **No committed engine settings**: MCP start/port and Python remote execution are passed on the
  editor command line (`-ModelContextProtocolStartServer`, `-ini:Engine:[...]:bRemoteExecution=True`),
  so only the plugin list in the `.uproject` changes.
- **Graceful stop**: saves dirty packages and calls `unreal.SystemLibrary.quit_editor()` via
  remote execution; falls back to killing headless editors only.
- **Standard library only**: no pip installs; the config file uses a small YAML subset any YAML parser reads.
- **GPU check**: Windows can't attribute GPU usage per process, so `ue gpu` samples overall
  utilization (`gpu.busy_util_percent`, default 40) plus an optional `gpu.watch_processes` list.
