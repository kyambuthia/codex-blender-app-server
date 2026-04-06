from __future__ import annotations

import contextlib
import io
import json
import traceback
from typing import Any

import bpy


def _text_item(text: str) -> dict[str, Any]:
    return {"type": "inputText", "text": text}


class BlenderToolHost:
    def dispatch(self, tool_name: str, arguments: Any) -> dict[str, Any]:
        args = arguments or {}

        if tool_name == "blender_get_scene_summary":
            return self._ok(self._scene_summary())

        if tool_name == "blender_read_text_block":
            return self._ok(self._read_text_block(args["name"]))

        if tool_name == "blender_write_text_block":
            return self._ok(self._write_text_block(args["name"], args["content"]))

        if tool_name == "blender_run_python":
            return self._run_python(
                code=args["code"],
                return_variable=args.get("return_variable"),
            )

        raise ValueError(f"unknown tool: {tool_name}")

    def _ok(self, text: str) -> dict[str, Any]:
        return {
            "success": True,
            "contentItems": [_text_item(text)],
        }

    def _scene_summary(self) -> str:
        scene = bpy.context.scene
        selected = list(bpy.context.selected_objects)
        objects = []
        for obj in scene.objects[:100]:
            objects.append(
                {
                    "name": obj.name,
                    "type": obj.type,
                    "location": [round(v, 4) for v in obj.location],
                    "rotation_mode": obj.rotation_mode,
                    "scale": [round(v, 4) for v in obj.scale],
                }
            )

        payload = {
            "scene_name": scene.name,
            "frame_current": scene.frame_current,
            "frame_start": scene.frame_start,
            "frame_end": scene.frame_end,
            "object_count": len(scene.objects),
            "selected_objects": [obj.name for obj in selected],
            "active_object": bpy.context.object.name if bpy.context.object else None,
            "collections": [collection.name for collection in bpy.data.collections[:100]],
            "text_blocks": [text.name for text in bpy.data.texts[:100]],
            "objects": objects,
        }
        return json.dumps(payload, indent=2)

    def _read_text_block(self, name: str) -> str:
        text_block = bpy.data.texts.get(name)
        if text_block is None:
            raise ValueError(f"text block not found: {name}")
        return text_block.as_string()

    def _write_text_block(self, name: str, content: str) -> str:
        text_block = bpy.data.texts.get(name)
        if text_block is None:
            text_block = bpy.data.texts.new(name)
        text_block.clear()
        text_block.write(content)
        return f"Updated text block {name} with {len(content)} characters."

    def _run_python(self, *, code: str, return_variable: str | None) -> dict[str, Any]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        namespace: dict[str, Any] = {
            "__name__": "__codex_blender__",
            "bpy": bpy,
            "context": bpy.context,
            "data": bpy.data,
            "ops": bpy.ops,
            "scene": bpy.context.scene,
        }

        try:
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                exec(code, namespace, namespace)
            result_lines = []
            captured_stdout = stdout.getvalue().strip()
            captured_stderr = stderr.getvalue().strip()

            if return_variable:
                result_value = namespace.get(return_variable, None)
                result_lines.append(f"{return_variable} = {repr(result_value)}")

            if captured_stdout:
                result_lines.append("stdout:")
                result_lines.append(captured_stdout)

            if captured_stderr:
                result_lines.append("stderr:")
                result_lines.append(captured_stderr)

            if not result_lines:
                result_lines.append("Python executed successfully with no output.")

            return {
                "success": True,
                "contentItems": [_text_item("\n".join(result_lines))],
            }
        except Exception:
            trace = traceback.format_exc()
            return {
                "success": False,
                "contentItems": [_text_item(trace)],
            }
