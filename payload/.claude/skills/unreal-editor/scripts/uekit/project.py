"""Project wiring (`ue setup`) and project creation from engine templates (`ue new`)."""
import glob
import json
import os
import re
import shutil
import uuid

from .discover import CONFIG_NAME

GITIGNORE_LINES = [
    "# ue-claude-kit (machine-local)", CONFIG_NAME,
    "# Unreal Engine", "Binaries/", "DerivedDataCache/", "Intermediate/", "Saved/", ".vs/", "*.sln",
]
CLAUDE_MD_BEGIN = "<!-- ue-claude-kit:begin -->"
CLAUDE_MD_END = "<!-- ue-claude-kit:end -->"
CLAUDE_MD_BODY = """## Unreal Engine (ue-claude-kit)

This project drives the Unreal editor through the `unreal-editor` skill (`.claude/skills/unreal-editor/`).
Load that skill before any Unreal work. Machine paths live in `ue_local_config.local` (gitignored; YAML).

Editor launch rules:
- No renderer needed (assets, Blueprints, actors, data, config): `-nullrhi` (`ue start`).
- Renderer needed (screenshots, thumbnails, PIE, visual checks): `-RenderOffscreen` (`ue ensure --mode offscreen`); batch render work into one session instead of restarting.
- While other processes are doing GPU work, do not run the editor offscreen (`ue gpu`; stop or switch to nullrhi).
- Interactive GUI editor only when the user asks for it.
"""


def _read(p):
    with open(p, encoding="utf-8-sig") as f:
        return f.read()


def _write(p, text, newline=None):
    with open(p, "w", encoding="utf-8", newline=newline) as f:
        f.write(text)


def enable_plugins(uproject, wanted, available):
    data = json.loads(_read(uproject))
    plugins = data.setdefault("Plugins", [])
    have = {p.get("Name"): p for p in plugins}
    added, skipped = [], []
    for name in wanted:
        if name not in available:
            skipped.append(name)
            continue
        if name in have:
            if not have[name].get("Enabled", False):
                have[name]["Enabled"] = True
                added.append(name)
        else:
            plugins.append({"Name": name, "Enabled": True})
            added.append(name)
    if added:
        _write(uproject, json.dumps(data, indent="\t") + "\n", newline="\r\n")
    return added, skipped


def write_mcp_json(root, name, url):
    p = os.path.join(root, ".mcp.json")
    data = json.loads(_read(p)) if os.path.exists(p) else {}
    servers = data.setdefault("mcpServers", {})
    entry = {"type": "http", "url": url}
    changed = servers.get(name) != entry
    servers[name] = entry
    if changed:
        _write(p, json.dumps(data, indent=2) + "\n")
    return changed


def update_gitignore(root):
    p = os.path.join(root, ".gitignore")
    existing = _read(p).splitlines() if os.path.exists(p) else []
    have = {l.strip() for l in existing}
    block, added, comment = [], [], None
    for line in GITIGNORE_LINES:
        if line.startswith("#"):
            comment = line
        elif line not in have:
            if comment:
                block.append(comment)
                comment = None
            block.append(line)
            added.append(line)
    if added:
        text = "\n".join(existing).rstrip()
        _write(p, (text + "\n\n" if text else "") + "\n".join(block) + "\n")
    return added


def update_claude_md(root):
    p = os.path.join(root, "CLAUDE.md")
    text = _read(p) if os.path.exists(p) else ""
    block = CLAUDE_MD_BEGIN + "\n" + CLAUDE_MD_BODY + CLAUDE_MD_END
    if CLAUDE_MD_BEGIN in text:
        new = re.sub(re.escape(CLAUDE_MD_BEGIN) + ".*?" + re.escape(CLAUDE_MD_END), lambda m: block, text, flags=re.S)
    else:
        new = (text.rstrip() + "\n\n" if text.strip() else "") + block + "\n"
    if new != text:
        _write(p, new)
        return True
    return False


# ---------------------------------------------------------------- templates

def list_templates(templates_dir):
    out = []
    for d in sorted(glob.glob(os.path.join(templates_dir, "TP_*"))):
        defs = os.path.join(d, "Config", "TemplateDefs.ini")
        if not os.path.exists(defs):
            continue
        txt = _read(defs)
        m = re.search(r'LocalizedDisplayNames=\(Language="en",Text="([^"]*)"\)', txt)
        variants = re.findall(r'^Variants=\(Name="([^"]+)"', txt, re.M)
        has_code = os.path.isdir(os.path.join(d, "Source"))
        out.append({"id": os.path.basename(d), "name": m.group(1) if m else "", "cpp": has_code, "variants": variants})
    return out


