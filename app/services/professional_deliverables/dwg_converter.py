from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


class ODAConverterError(RuntimeError):
    pass


@dataclass(frozen=True)
class ODAResult:
    command: tuple[str, ...]
    stdout: str
    stderr: str
    produced_files: tuple[Path, ...]


def find_oda_binary() -> str | None:
    configured = os.environ.get("ODA_FILE_CONVERTER_BIN")
    if configured:
        return configured
    return shutil.which("ODAFileConverter")


def build_oda_command(
    *,
    source_dir: Path,
    target_dir: Path,
    output_version: str = "ACAD2018",
    output_type: str = "DWG",
    recursive: bool = False,
    audit: bool = True,
    input_filter: str = "*.DXF",
    use_xvfb: bool | None = None,
    binary: str | None = None,
) -> tuple[str, ...]:
    resolved_binary = binary or find_oda_binary()
    if not resolved_binary:
        raise ODAConverterError("ODA File Converter binary not found. Set ODA_FILE_CONVERTER_BIN.")
    command: list[str] = [
        resolved_binary,
        str(source_dir),
        str(target_dir),
        output_version,
        output_type,
        "1" if recursive else "0",
        "1" if audit else "0",
        input_filter,
    ]
    if use_xvfb is None:
        use_xvfb = bool(os.environ.get("CI"))
    if use_xvfb:
        return ("xvfb-run", "-a", *command)
    return tuple(command)


def convert_dxf_directory_to_dwg(source_dir: Path, target_dir: Path, *, require_binary: bool = True) -> ODAResult | None:
    binary = find_oda_binary()
    if not binary:
        if require_binary or os.environ.get("CI"):
            raise ODAConverterError("ODA File Converter binary not found. Set ODA_FILE_CONVERTER_BIN.")
        return None
    target_dir.mkdir(parents=True, exist_ok=True)
    command = build_oda_command(source_dir=source_dir, target_dir=target_dir, output_type="DWG", binary=binary)
    completed = subprocess.run(command, check=False, capture_output=True, text=True)
    if completed.returncode != 0:
        raise ODAConverterError(
            f"ODA conversion failed with exit code {completed.returncode}\nSTDOUT:\n{completed.stdout}\nSTDERR:\n{completed.stderr}"
        )
    produced = tuple(sorted(target_dir.glob("*.dwg"))) + tuple(sorted(target_dir.glob("*.DWG")))
    return ODAResult(tuple(command), completed.stdout, completed.stderr, produced)


def audit_dwg_directory(source_dir: Path, target_dir: Path, *, require_binary: bool = True) -> ODAResult | None:
    binary = find_oda_binary()
    if not binary:
        if require_binary or os.environ.get("CI"):
            raise ODAConverterError("ODA File Converter binary not found. Set ODA_FILE_CONVERTER_BIN.")
        return None
    target_dir.mkdir(parents=True, exist_ok=True)
    command = build_oda_command(
        source_dir=source_dir,
        target_dir=target_dir,
        output_type="DXF",
        input_filter="*.dwg",
        binary=binary,
    )
    completed = subprocess.run(command, check=False, capture_output=True, text=True)
    if completed.returncode != 0:
        raise ODAConverterError(
            f"ODA audit/round-trip failed with exit code {completed.returncode}\nSTDOUT:\n{completed.stdout}\nSTDERR:\n{completed.stderr}"
        )
    produced = tuple(sorted(target_dir.glob("*.dxf"))) + tuple(sorted(target_dir.glob("*.DXF")))
    return ODAResult(tuple(command), completed.stdout, completed.stderr, produced)
