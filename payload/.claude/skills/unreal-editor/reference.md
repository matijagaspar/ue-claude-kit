# Unreal MCP reference and gotchas (UE 5.8, Epic's experimental "Unreal MCP" plugin)

## Toolset names

Names come in two styles - copy them exactly from `ue mcp toolsets`:
- C++ toolsets: `EditorToolset.EditorAppToolset`, `EditorToolset.LogsToolset`, `UMGToolSet.UMGToolSet`,
  `NiagaraToolsets.NiagaraToolset_System`, `GameplayTagsToolset.GameplayTagsToolset`, ...
- Python toolsets: `editor_toolset.toolsets.actor.ActorTools`, `...asset.AssetTools`,
  `...blueprint.BlueprintTools`, `...scene.SceneTools`, `...material.MaterialTools`,
  `...object.ObjectTools`, `state_tree_toolset.toolsets.state_tree.StateTreeTools`, ...

`tool_name` is the short name (last segment), e.g. `find_actors`, `CaptureViewport`.

## Argument quirks

- Optional parameters often still must be present. If a call fails with
  "input params are required" or "needs a default value", pass every parameter: strings as `""`,
  lists as `[]`, objects as `null`. Example:
  `ue mcp call editor_toolset.toolsets.scene.SceneTools find_actors '{"name":"","tag":"","collision_channels":[]}'`
- Object references are `{"refPath": "/Game/Path/Asset.Asset"}` (actors: the full path returned by `find_actors`).
- Transforms: `{"location":{"x":0,"y":0,"z":0},"rotation":{"pitch":0,"yaw":0,"roll":0},"scale":{"x":1,"y":1,"z":1}}`.
- Results are JSON, usually `{"returnValue": ...}`.

## Rendering

- `EditorAppToolset.CaptureViewport` needs `captureTransform` (get it from `GetCameraTransform`),
  `annotations` (`null` or the full config object) and `bShowUI`. The PNG comes back base64 inside
  `returnValue.image.data` - `ue render` handles all of this.
- Requires a renderer: works in offscreen/gui, not nullrhi.
- The first capture after a launch takes ~5 s (warm-up); later ones well under a second - batch shots.
- Editor sprites (light, player-start icons) are drawn even with `bShowUI=false`.
- `--annotate` overlays a ground grid and actor labels; useful before spatial edits (placing actors).

## Python

- `ue py` uses the PythonScriptPlugin remote execution (enabled per launch via a command-line ini
  override, local host only). It runs in the editor process with the full `unreal` module.
- Print what you need; the printed output is returned. Multi-statement scripts are fine.
- Useful: `unreal.EditorAssetLibrary`, `unreal.get_editor_subsystem(unreal.EditorActorSubsystem)` (EditorLevelLibrary is deprecated in 5.8),
  `unreal.EditorLoadingAndSavingUtils.save_dirty_packages(True, True)`, `unreal.AssetToolsHelpers.get_asset_tools()`.

## Timings (mid/high-end desktop GPU, warm caches, FirstPerson template)

| Step | Time |
|---|---|
| nullrhi start -> MCP ready | ~10-70 s (first launch of a project is the slow one) |
| offscreen start -> MCP ready | ~14 s |
| first capture / later captures | ~5 s / <1 s |
| save + graceful stop | ~2 s |

## Troubleshooting

- `ue status` says not running but port busy: another program owns the port - change `mcp.port`
  in the config, then `ue setup` (rewrites `.mcp.json`) and restart Claude Code.
- Editor exits during start: `ue logs --grep "Error|Fatal"`.
- New plugins enabled while running: `ue restart`.
- Engine moved/upgraded: `ue discover`.