def _ignored(defs_txt):
    files = [f.replace("%TEMPLATENAME%", "{T}") for f in re.findall(r'^FilesToIgnore="([^"]+)"', defs_txt, re.M)]
    folders = re.findall(r'^FoldersToIgnore=(\S+)', defs_txt, re.M)
    return files, folders


def _packs(defs_txt, variant):
    """[(mount, detail_level)] for the base template plus an optional variant."""
    packs = []
    for line in defs_txt.splitlines():
        if line.startswith("SharedContentPacks="):
            m = re.search(r'MountName="([^"]+)",DetailLevels=\(\s*"?(\w+)', line)
            if m:
                packs.append((m.group(1), m.group(2)))
    if variant:
        m = re.search(r'^Variants=\(Name="%s".*$' % re.escape(variant), defs_txt, re.M)
        if not m:
            raise ValueError("Unknown variant %r" % variant)
        for lvl, mount in re.findall(r'\(DetailLevels=\((\w+)\),MountName="([^"]+)"\)', m.group(0)):
            packs.append((mount, lvl))
    return packs


def _copy_tree(src, dst):
    if os.path.isdir(src):
        shutil.copytree(src, dst, dirs_exist_ok=True)


def new_project(templates_dir, template, name, dest_root, variant=None, engine_version=None):
    """Create <dest_root>/<name>.uproject from an engine template, the way the editor's
    New Project dialog does (copy + shared content packs + renames)."""
    if not re.match(r"^[A-Za-z][A-Za-z0-9_]{0,19}$", name):
        raise ValueError("Project name must start with a letter, use letters/digits/_ and be at most 20 characters.")
    tpl = os.path.join(templates_dir, template)
    if not os.path.isdir(tpl):
        raise ValueError("Template %s not found in %s (see `ue templates`)." % (template, templates_dir))
    if glob.glob(os.path.join(dest_root, "*.uproject")):
        raise ValueError("%s already contains a .uproject." % dest_root)
    if os.path.isdir(os.path.join(tpl, "Source")):
        raise ValueError("C++ templates need source renaming and a compile step; use a Blueprint (*BP) template, "
                         "or create C++ projects from the editor's New Project dialog.")
    defs = _read(os.path.join(tpl, "Config", "TemplateDefs.ini"))
    ignore_files, ignore_folders = _ignored(defs)
    ignore_files = {f.replace("{T}", template).replace("/", os.sep) for f in ignore_files}

    for entry in os.listdir(tpl):
        src = os.path.join(tpl, entry)
        if entry in ignore_folders or entry in ignore_files:
            continue
        if os.path.isdir(src):
            for dirpath, dirnames, filenames in os.walk(src):
                rel_dir = os.path.relpath(dirpath, tpl)
                os.makedirs(os.path.join(dest_root, rel_dir), exist_ok=True)
                for fn in filenames:
                    rel = os.path.join(rel_dir, fn)
                    if rel in ignore_files:
                        continue
                    shutil.copy2(os.path.join(dirpath, fn), os.path.join(dest_root, rel))

    res_root = os.path.join(templates_dir, "TemplateResources")
    for mount, level in _packs(defs, variant):
        pack = os.path.join(res_root, level, mount)
        if not os.path.isdir(pack):
            continue
        dest_folder = mount
        man = os.path.join(pack, "FeaturePack", "manifest.json")
        if os.path.exists(man):
            dest_folder = (json.loads(_read(man)).get("AdditionalFiles") or {}).get("DestinationFilesFolder") or mount
        _copy_tree(os.path.join(pack, "Content"), os.path.join(dest_root, "Content", dest_folder))
        for ext in ("__ExternalActors__", "__ExternalObjects__"):
            _copy_tree(os.path.join(pack, ext), os.path.join(dest_root, "Content", ext, dest_folder))

    # text replacements the template asks for (ini files in BP templates)
    for dirpath, _, filenames in os.walk(os.path.join(dest_root, "Config")):
        for fn in filenames:
            if fn.endswith(".ini"):
                p = os.path.join(dirpath, fn)
                t = _read(p)
                t2 = re.sub(re.escape(template), name, t, flags=re.I)
                if t2 != t:
                    _write(p, t2)

    game_ini = os.path.join(dest_root, "Config", "DefaultGame.ini")
    _write(game_ini, "[/Script/EngineSettings.GeneralProjectSettings]\r\nProjectID=%s\r\nProjectName=%s\r\n"
           % (uuid.uuid4().hex.upper(), name), newline="")

    up = json.loads(_read(os.path.join(tpl, template + ".uproject")))
    if engine_version:
        up["EngineAssociation"] = ".".join(engine_version.split(".")[:2])
    uproject = os.path.join(dest_root, name + ".uproject")
    _write(uproject, json.dumps(up, indent="\t") + "\n", newline="\r\n")
    return uproject
