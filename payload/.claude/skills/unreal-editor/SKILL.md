---
name: unreal-editor
description: Drive the Unreal Engine editor for this project - start/stop it headless (nullrhi) or offscreen on demand, call its built-in MCP toolsets (actors, Blueprints, materials, UMG, StateTree, Niagara...), run Python with the full `unreal` API, save, and capture viewport renders. Use for any task that reads or changes Unreal assets, levels or editor state, or needs a screenshot of the game.
---

# Unreal editor (ue-claude-kit)

The `ue` CLI in the project root controls the editor. Machine-specific paths live in
`ue_local_config.local` (YAML, gitignored) - read it instead of guessing paths
(`ue config` prints it, `ue config engine.root` prints one key). The first `ue` run
discovers everything and writes that file; `ue discover` refreshes it.

The kit sits in the repo root; the Unreal project may be in a subfolder (monorepo) -
`ue config project.uproject_rel` / `project.dir` tell you where. Asset and Content paths are
relative to that project folder, not the repo root.

Invoke it as `./ue <cmd>` from Bash (Git Bash) or `.\ue.cmd <cmd>` from PowerShell/cmd.
JSON arguments are easiest from Bash with single quotes.

## Launch rules (follow these)

1. **No renderer needed** (assets, Blueprints, actors, properties, data tables, config,
   gameplay tags, automation tests): run headless without renderer: `ue ensure --mode nullrhi`.
2. **Renderer needed** (renders/screenshots, thumbnails, Play-In-Editor, material or lighting
   checks): `ue ensure --mode offscreen`. **Batch**: do all non-visual edits first, then switch
   once and do every render-dependent step in that one session. Don't bounce between modes per
   operation - each restart costs ~15 s.
3. **Other GPU work** (ML jobs, renders, games, benchmarks the user runs or you are about to run):
   the editor must not run offscreen. Before launching such work run `ue yield-gpu` (add
   `--nullrhi` to keep a headless editor available). `ue start/ensure --mode offscreen` refuses when
   `ue gpu` says the GPU is busy (exit code 3) - don't override with `--force-gpu` unless the user says so.
4. **GUI** (`--mode gui`) only when the user explicitly asks for an interactive editor. Never close
   a GUI editor with unsaved changes without asking; `ue stop` refuses in that case.
5. Stop the editor when the task is done (`ue stop` saves all dirty packages first for headless
   editors). Don't leave it running between unrelated tasks unless the user wants that.

`ensure` is idempotent: an offscreen editor also satisfies nullrhi work, so once you are offscreen
for a batch, finish non-render follow-ups there before stopping.

## Commands

| Command | What it does |
|---|---|
| `ue status [--json]` | running editors (pid, mode) and whether MCP is listening |
| `ue ensure --mode nullrhi\|offscreen\|gui` | start, or switch mode (saves first) |
| `ue start` / `ue stop [--save\|--no-save\|--force]` / `ue restart [--mode M]` | lifecycle |
| `ue yield-gpu [--nullrhi]` | stop an offscreen editor to free the GPU |
| `ue gpu [--json]` | sampled GPU utilization, busy verdict |
| `ue mcp toolsets` | list toolsets |
| `ue mcp describe <toolset>` | tool names + args (`[x]` = optional) |
| `ue mcp call <toolset> <tool> '<json>'` | call a tool, prints JSON result |
| `ue py "<code>"` / `ue py -f script.py` | run Python in the editor, full `unreal` module |
| `ue save` / `ue dirty` | save all / list unsaved packages |
| `ue render out.png [--camera=x,y,z,pitch,yaw,roll]... [--annotate]` (use `=` form; repeat for a batch) | viewport capture (offscreen/gui only) |
| `ue logs [--tail N] [--grep RE]` | editor log |
| `ue new --template TP_FirstPersonBP --name Game` / `ue templates` | create a project from a template |
| `ue setup` | enable plugins, write `.mcp.json`, `.gitignore`, `CLAUDE.md` section |

## MCP: direct tools vs the CLI

`.mcp.json` registers the editor's server (default `unreal-mcp`, `http://127.0.0.1:8000/mcp`).
Claude Code connects only at startup, so if the editor wasn't running then, the
`mcp__unreal-mcp__*` tools are missing or failed - use `ue mcp ...` instead (same server, works any
time the editor runs), or ask the user to reconnect via `/mcp`.

The server exposes three meta-tools: `list_toolsets`, `describe_toolset`, `call_tool`
(`toolset_name`, `tool_name`, `arguments`). Always `describe` a toolset before first use.
Details and gotchas: [reference.md](reference.md).

## C++ projects (not handled by the kit)

If the `.uproject` lists `Modules` (there is a `Source/` folder), the kit does not compile code
and a headless editor cannot rebuild stale modules - it exits on start. Before starting, or after
changing C++ code (with the editor stopped), build the editor target yourself:
`"<engine.root>/Engine/Build/BatchFiles/Build.bat" <ProjectName>Editor Win64 Development -Project="<project.uproject>" -WaitMutex`
(values from `ue config`). It needs a C++ toolchain (Visual Studio "Game development with C++");
if that's missing, tell the user. When `ue start` says the editor exited, check
`ue logs --grep "module|Modules"` first.

## Choosing MCP tools vs `ue py`

- Prefer MCP toolsets for supported operations (they validate inputs and handle transactions).
- Use `ue py` for things the toolsets lack: bulk operations, `unreal.EditorAssetLibrary`,
  `EditorLevelLibrary`, project settings, anything in the Python API. The MCP
  `ProgrammaticToolset.execute_tool_script` sandbox cannot import `unreal` - don't use it for that.
- Save explicitly after changes (`ue save`); headless editors have no save prompt.
