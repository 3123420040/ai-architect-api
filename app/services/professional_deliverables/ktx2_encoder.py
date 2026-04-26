from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from app.services.professional_deliverables.scene_contract import MaterialSpec, TEXTURE_SLOTS, TextureSlot
from app.services.professional_deliverables.texture_authoring import AuthoredTexture


class ExternalToolError(RuntimeError):
    pass


@dataclass(frozen=True)
class KTXTool:
    path: Path
    style: str
    version: str

    @property
    def command_label(self) -> str:
        return f"{self.path.name} ({self.style})"


def _run(command: list[str], *, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=cwd, text=True, capture_output=True, check=False)


def discover_ktx_tool(*, require_binary: bool) -> KTXTool | None:
    candidates: list[str] = []
    if os.environ.get("KTX_BIN"):
        candidates.append(os.environ["KTX_BIN"])
    candidates.extend(["ktx", "toktx"])
    for candidate in candidates:
        resolved = shutil.which(candidate) if not Path(candidate).exists() else candidate
        if not resolved:
            continue
        path = Path(resolved)
        name = path.name.lower()
        style = "ktx" if name == "ktx" else "toktx"
        result = _run([str(path), "--version"])
        version = (result.stdout or result.stderr).strip().splitlines()[0] if (result.stdout or result.stderr).strip() else "unknown"
        return KTXTool(path=path, style=style, version=version)
    if require_binary:
        raise ExternalToolError("KTX_BIN/ktx/toktx was not found")
    return None


def _slot_transfer(slot: TextureSlot) -> str:
    return "srgb" if slot in {"baseColor", "emissive"} else "linear"


def _ktx_create_command(tool: KTXTool, source_png: Path, output_ktx: Path, *, slot: TextureSlot, codec: str) -> list[str]:
    transfer = _slot_transfer(slot)
    fmt = "R8G8B8A8_SRGB" if transfer == "srgb" else "R8G8B8A8_UNORM"
    encode = "uastc" if codec == "uastc" else "basis-lz"
    command = [
        str(tool.path),
        "create",
        "--format",
        fmt,
        "--encode",
        encode,
        "--assign-tf",
        transfer,
        "--assign-primaries",
        "srgb",
        "--generate-mipmap",
    ]
    if encode == "uastc":
        command.extend(["--uastc-quality", "2", "--zstd", "18"])
    else:
        command.extend(["--qlevel", "192", "--clevel", "5"])
    command.extend([str(source_png), str(output_ktx)])
    return command


def _toktx_command(tool: KTXTool, source_png: Path, output_ktx: Path, *, slot: TextureSlot, codec: str) -> list[str]:
    encode = "uastc" if codec == "uastc" else "basis-lz"
    command = [
        str(tool.path),
        "--t2",
        "--target_type",
        "RGBA",
        "--genmipmap",
        "--encode",
        encode,
    ]
    if _slot_transfer(slot) == "srgb":
        command.append("--assign_oetf")
        command.append("srgb")
    else:
        command.append("--assign_oetf")
        command.append("linear")
    if encode == "uastc":
        command.extend(["--uastc_quality", "2", "--zcmp", "18"])
    else:
        command.extend(["--qlevel", "192", "--clevel", "5"])
    command.extend([str(output_ktx), str(source_png)])
    return command


def encode_texture(
    tool: KTXTool,
    source_png: Path,
    output_ktx: Path,
    *,
    slot: TextureSlot,
    codec: str,
) -> None:
    output_ktx.parent.mkdir(parents=True, exist_ok=True)
    command = (
        _ktx_create_command(tool, source_png, output_ktx, slot=slot, codec=codec)
        if tool.style == "ktx"
        else _toktx_command(tool, source_png, output_ktx, slot=slot, codec=codec)
    )
    result = _run(command)
    if result.returncode != 0:
        detail = "\n".join(line for line in (result.stdout + result.stderr).splitlines() if line.strip())
        raise ExternalToolError(f"KTX2 encode failed for {source_png.name}: {detail}")


def encode_material_textures(
    materials: tuple[MaterialSpec, ...],
    authored: dict[str, dict[TextureSlot, AuthoredTexture]],
    output_dir: Path,
    *,
    require_binary: bool,
) -> tuple[KTXTool | None, tuple[Path, ...]]:
    tool = discover_ktx_tool(require_binary=require_binary)
    if tool is None:
        return None, ()
    outputs: list[Path] = []
    for material in materials:
        for slot in TEXTURE_SLOTS:
            source = authored[material.name][slot].source_path
            target = output_dir / material.texture_filename(slot, extension="ktx2")
            encode_texture(tool, source, target, slot=slot, codec=material.texture_codec)
            outputs.append(target)
    return tool, tuple(outputs)


def extract_ktx_to_png(tool: KTXTool, ktx_path: Path, png_path: Path) -> None:
    if tool.style != "ktx":
        raise ExternalToolError("KTX pixel extraction requires the unified ktx CLI")
    png_path.parent.mkdir(parents=True, exist_ok=True)
    command = [str(tool.path), "extract", "--transcode", "rgba8", str(ktx_path), str(png_path)]
    result = _run(command)
    if result.returncode != 0:
        detail = "\n".join(line for line in (result.stdout + result.stderr).splitlines() if line.strip())
        raise ExternalToolError(f"KTX2 extract failed for {ktx_path.name}: {detail}")


def extract_ktx_rgba8_sample(tool: KTXTool, ktx_path: Path, raw_path: Path) -> tuple[int, int, int, int]:
    if tool.style != "ktx":
        raise ExternalToolError("KTX pixel extraction requires the unified ktx CLI")
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    command = [str(tool.path), "extract", "--transcode", "rgba8", "--raw", str(ktx_path), str(raw_path)]
    result = _run(command)
    if result.returncode != 0:
        detail = "\n".join(line for line in (result.stdout + result.stderr).splitlines() if line.strip())
        raise ExternalToolError(f"KTX2 raw extract failed for {ktx_path.name}: {detail}")
    data = raw_path.read_bytes()
    if len(data) < 4:
        raise ExternalToolError(f"KTX2 raw extract was empty for {ktx_path.name}")
    return (data[0], data[1], data[2], data[3])


def validate_ktx(tool: KTXTool, ktx_path: Path) -> None:
    if tool.style != "ktx":
        return
    result = _run([str(tool.path), "validate", str(ktx_path)])
    if result.returncode != 0:
        detail = "\n".join(line for line in (result.stdout + result.stderr).splitlines() if line.strip())
        raise ExternalToolError(f"KTX2 validation failed for {ktx_path.name}: {detail}")
