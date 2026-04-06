from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import bpy


REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from codex_blender_unsafe.app_server import CodexAppServerClient
from codex_blender_unsafe.toolhost import BlenderToolHost


def wait_for_turn(client: CodexAppServerClient, timeout_s: float = 45.0) -> None:
    toolhost = BlenderToolHost()
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        client.poll(toolhost.dispatch, limit=8)
        status = client.get_status()
        if status not in {"running", "starting"}:
            return
        time.sleep(0.2)
    raise TimeoutError(
        f"Turn did not finish within {timeout_s} seconds\nRecent events:\n" + "\n".join(client.get_events()[-20:])
    )


def main() -> int:
    bpy.ops.wm.read_factory_settings(use_empty=True)

    workspace = str(REPO_ROOT)
    client = CodexAppServerClient(cwd=workspace, model="gpt-5.4")
    timeout_s = float(os.environ.get("CODEX_BLENDER_TEST_TIMEOUT", "45"))
    try:
        client.start()
        prompt = (
            "Use only structured Blender tools and do not call blender_run_python. "
            "Create a UV sphere named CodexTestSphere at location (3, 0, 0). "
            "Create a material named CodexRed with base color [0.9, 0.1, 0.1, 1.0]. "
            "Assign that material to CodexTestSphere. "
            "Then call blender_get_object_info for CodexTestSphere and report its material and location."
        )
        client.send_prompt(prompt)
        wait_for_turn(client, timeout_s=timeout_s)

        sphere = bpy.data.objects.get("CodexTestSphere")
        material = bpy.data.materials.get("CodexRed")
        assigned_material = None
        if sphere and sphere.material_slots and sphere.material_slots[0].material:
            assigned_material = sphere.material_slots[0].material.name
        result = {
            "status": client.get_status(),
            "thread_id": client.thread_id,
            "assistant_output": client.get_assistant_text(),
            "object_names": sorted(obj.name for obj in bpy.data.objects),
            "sphere_exists": sphere is not None,
            "sphere_location": list(sphere.location) if sphere else None,
            "assigned_material": assigned_material,
            "material_exists": material is not None,
            "recent_events": client.get_events()[-25:],
        }
        print(json.dumps(result, indent=2))

        if client.get_status() != "completed":
            raise RuntimeError(f"turn ended with status {client.get_status()}")
        if sphere is None:
            raise RuntimeError("CodexTestSphere was not created")
        if material is None:
            raise RuntimeError("CodexRed material was not created")
        if assigned_material != "CodexRed":
            raise RuntimeError(f"CodexRed was not assigned to CodexTestSphere: {assigned_material}")
        if tuple(round(v, 3) for v in sphere.location) != (3.0, 0.0, 0.0):
            raise RuntimeError(f"CodexTestSphere location mismatch: {tuple(sphere.location)}")
        if "CodexTestSphere" not in client.get_assistant_text():
            raise RuntimeError("assistant output did not mention CodexTestSphere")
        if "CodexRed" not in client.get_assistant_text():
            raise RuntimeError("assistant output did not mention CodexRed")
        recent_events = "\n".join(client.get_events())
        if "tool call blender_run_python" in recent_events:
            raise RuntimeError("structured tool test unexpectedly used blender_run_python")
        for required_tool in (
            "tool call blender_create_primitive",
            "tool call blender_create_material",
            "tool call blender_assign_material",
            "tool call blender_get_object_info",
        ):
            if required_tool not in recent_events:
                raise RuntimeError(f"structured tool test missed expected tool: {required_tool}")
        return 0
    finally:
        client.stop()


if __name__ == "__main__":
    raise SystemExit(main())
