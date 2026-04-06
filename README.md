# Codex Blender App Server

Blender 3.0 add-on that connects Blender to `codex app-server` and gives Codex a live tool surface for scene inspection, object creation, materials, transforms, and arbitrary Python execution.

This repo currently ships an intentionally high-trust add-on:

- Codex runs with `approvalPolicy: "never"`.
- The thread runs with `sandbox: "danger-full-access"`.
- The add-on exposes `blender_run_python`, which executes arbitrary Python against the live Blender process.

Do not install this on a machine or Blender environment you do not control.

## What You Get

- A Blender add-on named `Codex Blender Unsafe`
- A dedicated `Codex` workspace created from Blender's `Layout` workspace
- A bottom `Text Editor` area used as the Codex prompt composer
- A sidebar session UI for connection state, activity feed, and prompt actions
- A live App Server bridge over `stdio`
- Structured Blender tools for common scene operations, plus a raw Python escape hatch

## Requirements

- Blender `3.0.0`
- `codex` available on `PATH`
- a working local Codex login
- Python 3 available for packaging and local smoke tests

Check that Codex is installed:

```bash
codex --version
```

If you are not logged in yet, authenticate with your normal Codex workflow before using the add-on.

## Install

The easiest path is to install the packaged zip:

- [dist/codex_blender_unsafe-0.4.1.zip](/home/mbuthi/Projects/codex-blender-app-server/dist/codex_blender_unsafe-0.4.1.zip)

In Blender:

1. Open `Edit > Preferences > Add-ons > Install...`
2. Choose `dist/codex_blender_unsafe-0.4.1.zip`
3. Enable `Codex Blender Unsafe`
4. Open the `Codex Unsafe` panel in the `View3D` sidebar
5. Click `Open Codex`

The add-on will create a `Codex` workspace automatically. That workspace reuses Blender's normal layout pattern:

- center: `3D Viewport`
- bottom: `Text Editor` for the prompt
- right: Blender side panels for Codex controls and activity

## Use It

### Prompt workflow

1. Switch to the `Codex` workspace.
2. In the bottom `Text Editor`, select the `Codex Prompt` text block.
3. Type a natural-language prompt there, for example:

```text
remove the cube
```

4. Send it using the `Send` button in either:
   - the `Codex Prompt` panel inside the `Text Editor`
   - the `Codex Unsafe` sidebar panel

Do not use Blender's `Run Script` button for prompts. The prompt editor is plain text for Codex, not Python source code to execute directly.

### Typical prompts

- `remove the cube`
- `create a red sphere at x 2`
- `inspect the current scene and tell me what is selected`
- `create a metallic blue material and assign it to the active object`
- `write a Blender Python script that arrays the selected object in a spiral`

### What the UI shows

- `Session`: model, workspace path, connection state, open/connect/disconnect
- `Activity`: user messages, assistant output, and tool calls in a single feed
- `Advanced`: raw event log
- `Text Editor > Codex Prompt`: send/interrupt controls for the prompt editor

## Current Tool Surface

Structured tools:

- `blender_get_scene_summary`
- `blender_list_objects`
- `blender_get_object_info`
- `blender_select_objects`
- `blender_create_primitive`
- `blender_set_object_transform`
- `blender_delete_objects`
- `blender_create_material`
- `blender_assign_material`
- `blender_read_text_block`
- `blender_write_text_block`

Escape hatch:

- `blender_run_python`

The structured tools cover most routine scene operations. `blender_run_python` exists for anything the structured tools cannot express yet.

## Build The Add-on Zip

From the repo root:

```bash
python3 scripts/package_addon.py
```

That writes the latest installable zip into `dist/`.

## Local Verification

### Python-level checks

```bash
python3 -m py_compile codex_blender_unsafe/*.py scripts/*.py
python3 scripts/smoke_test_protocol.py --skip-prompt
```

### Install test in isolated Blender profile

```bash
blender --background --factory-startup --python scripts/test_install_addon.py -- dist/codex_blender_unsafe-0.4.1.zip
```

### End-to-end Blender tool test

```bash
CODEX_BLENDER_TEST_TIMEOUT=90 blender --background --factory-startup --python scripts/test_in_blender.py
```

That test verifies a real Codex turn in Blender by creating a sphere, creating a material, assigning it, and checking the resulting scene state.

## Project Layout

- `codex_blender_unsafe/__init__.py`
  Blender add-on entrypoint, workspace setup, panels, operators, and transcript UI.
- `codex_blender_unsafe/app_server.py`
  Codex App Server bridge, notifications, tool call routing, and UI activity items.
- `codex_blender_unsafe/toolhost.py`
  Main-thread Blender tool execution.
- `scripts/package_addon.py`
  Builds the installable add-on zip.
- `scripts/smoke_test_protocol.py`
  Local bridge smoke test outside Blender.
- `scripts/test_install_addon.py`
  Installs and enables the add-on in an isolated Blender profile.
- `scripts/test_in_blender.py`
  Runs an end-to-end headless Blender integration test.

## Safety Notes

This add-on is not sandboxed in the way a normal user-facing plugin should be.

The important risks are:

- Codex can write and execute Blender Python
- approvals are auto-accepted
- the session runs with dangerous filesystem access

If you want to turn this into a safer public-facing tool, the first changes should be:

1. remove `approvalPolicy: "never"`
2. remove `sandbox: "danger-full-access"`
3. gate `blender_run_python` behind explicit user approval
4. prefer structured tools over raw code execution everywhere
5. make the prompt editor clearly distinct from Blender script execution
