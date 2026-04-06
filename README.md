# Codex Blender App Server

An experimental Blender 3.0 add-on that connects Blender to `codex app-server` and exposes an unsafe live-execution tool surface.

This is intentionally high trust:

- Codex runs with `approvalPolicy: "never"`.
- The thread runs with `sandbox: "danger-full-access"`.
- The add-on exposes `blender.run_python`, which executes arbitrary Python against the live Blender process.

Do not install this in an environment you do not control.

## What it does

- Starts `codex app-server` as a subprocess over `stdio`.
- Opens a Codex thread configured for Blender work.
- Exposes dynamic Blender tools to Codex.
- Lets Codex inspect and mutate the open scene directly.
- Streams assistant output back into a Blender sidebar panel.

## Current tool surface

- `blender_get_scene_summary`
- `blender_read_text_block`
- `blender_write_text_block`
- `blender_run_python`

`blender_run_python` is the escape hatch. It can do anything Blender's Python API can do.

## Project layout

- `codex_blender_unsafe/__init__.py`
  Blender add-on entrypoint, operators, panel, timer pump.
- `codex_blender_unsafe/app_server.py`
  App Server JSON-RPC bridge and event handling.
- `codex_blender_unsafe/toolhost.py`
  Main-thread Blender tool execution.
- `scripts/smoke_test_protocol.py`
  Minimal local bridge smoke test outside Blender.

## Blender install

1. Zip the `codex_blender_unsafe` directory, or copy it into your Blender add-ons directory.
2. In Blender 3.0, open `Edit > Preferences > Add-ons > Install...`.
3. Enable `Codex Blender Unsafe`.
4. Open the `View3D` sidebar, then the `Codex Unsafe` tab.
5. Click `Connect`.

## Runtime requirements

- `codex` must be on `PATH`.
- You must already be authenticated with Codex locally.
- Blender's Python must be able to launch subprocesses.

## Unsafe behavior

The add-on deliberately auto-accepts approvals and gives Codex a direct code execution tool. That is the requested behavior for this prototype.

If you want the safer version later, the first thing to change is:

- remove `approvalPolicy: "never"`
- remove `sandbox: "danger-full-access"`
- stop auto-accepting approval requests
- disable `blender.run_python` or gate it behind a user approval step

## Local verification

Outside Blender:

```bash
python3 -m py_compile codex_blender_unsafe/*.py scripts/smoke_test_protocol.py
python3 scripts/smoke_test_protocol.py --help
```

Inside Blender:

- Enable the add-on.
- Connect.
- Prompt: `Create a cube, shade it smooth, and tell me what changed.`
