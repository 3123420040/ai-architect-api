from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


class BlenderToolError(RuntimeError):
    pass


@dataclass(frozen=True)
class BlenderTool:
    path: Path
    version: str


def _run(command: list[str], *, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=cwd, text=True, capture_output=True, check=False)


def discover_blender(*, require_binary: bool) -> BlenderTool | None:
    candidates: list[str] = []
    if os.environ.get("BLENDER_BIN"):
        candidates.append(os.environ["BLENDER_BIN"])
    candidates.append("blender")
    for candidate in candidates:
        resolved = shutil.which(candidate) if not Path(candidate).exists() else candidate
        if not resolved:
            continue
        path = Path(resolved)
        result = _run([str(path), "--background", "--version"])
        output = (result.stdout or result.stderr).strip().splitlines()
        version = output[0] if output else "unknown"
        return BlenderTool(path=path, version=version)
    if require_binary:
        raise BlenderToolError("BLENDER_BIN/blender was not found")
    return None


def run_blender_script(
    script_path: Path,
    args: list[str],
    *,
    require_binary: bool,
    cwd: Path | None = None,
) -> BlenderTool | None:
    tool = discover_blender(require_binary=require_binary)
    if tool is None:
        return None
    command = [str(tool.path), "--background", "--factory-startup", "--python", str(script_path), "--", *args]
    result = _run(command, cwd=cwd)
    if result.returncode != 0:
        detail = "\n".join(line for line in (result.stdout + result.stderr).splitlines() if line.strip())
        raise BlenderToolError(f"Blender script failed: {script_path.name}: {detail}")
    return tool
