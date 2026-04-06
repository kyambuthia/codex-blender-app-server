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
    raise TimeoutError(f"Turn did not finish within {timeout_s} seconds")


def main() -> int:
    bpy.ops.wm.read_factory_settings(use_empty=True)

    workspace = str(REPO_ROOT)
    client = CodexAppServerClient(cwd=workspace, model="gpt-5.4")
    try:
        client.start()
        prompt = (
            "Use blender_run_python to create a UV sphere named CodexTestSphere at location (3, 0, 0). "
            "Then call blender_get_scene_summary and report the object count plus whether CodexTestSphere exists. "
            "Do not only describe the steps."
        )
        client.send_prompt(prompt)
        wait_for_turn(client)

        sphere = bpy.data.objects.get("CodexTestSphere")
        result = {
            "status": client.get_status(),
            "thread_id": client.thread_id,
            "assistant_output": client.get_assistant_text(),
            "object_names": sorted(obj.name for obj in bpy.data.objects),
            "sphere_exists": sphere is not None,
            "sphere_location": list(sphere.location) if sphere else None,
            "recent_events": client.get_events()[-25:],
        }
        print(json.dumps(result, indent=2))

        if client.get_status() != "completed":
            raise RuntimeError(f"turn ended with status {client.get_status()}")
        if sphere is None:
            raise RuntimeError("CodexTestSphere was not created")
        if tuple(round(v, 3) for v in sphere.location) != (3.0, 0.0, 0.0):
            raise RuntimeError(f"CodexTestSphere location mismatch: {tuple(sphere.location)}")
        if "CodexTestSphere" not in client.get_assistant_text():
            raise RuntimeError("assistant output did not mention CodexTestSphere")
        return 0
    finally:
        client.stop()


if __name__ == "__main__":
    raise SystemExit(main())
