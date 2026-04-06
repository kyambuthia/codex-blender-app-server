#!/usr/bin/env python3
from __future__ import annotations

import ast
from pathlib import Path
import zipfile


REPO_ROOT = Path(__file__).resolve().parent.parent
ADDON_DIR = REPO_ROOT / "codex_blender_unsafe"
DIST_DIR = REPO_ROOT / "dist"


def read_version() -> str:
    init_path = ADDON_DIR / "__init__.py"
    module = ast.parse(init_path.read_text(encoding="utf-8"))
    for node in module.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "bl_info":
                    value = ast.literal_eval(node.value)
                    version = value["version"]
                    return ".".join(str(part) for part in version)
    raise RuntimeError("Could not read bl_info.version from __init__.py")


def build_zip() -> Path:
    version = read_version()
    DIST_DIR.mkdir(exist_ok=True)
    zip_path = DIST_DIR / f"codex_blender_unsafe-{version}.zip"
    if zip_path.exists():
        zip_path.unlink()

    compression = zipfile.ZIP_STORED
    if getattr(zipfile, "zlib", None) is not None:
        compression = zipfile.ZIP_DEFLATED

    with zipfile.ZipFile(zip_path, "w", compression=compression) as archive:
        for path in sorted(ADDON_DIR.rglob("*")):
            if path.is_dir():
                continue
            if path.suffix in {".pyc", ".pyo"}:
                continue
            if "__pycache__" in path.parts:
                continue
            relative = path.relative_to(REPO_ROOT)
            archive.write(path, arcname=relative.as_posix())

    return zip_path


def main() -> int:
    print(build_zip())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
