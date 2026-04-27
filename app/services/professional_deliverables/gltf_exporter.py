from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from app.core.config import ROOT_DIR


class GLTFExportError(RuntimeError):
    pass


@dataclass(frozen=True)
class GLTFTransformTool:
    path: Path
    version: str


def _run(command: list[str], *, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=cwd, text=True, capture_output=True, check=False)


def discover_gltf_transform(*, require_binary: bool) -> GLTFTransformTool | None:
    candidates: list[str] = []
    if os.environ.get("GLTF_TRANSFORM_BIN"):
        candidates.append(os.environ["GLTF_TRANSFORM_BIN"])
    candidates.append(str(ROOT_DIR / "tools" / "sprint2" / "node_modules" / ".bin" / "gltf-transform"))
    candidates.append("gltf-transform")
    for candidate in candidates:
        resolved = shutil.which(candidate) if not Path(candidate).exists() else candidate
        if not resolved:
            continue
        path = Path(resolved)
        result = _run([str(path), "--version"])
        version = (result.stdout or result.stderr).strip().splitlines()[0] if (result.stdout or result.stderr).strip() else "unknown"
        return GLTFTransformTool(path=path, version=version)
    if require_binary:
        raise GLTFExportError("GLTF_TRANSFORM_BIN/gltf-transform was not found")
    return None


def export_glb_with_gltf_transform(
    source_glb: Path,
    output_glb: Path,
    *,
    work_dir: Path,
    require_binary: bool,
) -> GLTFTransformTool | None:
    tool = discover_gltf_transform(require_binary=require_binary)
    if tool is None:
        return None
    output_glb.parent.mkdir(parents=True, exist_ok=True)
    command = [str(tool.path), "draco", str(source_glb), str(output_glb), "--method", "edgebreaker"]
    result = _run(command, cwd=work_dir)
    if result.returncode != 0:
        detail = "\n".join(line for line in (result.stdout + result.stderr).splitlines() if line.strip())
        raise GLTFExportError(f"glTF Transform failed: {' '.join(command[:3])}: {detail}")
    return tool
