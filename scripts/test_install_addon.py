from __future__ import annotations

import json
import sys
from pathlib import Path

import bpy


def main() -> int:
    if "--" not in sys.argv:
        raise RuntimeError("Expected zip path after --")

    zip_path = Path(sys.argv[sys.argv.index("--") + 1]).resolve()
    if not zip_path.exists():
        raise RuntimeError(f"Zip file not found: {zip_path}")

    bpy.ops.preferences.addon_install(overwrite=True, filepath=str(zip_path))
    bpy.ops.preferences.addon_enable(module="codex_blender_unsafe")

    import codex_blender_unsafe

    workspace = codex_blender_unsafe._ensure_codex_workspace()
    if workspace is None:
        raise RuntimeError("Codex workspace was not created")
    area_types = []
    for screen in workspace.screens:
        area_types.extend(area.type for area in screen.areas)

    payload = {
        "zip_path": str(zip_path),
        "module_file": str(Path(codex_blender_unsafe.__file__).resolve()),
        "addon_enabled": "codex_blender_unsafe" in bpy.context.preferences.addons.keys(),
        "bl_info_name": codex_blender_unsafe.bl_info["name"],
        "bl_info_version": ".".join(str(part) for part in codex_blender_unsafe.bl_info["version"]),
        "workspace_name": workspace.name,
        "workspace_area_types": area_types,
    }
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
