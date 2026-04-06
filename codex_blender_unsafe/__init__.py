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
    "version": (0, 3, 0),
    "blender": (3, 0, 0),
    "location": "View3D > Sidebar > Codex Unsafe",
    "description": "Unsafe live Codex App Server integration for Blender 3.0",
    "category": "3D View",
}


_BRIDGE: CodexAppServerClient | None = None
_DEFAULT_PROMPT_TEXT_NAME = "Codex Prompt"
_DEFAULT_PROMPT_TEXT = (
    "Inspect the current scene and explain what you can change.\n"
    "Prefer the structured Blender tools before blender_run_python."
)


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


    def _ensure_prompt_text_block(wm: bpy.types.WindowManager) -> bpy.types.Text:
        name = wm.codex_unsafe_prompt_text_name or _DEFAULT_PROMPT_TEXT_NAME
        text_block = bpy.data.texts.get(name)
        if text_block is None:
            text_block = bpy.data.texts.new(name)
            text_block.write(_DEFAULT_PROMPT_TEXT)
        elif not text_block.as_string().strip():
            text_block.write(_DEFAULT_PROMPT_TEXT)
        wm.codex_unsafe_prompt_text_name = text_block.name
        return text_block


    def _prompt_text(wm: bpy.types.WindowManager) -> str:
        text_block = bpy.data.texts.get(wm.codex_unsafe_prompt_text_name)
        return text_block.as_string() if text_block is not None else ""


    def _message_summary(body: str) -> str:
        first_line = (body or "").strip().splitlines()[0] if (body or "").strip() else ""
        if not first_line:
            return "(empty)"
        if len(first_line) > 72:
            return first_line[:69] + "..."
        return first_line


    def _message_icon(role: str, kind: str) -> str:
        if kind == "tool":
            return "TOOL_SETTINGS"
        if role == "user":
            return "USER"
        if role == "assistant":
            return "CONSOLE"
        return "INFO"


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
        wm.codex_unsafe_event_log = "\n".join(bridge.get_events()[-40:])

        ui_items = bridge.get_ui_items()
        wm.codex_unsafe_messages.clear()
        for data in ui_items:
            item = wm.codex_unsafe_messages.add()
            item.message_id = data.get("id", "")
            item.role = data.get("role", "")
            item.kind = data.get("kind", "")
            item.title = data.get("title", "")
            item.body = data.get("body", "")
            item.status = data.get("status", "")
            item.summary = _message_summary(item.body or item.title)

        if wm.codex_unsafe_messages:
            wm.codex_unsafe_message_index = min(
                max(wm.codex_unsafe_message_index, 0),
                len(wm.codex_unsafe_messages) - 1,
            )
        else:
            wm.codex_unsafe_message_index = 0


    def _draw_wrapped_text(layout: bpy.types.UILayout, text: str, width: int = 72, limit: int = 32) -> None:
        lines_drawn = 0
        if not text:
            layout.label(text="(empty)")
            return
        for raw_line in text.splitlines() or [""]:
            wrapped = textwrap.wrap(raw_line, width=width) or [""]
            for line in wrapped:
                layout.label(text=line[:160])
                lines_drawn += 1
                if lines_drawn >= limit:
                    layout.label(text="...")
                    return


    class CODEX_PG_message(bpy.types.PropertyGroup):
        message_id: bpy.props.StringProperty(name="Message Id")
        role: bpy.props.StringProperty(name="Role")
        kind: bpy.props.StringProperty(name="Kind")
        title: bpy.props.StringProperty(name="Title")
        summary: bpy.props.StringProperty(name="Summary")
        body: bpy.props.StringProperty(name="Body")
        status: bpy.props.StringProperty(name="Status")


    class CODEX_UL_messages(bpy.types.UIList):
        bl_idname = "CODEX_UL_messages"

        def draw_item(
            self,
            context: bpy.types.Context,
            layout: bpy.types.UILayout,
            data: bpy.types.WindowManager,
            item: CODEX_PG_message,
            icon: int,
            active_data: bpy.types.WindowManager,
            active_propname: str,
            index: int,
        ) -> None:
            icon_name = _message_icon(item.role, item.kind)
            if self.layout_type in {"DEFAULT", "COMPACT"}:
                row = layout.row(align=True)
                row.label(text=item.title or item.role.title(), icon=icon_name)
                row.label(text=item.summary)
                if item.status:
                    row.label(text=item.status)
            elif self.layout_type == "GRID":
                layout.alignment = "CENTER"
                layout.label(text="", icon=icon_name)


    class CODEX_OT_unsafe_connect(bpy.types.Operator):
        bl_idname = "codex_unsafe.connect"
        bl_label = "Connect"

        def execute(self, context: bpy.types.Context):
            bridge = _get_bridge()
            wm = context.window_manager
            bridge.set_cwd(wm.codex_unsafe_cwd or _workspace_default())
            bridge.set_model(wm.codex_unsafe_model or "gpt-5.4")
            try:
                bridge.start()
            except Exception as exc:
                self.report({"ERROR"}, str(exc))
                wm.codex_unsafe_status = f"error: {exc}"
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
            context.window_manager.codex_unsafe_messages.clear()
            return {"FINISHED"}


    class CODEX_OT_unsafe_prepare_prompt_text(bpy.types.Operator):
        bl_idname = "codex_unsafe.prepare_prompt_text"
        bl_label = "Prepare Prompt Text"

        def execute(self, context: bpy.types.Context):
            text_block = _ensure_prompt_text_block(context.window_manager)
            self.report({"INFO"}, f"Prompt text ready: {text_block.name}")
            return {"FINISHED"}


    class CODEX_OT_unsafe_open_prompt_editor(bpy.types.Operator):
        bl_idname = "codex_unsafe.open_prompt_editor"
        bl_label = "Open Prompt Editor"

        def execute(self, context: bpy.types.Context):
            wm = context.window_manager
            text_block = _ensure_prompt_text_block(wm)
            before = {window.as_pointer() for window in wm.windows}

            try:
                override = {
                    "window": context.window,
                    "screen": context.screen,
                    "area": context.area,
                    "region": context.region,
                }
                bpy.ops.screen.area_dupli(override, "EXEC_DEFAULT")
            except Exception:
                self.report({"WARNING"}, "Could not create a detached prompt window")
                return {"CANCELLED"}

            new_window = None
            for window in wm.windows:
                if window.as_pointer() not in before:
                    new_window = window
                    break

            if new_window is None:
                self.report({"WARNING"}, "Prompt window did not open")
                return {"CANCELLED"}

            area = new_window.screen.areas[0]
            area.type = "TEXT_EDITOR"
            area.spaces.active.text = text_block
            if hasattr(area.spaces.active, "show_region_ui"):
                area.spaces.active.show_region_ui = True
            self.report({"INFO"}, f"Opened prompt editor for {text_block.name}")
            return {"FINISHED"}


    class CODEX_OT_unsafe_send_prompt(bpy.types.Operator):
        bl_idname = "codex_unsafe.send_prompt"
        bl_label = "Send Prompt"

        def execute(self, context: bpy.types.Context):
            bridge = _get_bridge()
            wm = context.window_manager
            text_block = _ensure_prompt_text_block(wm)
            prompt = text_block.as_string().strip()
            bridge.set_cwd(wm.codex_unsafe_cwd or _workspace_default())
            bridge.set_model(wm.codex_unsafe_model or "gpt-5.4")
            try:
                if not bridge.is_running:
                    bridge.start()
                bridge.send_prompt(prompt)
            except Exception as exc:
                self.report({"ERROR"}, str(exc))
                wm.codex_unsafe_status = f"error: {exc}"
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

            session = layout.box()
            session.label(text="Session", icon="PLUGIN")
            session.prop(wm, "codex_unsafe_model")
            session.prop(wm, "codex_unsafe_cwd")
            row = session.row(align=True)
            row.operator("codex_unsafe.connect", text="Connect")
            row.operator("codex_unsafe.disconnect", text="Disconnect")
            row.operator("codex_unsafe.interrupt", text="Interrupt")
            session.label(text=f"Status: {wm.codex_unsafe_status}")
            if bridge and bridge.thread_id:
                session.label(text=f"Thread: {bridge.thread_id}")

            prompt = layout.box()
            prompt.label(text="Prompt Editor", icon="TEXT")
            prompt.prop_search(wm, "codex_unsafe_prompt_text_name", bpy.data, "texts", text="Text")
            row = prompt.row(align=True)
            row.operator("codex_unsafe.prepare_prompt_text", text="Prepare")
            row.operator("codex_unsafe.open_prompt_editor", text="Open Window")
            row.operator("codex_unsafe.send_prompt", text="Send")
            prompt.label(text="Type your prompt in the Blender Text Editor window for the selected text block.")
            preview = prompt.box()
            preview.label(text="Composer Preview")
            _draw_wrapped_text(preview, _prompt_text(wm), width=72, limit=10)

            transcript = layout.box()
            transcript.label(text="Conversation", icon="WORDWRAP_ON")
            transcript.template_list(
                "CODEX_UL_messages",
                "",
                wm,
                "codex_unsafe_messages",
                wm,
                "codex_unsafe_message_index",
                rows=8,
            )
            if wm.codex_unsafe_messages:
                selected = wm.codex_unsafe_messages[wm.codex_unsafe_message_index]
                detail = transcript.box()
                detail.label(text=f"{selected.title} [{selected.status or 'idle'}]", icon=_message_icon(selected.role, selected.kind))
                _draw_wrapped_text(detail, selected.body, width=78, limit=20)
            else:
                transcript.label(text="No conversation yet.")

            activity = layout.box()
            activity.label(text="Activity", icon="INFO")
            _draw_wrapped_text(activity, wm.codex_unsafe_event_log, width=78, limit=14)


    class TEXTEDITOR_PT_codex_unsafe(bpy.types.Panel):
        bl_label = "Codex Prompt"
        bl_idname = "TEXTEDITOR_PT_codex_unsafe"
        bl_space_type = "TEXT_EDITOR"
        bl_region_type = "UI"
        bl_category = "Codex Unsafe"

        def draw(self, context: bpy.types.Context):
            layout = self.layout
            wm = context.window_manager
            text_block = _ensure_prompt_text_block(wm)
            text = context.space_data.text if context.space_data else None

            box = layout.box()
            box.label(text="Prompt Editor", icon="TEXT")
            box.prop_search(wm, "codex_unsafe_prompt_text_name", bpy.data, "texts", text="Prompt Text")
            if text and text.name == text_block.name:
                box.label(text=f"Editing: {text.name}")
            else:
                box.label(text=f"Active Prompt: {text_block.name}")
            row = box.row(align=True)
            row.operator("codex_unsafe.send_prompt", text="Send")
            row.operator("codex_unsafe.connect", text="Connect")
            box.label(text=f"Status: {wm.codex_unsafe_status}")
            if _BRIDGE and _BRIDGE.thread_id:
                box.label(text=f"Thread: {_BRIDGE.thread_id}")


    classes = (
        CODEX_PG_message,
        CODEX_UL_messages,
        CODEX_OT_unsafe_connect,
        CODEX_OT_unsafe_disconnect,
        CODEX_OT_unsafe_prepare_prompt_text,
        CODEX_OT_unsafe_open_prompt_editor,
        CODEX_OT_unsafe_send_prompt,
        CODEX_OT_unsafe_interrupt,
        VIEW3D_PT_codex_unsafe,
        TEXTEDITOR_PT_codex_unsafe,
    )


    def register():
        for cls in classes:
            bpy.utils.register_class(cls)

        bpy.types.WindowManager.codex_unsafe_model = bpy.props.StringProperty(
            name="Model",
            default="gpt-5.4",
        )
        bpy.types.WindowManager.codex_unsafe_cwd = bpy.props.StringProperty(
            name="Workspace",
            default=_workspace_default(),
            subtype="DIR_PATH",
        )
        bpy.types.WindowManager.codex_unsafe_prompt_text_name = bpy.props.StringProperty(
            name="Prompt Text",
            default=_DEFAULT_PROMPT_TEXT_NAME,
        )
        bpy.types.WindowManager.codex_unsafe_status = bpy.props.StringProperty(
            name="Status",
            default="disconnected",
        )
        bpy.types.WindowManager.codex_unsafe_event_log = bpy.props.StringProperty(
            name="Event Log",
            default="",
        )
        bpy.types.WindowManager.codex_unsafe_messages = bpy.props.CollectionProperty(
            type=CODEX_PG_message,
        )
        bpy.types.WindowManager.codex_unsafe_message_index = bpy.props.IntProperty(
            name="Conversation Index",
            default=0,
        )

        _ensure_timer()


    def unregister():
        if bpy.app.timers.is_registered(_pump_bridge):
            bpy.app.timers.unregister(_pump_bridge)

        _reset_bridge()

        del bpy.types.WindowManager.codex_unsafe_message_index
        del bpy.types.WindowManager.codex_unsafe_messages
        del bpy.types.WindowManager.codex_unsafe_event_log
        del bpy.types.WindowManager.codex_unsafe_status
        del bpy.types.WindowManager.codex_unsafe_prompt_text_name
        del bpy.types.WindowManager.codex_unsafe_cwd
        del bpy.types.WindowManager.codex_unsafe_model

        for cls in reversed(classes):
            bpy.utils.unregister_class(cls)
