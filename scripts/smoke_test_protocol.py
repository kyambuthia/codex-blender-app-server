#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import time

from codex_blender_unsafe.app_server import CodexAppServerClient, default_workspace


def fake_tool_runner(tool_name: str, arguments):
    if tool_name == "blender_get_scene_summary":
        return {
            "success": True,
            "contentItems": [
                {
                    "type": "inputText",
                    "text": json.dumps(
                        {
                            "scene_name": "SmokeTestScene",
                            "object_count": 1,
                            "selected_objects": ["Cube"],
                            "active_object": "Cube",
                        },
                        indent=2,
                    ),
                }
            ],
        }
    if tool_name == "blender_read_text_block":
        return {"success": True, "contentItems": [{"type": "inputText", "text": "print('hello')"}]}
    if tool_name == "blender_write_text_block":
        name = arguments.get("name", "unknown")
        return {"success": True, "contentItems": [{"type": "inputText", "text": f"wrote {name}"}]}
    if tool_name == "blender_run_python":
        return {
            "success": True,
            "contentItems": [{"type": "inputText", "text": "fake blender.run_python executed"}],
        }
    return {"success": False, "contentItems": [{"type": "inputText", "text": f"unknown tool {tool_name}"}]}


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke test the Codex App Server bridge.")
    parser.add_argument("--cwd", default=default_workspace())
    parser.add_argument("--model", default="gpt-5.4")
    parser.add_argument(
        "--prompt",
        default="Use blender_get_scene_summary, then describe the current scene in one short paragraph.",
        help="Optional prompt to send after connecting.",
    )
    parser.add_argument(
        "--skip-prompt",
        action="store_true",
        help="Only test initialize + thread/start.",
    )
    args = parser.parse_args()

    client = CodexAppServerClient(cwd=args.cwd, model=args.model)
    try:
        client.start()
        print(json.dumps({"status": client.get_status(), "thread_id": client.thread_id}, indent=2))
        if not args.skip_prompt:
            client.send_prompt(args.prompt)
            deadline = time.time() + 20
            while time.time() < deadline:
                time.sleep(0.25)
                client.poll(fake_tool_runner)
                if client.get_status() not in {"running", "starting"}:
                    break
            print("\nAssistant output:\n")
            print(client.get_assistant_text())
        print("\nRecent events:\n")
        print("\n".join(client.get_events()[-20:]))
        return 0
    finally:
        client.stop()


if __name__ == "__main__":
    raise SystemExit(main())
