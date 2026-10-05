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

The kit always goes into the **repo root** - the folder where you run Claude Code. The
Unreal project can be right there or in a subfolder (monorepo):

```
my-game/                     my-monorepo/
  MyGame.uproject              .claude/skills/unreal-editor/   <- kit
  Content/ Config/             ue, ue.cmd, .mcp.json, CLAUDE.md
  .claude/skills/...  <- kit   web/  services/  ...
  ue, ue.cmd, .mcp.json        ue_project/MyGame/MyGame.uproject
```

**Ask Claude** (in Claude Code, at the repo root):

> Install ue-claude-kit from https://github.com/matijagaspar/ue-claude-kit into this project.

Claude should follow [Notes for the installing agent](#notes-for-the-installing-agent), run the
install command below, then use the `unreal-editor` skill.

**Or run it yourself** from the repo root:

```sh
# one-liner (bash, PowerShell or cmd): downloads bootstrap.py, which fetches the kit into a temp
# folder (git clone, or a zip download when git is missing), installs it and deletes the temp copy.
# Install options go after the "." - e.g.  . --uproject ue_project/MyGame/MyGame.uproject
python -c "import urllib.request as u; exec(u.urlopen('https://raw.githubusercontent.com/matijagaspar/ue-claude-kit/main/bootstrap.py').read())" .

# or clone + install + clean up yourself
git clone --depth 1 https://github.com/matijagaspar/ue-claude-kit.git /tmp/uck && python /tmp/uck/install.py . --source "ue-claude-kit@$(git -C /tmp/uck rev-parse --short HEAD)" && rm -rf /tmp/uck
```

PowerShell clone variant: `git clone --depth 1 https://github.com/matijagaspar/ue-claude-kit.git $env:TEMP\uck; python $env:TEMP\uck\install.py .; Remove-Item -Recurse -Force $env:TEMP\uck`

Prefer to read what you run first? Open [bootstrap.py](bootstrap.py) - it only clones/downloads this
repo into a temp folder and runs `install.py`.

If you already have a checkout of the kit anywhere, `python <kit>/bootstrap.py <repo_root> [options]`
does the same (fresh clone of `main`, install, cleanup; `--ref` picks a branch/tag).

### Which options

| Situation | Add to `install.py .` |
|---|---|
| Existing project, `.uproject` in the repo root | nothing |
| Existing project in a subfolder (monorepo), only one `.uproject` within 5 levels | nothing - it is found automatically |
| Several `.uproject` files, or it is deeper than 5 levels | `--uproject ue_project/MyGame/MyGame.uproject` |
| Empty repo, new project in the root | `--new TP_FirstPersonBP --name MyGame` |
| Monorepo, new project in a subfolder | `--new TP_FirstPersonBP --name MyGame --dir ue_project/MyGame` |

```
--uproject PATH                        existing .uproject to use (relative to the repo root)
--new TEMPLATE --name NAME [--dir D]   create a Blueprint project from an engine template (`ue templates` lists them)
--variant ArenaShooter                 template variant (with --new)
--port 8010                            preferred MCP port (default 8000)
--no-setup                             copy + discover only, don't touch the .uproject/.mcp.json/.gitignore
--force                                overwrite an existing kit install (local changes are lost)
--ref v1.0.0                           (bootstrap only) branch or tag to fetch, default main
```

The project search skips `.git`, `node_modules`, `Saved`, `Intermediate`, `Binaries`, `Plugins`,
`Content`, `Source` and similar folders. A chosen project is remembered in the config; switch later
with `ue discover --uproject <path>`. If discovery fails, the install is rolled back so you can re-run it.

No Python on PATH? Use the engine's: `<Engine>\Engine\Binaries\ThirdParty\Python3\Win64\python.exe install.py .`

### What the installer changes

1. copies `.claude/skills/unreal-editor/` (skill + CLI) and the `ue` / `ue.cmd` launchers into the repo
   root, and adds `.gitattributes` rules that keep their line endings intact,
2. runs `ue discover` -> writes **`ue_local_config.local`** (YAML, gitignored) in the repo root:
   engine install (from the `.uproject` EngineAssociation via the Epic launcher, registry,
   source-build registry or `UE_ENGINE_ROOT`), editor binaries, bundled Python, MCP plugin
   presence, a free MCP port, remote-execution module, GPU,
3. runs `ue setup`:
   - enables the MCP + toolset + Python plugins in the `.uproject` (only those the engine has),
   - writes/merges `.mcp.json` in the repo root (other servers are kept),
   - root `.gitignore`: `/ue_local_config.local`; the project folder's `.gitignore`: anchored
     Unreal rules (`/Binaries/`, `/Saved/`, `/Intermediate/`, ...) so they never hide folders
     elsewhere in a monorepo; existing equivalent rules are not duplicated,
   - adds a marked ue-claude-kit block to `CLAUDE.md` (with the project's relative path).

`.claude/skills/unreal-editor/KIT_SOURCE` records which repo/commit was installed.

Commit: `.claude/skills/unreal-editor/`, `ue`, `ue.cmd`, `.gitattributes`, `.mcp.json`, `.gitignore`
changes, the `.uproject` change, `CLAUDE.md`. Don't commit: `ue_local_config.local`.

### Notes for the installing agent

- Run the install from the repo root the user works in. Look for `.uproject` files first; if there
  are several, ask the user which one and pass `--uproject`. If there is none, ask whether to create
  one (template, name, and for a monorepo the `--dir`).
- If an editor has the project open, ask the user to save and close it first (setup edits the `.uproject`).
- After installing, run `./ue start` then `./ue stop` once to confirm the editor launches headless,
  and tell the user to restart Claude Code so the `unreal-mcp` server from `.mcp.json` loads.
- Show the user the diff of their existing files (`.uproject`, `.gitignore`, `.mcp.json`, `CLAUDE.md`)
  before they commit.
- **C++ projects** (the `.uproject` has a `Modules` list / there is a `Source/` folder): the kit does
  not compile code. A headless editor cannot rebuild missing or stale project modules - it just
  exits, and the log says modules are missing or were built with a different engine version.
  Mitigate it as the agent:
  - before the first `ue start`, check that `Binaries/<Platform>/UnrealEditor-<Module>.dll` (Win64)
    exists for each module and is newer than the `Source/` files; if not, build the editor target
    with the engine's build script while the editor is closed:
    `"<engine.root>/Engine/Build/BatchFiles/Build.bat" <ProjectName>Editor Win64 Development -Project="<uproject>" -WaitMutex`
    (Linux/macOS: `Engine/Build/BatchFiles/<Linux|Mac>/Build.sh`). Paths come from `ue config`.
  - this needs a C++ toolchain (Visual Studio with the "Game development with C++" workload on
    Windows); if it is missing, tell the user instead of trying to install it,
  - after changing C++ code, `ue stop`, build, then start again (Live Coding only applies to a GUI editor),
  - if `ue start` reports the editor exited, check `ue logs --grep "module|Modules"` first.

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
ue save | dirty               ue render out.png [--camera=x,y,z,pitch,yaw,roll]
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

## License

MIT - see [LICENSE](LICENSE). Unreal Engine and its plugins are not included; the kit uses your own engine install.
