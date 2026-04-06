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

        if tool_name == "blender_list_objects":
            return self._ok(self._list_objects(args.get("type"), args.get("selected_only", False)))

        if tool_name == "blender_get_object_info":
            return self._ok(self._get_object_info(args["name"]))

        if tool_name == "blender_select_objects":
            return self._ok(self._select_objects(args["names"], args.get("mode", "replace")))

        if tool_name == "blender_create_primitive":
            return self._ok(
                self._create_primitive(
                    primitive_type=args["primitive_type"],
                    name=args.get("name"),
                    location=args.get("location"),
                    rotation=args.get("rotation"),
                    scale=args.get("scale"),
                )
            )

        if tool_name == "blender_set_object_transform":
            return self._ok(
                self._set_object_transform(
                    name=args["name"],
                    location=args.get("location"),
                    rotation=args.get("rotation"),
                    scale=args.get("scale"),
                )
            )

        if tool_name == "blender_delete_objects":
            return self._ok(self._delete_objects(args["names"]))

        if tool_name == "blender_create_material":
            return self._ok(
                self._create_material(
                    name=args["name"],
                    base_color=args.get("base_color"),
                    metallic=args.get("metallic"),
                    roughness=args.get("roughness"),
                )
            )

        if tool_name == "blender_assign_material":
            return self._ok(
                self._assign_material(
                    object_name=args["object_name"],
                    material_name=args["material_name"],
                    slot_index=args.get("slot_index", 0),
                )
            )

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
        for obj in list(scene.objects)[:100]:
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

    def _list_objects(self, object_type: str | None, selected_only: bool) -> str:
        objects = bpy.context.selected_objects if selected_only else bpy.context.scene.objects
        payload = []
        requested_type = object_type.upper() if object_type else None
        for obj in objects:
            if requested_type and obj.type != requested_type:
                continue
            payload.append(
                {
                    "name": obj.name,
                    "type": obj.type,
                    "selected": bool(obj.select_get()),
                    "visible": bool(obj.visible_get()),
                    "location": [round(v, 4) for v in obj.location],
                }
            )
        return json.dumps(payload, indent=2)

    def _get_object_info(self, name: str) -> str:
        obj = self._require_object(name)
        payload = {
            "name": obj.name,
            "type": obj.type,
            "location": [round(v, 4) for v in obj.location],
            "rotation_euler": [round(v, 4) for v in obj.rotation_euler],
            "scale": [round(v, 4) for v in obj.scale],
            "dimensions": [round(v, 4) for v in obj.dimensions],
            "selected": bool(obj.select_get()),
            "visible": bool(obj.visible_get()),
            "material_slots": [
                slot.material.name if slot.material else None for slot in obj.material_slots
            ],
        }
        return json.dumps(payload, indent=2)

    def _select_objects(self, names: list[str], mode: str) -> str:
        valid_modes = {"replace", "add", "remove"}
        if mode not in valid_modes:
            raise ValueError(f"invalid selection mode: {mode}")

        if mode == "replace":
            for obj in bpy.context.scene.objects:
                obj.select_set(False)

        selected_names = []
        for name in names:
            obj = self._require_object(name)
            obj.select_set(mode != "remove")
            if mode != "remove":
                selected_names.append(obj.name)

        if selected_names:
            bpy.context.view_layer.objects.active = self._require_object(selected_names[-1])
        elif mode == "replace":
            bpy.context.view_layer.objects.active = None

        return json.dumps(
            {
                "mode": mode,
                "selected_objects": [obj.name for obj in bpy.context.selected_objects],
                "active_object": bpy.context.object.name if bpy.context.object else None,
            },
            indent=2,
        )

    def _create_primitive(
        self,
        *,
        primitive_type: str,
        name: str | None,
        location: list[float] | None,
        rotation: list[float] | None,
        scale: list[float] | None,
    ) -> str:
        primitive = primitive_type.lower()
        location_value = tuple(location or [0.0, 0.0, 0.0])
        rotation_value = tuple(rotation or [0.0, 0.0, 0.0])
        scale_value = tuple(scale or [1.0, 1.0, 1.0])
        creators = {
            "cube": bpy.ops.mesh.primitive_cube_add,
            "uv_sphere": bpy.ops.mesh.primitive_uv_sphere_add,
            "ico_sphere": bpy.ops.mesh.primitive_ico_sphere_add,
            "cylinder": bpy.ops.mesh.primitive_cylinder_add,
            "cone": bpy.ops.mesh.primitive_cone_add,
            "plane": bpy.ops.mesh.primitive_plane_add,
            "torus": bpy.ops.mesh.primitive_torus_add,
            "monkey": bpy.ops.mesh.primitive_monkey_add,
        }
        creator = creators.get(primitive)
        if creator is None:
            raise ValueError(f"unsupported primitive type: {primitive_type}")

        creator(location=location_value, rotation=rotation_value, scale=scale_value)
        obj = bpy.context.object
        if obj is None:
            raise RuntimeError("primitive creation did not produce an active object")
        if name:
            obj.name = name
            if obj.data:
                obj.data.name = f"{name}Mesh"
        return self._get_object_info(obj.name)

    def _set_object_transform(
        self,
        *,
        name: str,
        location: list[float] | None,
        rotation: list[float] | None,
        scale: list[float] | None,
    ) -> str:
        obj = self._require_object(name)
        if location is not None:
            obj.location = tuple(location)
        if rotation is not None:
            obj.rotation_mode = "XYZ"
            obj.rotation_euler = tuple(rotation)
        if scale is not None:
            obj.scale = tuple(scale)
        return self._get_object_info(obj.name)

    def _delete_objects(self, names: list[str]) -> str:
        deleted = []
        for name in names:
            obj = self._require_object(name)
            deleted.append(obj.name)
            bpy.data.objects.remove(obj, do_unlink=True)
        return json.dumps({"deleted": deleted}, indent=2)

    def _create_material(
        self,
        *,
        name: str,
        base_color: list[float] | None,
        metallic: float | None,
        roughness: float | None,
    ) -> str:
        material = bpy.data.materials.get(name)
        if material is None:
            material = bpy.data.materials.new(name=name)
        material.use_nodes = True
        principled = material.node_tree.nodes.get("Principled BSDF")
        if principled is None:
            raise RuntimeError("Principled BSDF node was not found")

        if base_color is not None:
            principled.inputs["Base Color"].default_value = tuple(base_color)
        if metallic is not None:
            principled.inputs["Metallic"].default_value = float(metallic)
        if roughness is not None:
            principled.inputs["Roughness"].default_value = float(roughness)

        payload = {
            "name": material.name,
            "base_color": list(principled.inputs["Base Color"].default_value),
            "metallic": float(principled.inputs["Metallic"].default_value),
            "roughness": float(principled.inputs["Roughness"].default_value),
        }
        return json.dumps(payload, indent=2)

    def _assign_material(self, *, object_name: str, material_name: str, slot_index: int) -> str:
        obj = self._require_object(object_name)
        material = bpy.data.materials.get(material_name)
        if material is None:
            raise ValueError(f"material not found: {material_name}")

        while len(obj.material_slots) <= slot_index:
            obj.data.materials.append(None)
        obj.material_slots[slot_index].material = material
        return self._get_object_info(obj.name)

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

    def _require_object(self, name: str):
        obj = bpy.data.objects.get(name)
        if obj is None:
            raise ValueError(f"object not found: {name}")
        return obj

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
