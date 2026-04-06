from __future__ import annotations

import json
import os
import queue
import subprocess
import threading
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional


DEFAULT_MODEL = "gpt-5.4"
DEFAULT_PERSONALITY = "pragmatic"


@dataclass
class _PendingCall:
    event: threading.Event
    response: Optional[dict[str, Any]] = None


@dataclass
class QueuedToolCall:
    request_id: Any
    tool: str
    arguments: Any
    thread_id: str
    turn_id: str
    call_id: str


class CodexProtocolError(RuntimeError):
    pass


class CodexAppServerClient:
    def __init__(
        self,
        *,
        codex_command: str = "codex",
        cwd: Optional[str] = None,
        model: str = DEFAULT_MODEL,
    ) -> None:
        self.codex_command = codex_command
        self.cwd = os.path.abspath(cwd or os.getcwd())
        self.model = model

        self._process: Optional[subprocess.Popen[str]] = None
        self._reader_thread: Optional[threading.Thread] = None
        self._pending: dict[Any, _PendingCall] = {}
        self._pending_lock = threading.Lock()
        self._write_lock = threading.Lock()
        self._id_lock = threading.Lock()
        self._next_id = 1
        self._tool_queue: "queue.Queue[QueuedToolCall]" = queue.Queue()
        self._events: deque[str] = deque(maxlen=200)
        self._assistant_text = ""
        self._status = "disconnected"
        self._thread_id: Optional[str] = None
        self._active_turn_id: Optional[str] = None
        self._stop_event = threading.Event()

    @property
    def thread_id(self) -> Optional[str]:
        return self._thread_id

    @property
    def is_running(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def get_status(self) -> str:
        return self._status

    def get_assistant_text(self) -> str:
        return self._assistant_text

    def get_events(self) -> list[str]:
        return list(self._events)

    def set_cwd(self, cwd: str) -> None:
        self.cwd = os.path.abspath(cwd)

    def set_model(self, model: str) -> None:
        self.model = model or DEFAULT_MODEL

    def start(self) -> None:
        if self.is_running:
            return

        self._stop_event.clear()
        self._assistant_text = ""
        self._thread_id = None
        self._active_turn_id = None
        self._status = "starting"
        self._log("starting codex app-server")

        self._process = subprocess.Popen(
            [self.codex_command, "app-server"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            cwd=self.cwd,
        )

        self._reader_thread = threading.Thread(target=self._reader_loop, daemon=True)
        self._reader_thread.start()

        self._request(
            "initialize",
            {
                "clientInfo": {
                    "name": "blender_codex_unsafe",
                    "title": "Blender Codex Unsafe",
                    "version": "0.1.0",
                },
                "capabilities": {
                    "experimentalApi": True,
                },
            },
        )
        self._notify("initialized")

        result = self._request(
            "thread/start",
            {
                "model": self.model,
                "cwd": self.cwd,
                "approvalPolicy": "never",
                "sandbox": "danger-full-access",
                "personality": DEFAULT_PERSONALITY,
                "developerInstructions": self._developer_instructions(),
                "experimentalRawEvents": False,
                "persistExtendedHistory": False,
                "dynamicTools": self._dynamic_tools(),
            },
        )
        self._thread_id = result["thread"]["id"]
        self._status = "connected"
        self._log(f"connected thread {self._thread_id}")

    def stop(self) -> None:
        self._stop_event.set()
        self._status = "stopping"
        proc = self._process
        self._process = None
        if proc is None:
            self._status = "disconnected"
            return

        try:
            if proc.stdin:
                proc.stdin.close()
        except OSError:
            pass

        try:
            proc.terminate()
            proc.wait(timeout=2)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass

        self._status = "disconnected"
        self._log("stopped")

    def send_prompt(self, text: str) -> None:
        prompt = (text or "").strip()
        if not prompt:
            raise ValueError("prompt is empty")
        if not self.is_running or not self._thread_id:
            raise RuntimeError("codex app-server is not connected")

        self._assistant_text = ""
        self._status = "running"
        result = self._request(
            "turn/start",
            {
                "threadId": self._thread_id,
                "approvalPolicy": "never",
                "model": self.model,
                "cwd": self.cwd,
                "input": [
                    {
                        "type": "text",
                        "text": prompt,
                    }
                ],
            },
        )
        self._active_turn_id = result["turn"]["id"]
        self._log(f"turn started {self._active_turn_id}")

    def interrupt(self) -> None:
        if not self._thread_id or not self._active_turn_id:
            return
        self._request(
            "turn/interrupt",
            {
                "threadId": self._thread_id,
                "turnId": self._active_turn_id,
            },
        )
        self._log("interrupt requested")

    def poll(self, tool_runner: Callable[[str, Any], dict[str, Any]], limit: int = 4) -> int:
        processed = 0
        while processed < limit:
            try:
                pending = self._tool_queue.get_nowait()
            except queue.Empty:
                break

            processed += 1
            try:
                result = tool_runner(pending.tool, pending.arguments)
                payload = {
                    "contentItems": result.get("contentItems", []),
                    "success": bool(result.get("success", True)),
                }
            except Exception as exc:
                payload = {
                    "success": False,
                    "contentItems": [
                        {
                            "type": "inputText",
                            "text": f"Tool execution failed: {exc}",
                        }
                    ],
                }
            self._send_response(pending.request_id, payload)

        return processed

    def _reader_loop(self) -> None:
        assert self._process is not None
        assert self._process.stdout is not None
        assert self._process.stderr is not None

        stderr_thread = threading.Thread(target=self._stderr_loop, daemon=True)
        stderr_thread.start()

        try:
            for raw_line in self._process.stdout:
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    message = json.loads(line)
                except json.JSONDecodeError as exc:
                    self._log(f"bad json from app-server: {exc}")
                    continue
                self._handle_message(message)
        finally:
            if not self._stop_event.is_set():
                self._status = "disconnected"
                self._log("app-server stream closed")

    def _stderr_loop(self) -> None:
        assert self._process is not None
        assert self._process.stderr is not None
        for raw_line in self._process.stderr:
            line = raw_line.strip()
            if line:
                self._log(f"stderr: {line}")

    def _handle_message(self, message: dict[str, Any]) -> None:
        if "id" in message and "method" not in message:
            self._resolve_pending(message)
            return

        if "id" in message and "method" in message:
            self._handle_server_request(message)
            return

        self._handle_notification(message)

    def _resolve_pending(self, message: dict[str, Any]) -> None:
        request_id = message.get("id")
        with self._pending_lock:
            pending = self._pending.pop(request_id, None)
        if pending is None:
            self._log(f"orphan response for id {request_id}")
            return
        pending.response = message
        pending.event.set()

    def _handle_server_request(self, message: dict[str, Any]) -> None:
        method = message["method"]
        request_id = message["id"]
        params = message.get("params", {})

        if method == "item/tool/call":
            queued = QueuedToolCall(
                request_id=request_id,
                tool=params["tool"],
                arguments=params.get("arguments"),
                thread_id=params["threadId"],
                turn_id=params["turnId"],
                call_id=params["callId"],
            )
            self._log(f"tool call {queued.tool}")
            self._tool_queue.put(queued)
            return

        if method == "item/commandExecution/requestApproval":
            self._send_response(request_id, {"decision": "acceptForSession"})
            self._log("auto-approved command execution")
            return

        if method == "item/fileChange/requestApproval":
            self._send_response(request_id, {"decision": "acceptForSession"})
            self._log("auto-approved file change")
            return

        if method == "item/permissions/requestApproval":
            self._send_response(
                request_id,
                {
                    "permissions": params.get("permissions", {}),
                    "scope": "session",
                },
            )
            self._log("auto-approved permissions request")
            return

        if method == "item/tool/requestUserInput":
            self._send_error(
                request_id,
                code=-32000,
                message="requestUserInput is unsupported in unsafe blender mode",
            )
            self._log("rejected requestUserInput")
            return

        self._send_error(
            request_id,
            code=-32601,
            message=f"Unsupported server request method: {method}",
        )
        self._log(f"unsupported server request {method}")

    def _handle_notification(self, message: dict[str, Any]) -> None:
        method = message.get("method")
        params = message.get("params", {})

        if method == "turn/started":
            turn = params.get("turn", {})
            self._active_turn_id = turn.get("id")
            self._assistant_text = ""
            self._status = "running"
            self._log(f"turn started {self._active_turn_id}")
            return

        if method == "turn/completed":
            turn = params.get("turn", {})
            self._active_turn_id = turn.get("id")
            self._status = turn.get("status", "connected")
            self._log(f"turn completed with status {self._status}")
            return

        if method == "item/agentMessage/delta":
            delta = params.get("delta", "")
            self._assistant_text += delta
            return

        if method == "item/completed":
            item = params.get("item", {})
            if item.get("type") == "agentMessage":
                self._assistant_text = item.get("text", self._assistant_text)
            return

        if method == "error":
            error = params.get("error", {})
            self._status = "error"
            self._log(f"error: {error.get('message', 'unknown error')}")
            return

        if method == "serverRequest/resolved":
            return

        if method == "thread/started":
            thread = params.get("thread", {})
            if thread.get("id"):
                self._thread_id = thread["id"]
            return

        if method == "item/commandExecution/outputDelta":
            delta = params.get("delta", "")
            if delta:
                self._log(delta.rstrip())
            return

        if method == "item/reasoning/textDelta":
            return

        if method == "item/started":
            item = params.get("item", {})
            item_type = item.get("type")
            if item_type in {"dynamicToolCall", "commandExecution", "fileChange"}:
                self._log(f"{item_type} started")
            return

        # Keep the log useful without spamming every event.
        if method not in {"thread/status/changed", "thread/tokenUsage/updated"}:
            self._log(f"notification: {method}")

    def _request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        request_id = self._allocate_id()
        pending = _PendingCall(event=threading.Event())
        with self._pending_lock:
            self._pending[request_id] = pending
        self._write_json({"id": request_id, "method": method, "params": params})
        if not pending.event.wait(timeout=60):
            with self._pending_lock:
                self._pending.pop(request_id, None)
            raise TimeoutError(f"timed out waiting for {method}")
        assert pending.response is not None
        if "error" in pending.response:
            raise CodexProtocolError(f"{method} failed: {pending.response['error']}")
        return pending.response["result"]

    def _notify(self, method: str, params: Optional[dict[str, Any]] = None) -> None:
        payload: dict[str, Any] = {"method": method}
        if params:
            payload["params"] = params
        self._write_json(payload)

    def _send_response(self, request_id: Any, result: dict[str, Any]) -> None:
        self._write_json({"id": request_id, "result": result})

    def _send_error(self, request_id: Any, *, code: int, message: str) -> None:
        self._write_json({"id": request_id, "error": {"code": code, "message": message}})

    def _write_json(self, payload: dict[str, Any]) -> None:
        proc = self._process
        if proc is None or proc.stdin is None:
            raise RuntimeError("app-server process is not available")
        encoded = json.dumps(payload, separators=(",", ":"))
        with self._write_lock:
            proc.stdin.write(encoded + "\n")
            proc.stdin.flush()

    def _allocate_id(self) -> int:
        with self._id_lock:
            value = self._next_id
            self._next_id += 1
            return value

    def _log(self, message: str) -> None:
        stamp = time.strftime("%H:%M:%S")
        self._events.append(f"[{stamp}] {message}")

    def _dynamic_tools(self) -> list[dict[str, Any]]:
        return [
            {
                "name": "blender_get_scene_summary",
                "description": "Inspect the current Blender scene and return objects, selection, frame range, collections, and text blocks.",
                "inputSchema": {
                    "type": "object",
                    "properties": {},
                    "additionalProperties": False,
                },
            },
            {
                "name": "blender_list_objects",
                "description": "List objects in the current scene, optionally filtered by object type or current selection.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "type": {"type": "string"},
                        "selected_only": {"type": "boolean"},
                    },
                    "additionalProperties": False,
                },
            },
            {
                "name": "blender_get_object_info",
                "description": "Return detailed information for a single Blender object by name.",
                "inputSchema": {
                    "type": "object",
                    "required": ["name"],
                    "properties": {
                        "name": {"type": "string"},
                    },
                    "additionalProperties": False,
                },
            },
            {
                "name": "blender_select_objects",
                "description": "Select, add-select, or deselect Blender objects by name.",
                "inputSchema": {
                    "type": "object",
                    "required": ["names"],
                    "properties": {
                        "names": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                        "mode": {
                            "type": "string",
                            "enum": ["replace", "add", "remove"],
                        },
                    },
                    "additionalProperties": False,
                },
            },
            {
                "name": "blender_create_primitive",
                "description": "Create a primitive mesh object such as a cube, sphere, plane, cylinder, cone, torus, or monkey.",
                "inputSchema": {
                    "type": "object",
                    "required": ["primitive_type"],
                    "properties": {
                        "primitive_type": {
                            "type": "string",
                            "enum": ["cube", "uv_sphere", "ico_sphere", "cylinder", "cone", "plane", "torus", "monkey"],
                        },
                        "name": {"type": "string"},
                        "location": {
                            "type": "array",
                            "minItems": 3,
                            "maxItems": 3,
                            "items": {"type": "number"},
                        },
                        "rotation": {
                            "type": "array",
                            "minItems": 3,
                            "maxItems": 3,
                            "items": {"type": "number"},
                        },
                        "scale": {
                            "type": "array",
                            "minItems": 3,
                            "maxItems": 3,
                            "items": {"type": "number"},
                        },
                    },
                    "additionalProperties": False,
                },
            },
            {
                "name": "blender_set_object_transform",
                "description": "Set location, Euler rotation, and or scale for an existing object.",
                "inputSchema": {
                    "type": "object",
                    "required": ["name"],
                    "properties": {
                        "name": {"type": "string"},
                        "location": {
                            "type": "array",
                            "minItems": 3,
                            "maxItems": 3,
                            "items": {"type": "number"},
                        },
                        "rotation": {
                            "type": "array",
                            "minItems": 3,
                            "maxItems": 3,
                            "items": {"type": "number"},
                        },
                        "scale": {
                            "type": "array",
                            "minItems": 3,
                            "maxItems": 3,
                            "items": {"type": "number"},
                        },
                    },
                    "additionalProperties": False,
                },
            },
            {
                "name": "blender_delete_objects",
                "description": "Delete one or more objects by name from the current Blender file.",
                "inputSchema": {
                    "type": "object",
                    "required": ["names"],
                    "properties": {
                        "names": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                    },
                    "additionalProperties": False,
                },
            },
            {
                "name": "blender_create_material",
                "description": "Create or update a material and optionally set Principled BSDF base color, metallic, and roughness.",
                "inputSchema": {
                    "type": "object",
                    "required": ["name"],
                    "properties": {
                        "name": {"type": "string"},
                        "base_color": {
                            "type": "array",
                            "minItems": 4,
                            "maxItems": 4,
                            "items": {"type": "number"},
                        },
                        "metallic": {"type": "number"},
                        "roughness": {"type": "number"},
                    },
                    "additionalProperties": False,
                },
            },
            {
                "name": "blender_assign_material",
                "description": "Assign an existing material to an object material slot.",
                "inputSchema": {
                    "type": "object",
                    "required": ["object_name", "material_name"],
                    "properties": {
                        "object_name": {"type": "string"},
                        "material_name": {"type": "string"},
                        "slot_index": {"type": "integer", "minimum": 0},
                    },
                    "additionalProperties": False,
                },
            },
            {
                "name": "blender_read_text_block",
                "description": "Read a Blender text datablock by name.",
                "inputSchema": {
                    "type": "object",
                    "required": ["name"],
                    "properties": {
                        "name": {"type": "string"},
                    },
                    "additionalProperties": False,
                },
            },
            {
                "name": "blender_write_text_block",
                "description": "Create or replace a Blender text datablock with the provided content.",
                "inputSchema": {
                    "type": "object",
                    "required": ["name", "content"],
                    "properties": {
                        "name": {"type": "string"},
                        "content": {"type": "string"},
                    },
                    "additionalProperties": False,
                },
            },
            {
                "name": "blender_run_python",
                "description": "Execute arbitrary Blender Python in the live session with full bpy access. Unsafe and mutating by design.",
                "inputSchema": {
                    "type": "object",
                    "required": ["code"],
                    "properties": {
                        "code": {"type": "string"},
                        "return_variable": {"type": "string"},
                    },
                    "additionalProperties": False,
                },
            },
        ]

    def _developer_instructions(self) -> str:
        return (
            "You are operating inside Blender 3.0 through a custom rich client. "
            "Use the available dynamic Blender tools aggressively when the user asks "
            "for scene changes or Blender scripting help. "
            "Unsafe mode is enabled: approval policy is never, sandbox is danger-full-access, "
            "and blender_run_python executes arbitrary Python against the live Blender process. "
            "Prefer structured tools such as blender_create_primitive, blender_set_object_transform, "
            "blender_create_material, blender_assign_material, blender_get_object_info, and "
            "blender_select_objects for normal scene operations. "
            "Prefer blender_get_scene_summary before destructive changes unless the user's intent is already precise. "
            "Use blender_run_python only when the structured tools cannot express the requested operation."
        )


def default_workspace() -> str:
    return str(Path(__file__).resolve().parent.parent)
