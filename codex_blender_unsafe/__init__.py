from __future__ import annotations

import textwrap
try:
    import bpy  # type: ignore
except ModuleNotFoundError:  # pragma: no cover - expected outside Blender
    bpy = None

from .app_server import CodexAppServerClient, default_workspace


bl_info = {
    "name": "Codex Blender Unsafe",
    "author": "OpenAI Codex",
    "version": (0, 1, 0),
    "blender": (3, 0, 0),
    "location": "View3D > Sidebar > Codex Unsafe",
    "description": "Unsafe live Codex App Server integration for Blender 3.0",
    "category": "3D View",
}


_BRIDGE: CodexAppServerClient | None = None


def _workspace_default() -> str:
    return default_workspace()


if bpy is None:
    def register():
        raise RuntimeError("This module must be loaded inside Blender.")


    def unregister():
        return None

else:
    from .toolhost import BlenderToolHost

    def _get_bridge() -> CodexAppServerClient:
        global _BRIDGE
        if _BRIDGE is None:
            wm = bpy.context.window_manager
            _BRIDGE = CodexAppServerClient(
                cwd=wm.codex_unsafe_cwd or _workspace_default(),
                model=wm.codex_unsafe_model or "gpt-5.4",
            )
        return _BRIDGE


    def _reset_bridge() -> None:
        global _BRIDGE
        if _BRIDGE is not None:
            _BRIDGE.stop()
        _BRIDGE = None


    def _ensure_timer() -> None:
        if not bpy.app.timers.is_registered(_pump_bridge):
            bpy.app.timers.register(_pump_bridge, first_interval=0.2)


    def _pump_bridge() -> float | None:
        bridge = _BRIDGE
        if bridge is None:
            return 0.5

        try:
            bridge.poll(BlenderToolHost().dispatch)
            _sync_window_manager_state(bridge)
        except Exception as exc:
            bpy.context.window_manager.codex_unsafe_status = f"error: {exc}"

        return 0.2


    def _sync_window_manager_state(bridge: CodexAppServerClient) -> None:
        wm = bpy.context.window_manager
        wm.codex_unsafe_status = bridge.get_status()
        wm.codex_unsafe_output = bridge.get_assistant_text()
        wm.codex_unsafe_event_log = "\n".join(bridge.get_events()[-20:])


    class CODEX_OT_unsafe_connect(bpy.types.Operator):
        bl_idname = "codex_unsafe.connect"
        bl_label = "Connect"

        def execute(self, context: bpy.types.Context):
            bridge = _get_bridge()
            bridge.set_cwd(context.window_manager.codex_unsafe_cwd or _workspace_default())
            bridge.set_model(context.window_manager.codex_unsafe_model or "gpt-5.4")
            try:
                bridge.start()
            except Exception as exc:
                self.report({"ERROR"}, str(exc))
                context.window_manager.codex_unsafe_status = f"error: {exc}"
                return {"CANCELLED"}

            _ensure_timer()
            _sync_window_manager_state(bridge)
            return {"FINISHED"}


    class CODEX_OT_unsafe_disconnect(bpy.types.Operator):
        bl_idname = "codex_unsafe.disconnect"
        bl_label = "Disconnect"

        def execute(self, context: bpy.types.Context):
            _reset_bridge()
            context.window_manager.codex_unsafe_status = "disconnected"
            return {"FINISHED"}


    class CODEX_OT_unsafe_send_prompt(bpy.types.Operator):
        bl_idname = "codex_unsafe.send_prompt"
        bl_label = "Send Prompt"

        def execute(self, context: bpy.types.Context):
            bridge = _get_bridge()
            prompt = context.window_manager.codex_unsafe_prompt
            bridge.set_cwd(context.window_manager.codex_unsafe_cwd or _workspace_default())
            bridge.set_model(context.window_manager.codex_unsafe_model or "gpt-5.4")
            try:
                if not bridge.is_running:
                    bridge.start()
                bridge.send_prompt(prompt)
            except Exception as exc:
                self.report({"ERROR"}, str(exc))
                context.window_manager.codex_unsafe_status = f"error: {exc}"
                return {"CANCELLED"}

            _ensure_timer()
            _sync_window_manager_state(bridge)
            return {"FINISHED"}


    class CODEX_OT_unsafe_interrupt(bpy.types.Operator):
        bl_idname = "codex_unsafe.interrupt"
        bl_label = "Interrupt"

        def execute(self, context: bpy.types.Context):
            bridge = _get_bridge()
            try:
                bridge.interrupt()
            except Exception as exc:
                self.report({"ERROR"}, str(exc))
                return {"CANCELLED"}
            return {"FINISHED"}


    class CODEX_OT_unsafe_clear_output(bpy.types.Operator):
        bl_idname = "codex_unsafe.clear_output"
        bl_label = "Clear Output"

        def execute(self, context: bpy.types.Context):
            context.window_manager.codex_unsafe_output = ""
            context.window_manager.codex_unsafe_event_log = ""
            return {"FINISHED"}


    class VIEW3D_PT_codex_unsafe(bpy.types.Panel):
        bl_label = "Codex Unsafe"
        bl_idname = "VIEW3D_PT_codex_unsafe"
        bl_space_type = "VIEW_3D"
        bl_region_type = "UI"
        bl_category = "Codex Unsafe"

        def draw(self, context: bpy.types.Context):
            layout = self.layout
            wm = context.window_manager
            bridge = _BRIDGE

            col = layout.column(align=True)
            col.prop(wm, "codex_unsafe_model")
            col.prop(wm, "codex_unsafe_cwd")

            row = layout.row(align=True)
            row.operator("codex_unsafe.connect", text="Connect")
            row.operator("codex_unsafe.disconnect", text="Disconnect")

            row = layout.row(align=True)
            row.operator("codex_unsafe.send_prompt", text="Send Prompt")
            row.operator("codex_unsafe.interrupt", text="Interrupt")

            layout.operator("codex_unsafe.clear_output", text="Clear Output")

            layout.label(text=f"Status: {wm.codex_unsafe_status}")
            if bridge and bridge.thread_id:
                layout.label(text=f"Thread: {bridge.thread_id}")

            layout.prop(wm, "codex_unsafe_prompt", text="Prompt")

            self._draw_text_block(layout, "Assistant", wm.codex_unsafe_output)
            self._draw_text_block(layout, "Event Log", wm.codex_unsafe_event_log)

        def _draw_text_block(self, layout: bpy.types.UILayout, title: str, text: str):
            box = layout.box()
            box.label(text=title)
            if not text:
                box.label(text="(empty)")
                return
            for raw_line in text.splitlines()[:24]:
                for wrapped in textwrap.wrap(raw_line, width=72) or [""]:
                    box.label(text=wrapped[:120])


    classes = (
        CODEX_OT_unsafe_connect,
        CODEX_OT_unsafe_disconnect,
        CODEX_OT_unsafe_send_prompt,
        CODEX_OT_unsafe_interrupt,
        CODEX_OT_unsafe_clear_output,
        VIEW3D_PT_codex_unsafe,
    )


    def register():
        for cls in classes:
            bpy.utils.register_class(cls)

        bpy.types.WindowManager.codex_unsafe_prompt = bpy.props.StringProperty(
            name="Prompt",
            description="Prompt sent to Codex",
            default="Inspect the current scene and explain what you can change.",
        )
        bpy.types.WindowManager.codex_unsafe_model = bpy.props.StringProperty(
            name="Model",
            default="gpt-5.4",
        )
        bpy.types.WindowManager.codex_unsafe_cwd = bpy.props.StringProperty(
            name="Workspace",
            default=_workspace_default(),
            subtype="DIR_PATH",
        )
        bpy.types.WindowManager.codex_unsafe_status = bpy.props.StringProperty(
            name="Status",
            default="disconnected",
        )
        bpy.types.WindowManager.codex_unsafe_output = bpy.props.StringProperty(
            name="Assistant Output",
            default="",
        )
        bpy.types.WindowManager.codex_unsafe_event_log = bpy.props.StringProperty(
            name="Event Log",
            default="",
        )

        _ensure_timer()


    def unregister():
        if bpy.app.timers.is_registered(_pump_bridge):
            bpy.app.timers.unregister(_pump_bridge)

        _reset_bridge()

        del bpy.types.WindowManager.codex_unsafe_event_log
        del bpy.types.WindowManager.codex_unsafe_output
        del bpy.types.WindowManager.codex_unsafe_status
        del bpy.types.WindowManager.codex_unsafe_cwd
        del bpy.types.WindowManager.codex_unsafe_model
        del bpy.types.WindowManager.codex_unsafe_prompt

        for cls in reversed(classes):
            bpy.utils.unregister_class(cls)
