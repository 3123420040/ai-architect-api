from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass
from pathlib import Path

from app.services.professional_deliverables.scene_contract import MaterialSpec, TEXTURE_SLOTS, TextureSlot

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


@dataclass(frozen=True)
class AuthoredTexture:
    material_name: str
    slot: TextureSlot
    source_path: Path
    resolution_px: int
    expected_sample_rgba: tuple[int, int, int, int]


def _png_chunk(kind: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)


def write_solid_rgba_png(path: Path, *, size_px: int, color: tuple[int, int, int, int]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    row = b"\x00" + bytes(color) * size_px
    raw = row * size_px
    payload = bytearray(PNG_SIGNATURE)
    payload.extend(_png_chunk(b"IHDR", struct.pack(">IIBBBBB", size_px, size_px, 8, 6, 0, 0, 0)))
    payload.extend(_png_chunk(b"IDAT", zlib.compress(raw, level=9)))
    payload.extend(_png_chunk(b"IEND", b""))
    path.write_bytes(bytes(payload))


def material_slot_color(material: MaterialSpec, slot: TextureSlot) -> tuple[int, int, int, int]:
    if slot == "baseColor":
        return material.channels.base_color_rgba
    if slot == "metallicRoughness":
        return material.channels.metallic_roughness_rgba
    if slot == "normal":
        return material.channels.normal_rgba
    if slot == "ao":
        return material.channels.ao_rgba
    if slot == "emissive":
        return material.channels.emissive_rgba
    raise AssertionError(f"Unhandled texture slot: {slot}")


def write_source_textures(materials: tuple[MaterialSpec, ...], output_dir: Path) -> dict[str, dict[TextureSlot, AuthoredTexture]]:
    authored: dict[str, dict[TextureSlot, AuthoredTexture]] = {}
    for material in materials:
        authored[material.name] = {}
        for slot in TEXTURE_SLOTS:
            color = material_slot_color(material, slot)
            path = output_dir / material.texture_filename(slot, extension="png")
            write_solid_rgba_png(path, size_px=material.resolution_px, color=color)
            authored[material.name][slot] = AuthoredTexture(
                material_name=material.name,
                slot=slot,
                source_path=path,
                resolution_px=material.resolution_px,
                expected_sample_rgba=color,
            )
    return authored


def _paeth_predictor(a: int, b: int, c: int) -> int:
    p = a + b - c
    pa = abs(p - a)
    pb = abs(p - b)
    pc = abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    if pb <= pc:
        return b
    return c


def _read_png_chunks(path: Path) -> tuple[dict[str, int], bytes]:
    data = path.read_bytes()
    if not data.startswith(PNG_SIGNATURE):
        raise ValueError(f"{path} is not a PNG file")
    pos = len(PNG_SIGNATURE)
    info: dict[str, int] = {}
    compressed = bytearray()
    while pos < len(data):
        length = struct.unpack(">I", data[pos : pos + 4])[0]
        kind = data[pos + 4 : pos + 8]
        chunk = data[pos + 8 : pos + 8 + length]
        pos += 12 + length
        if kind == b"IHDR":
            width, height, bit_depth, color_type, compression, filter_method, interlace = struct.unpack(">IIBBBBB", chunk)
            info = {
                "width": width,
                "height": height,
                "bit_depth": bit_depth,
                "color_type": color_type,
                "compression": compression,
                "filter": filter_method,
                "interlace": interlace,
            }
        elif kind == b"IDAT":
            compressed.extend(chunk)
        elif kind == b"IEND":
            break
    if not info:
        raise ValueError(f"{path} has no IHDR chunk")
    return info, bytes(compressed)


def read_png_dimensions(path: Path) -> tuple[int, int]:
    info, _ = _read_png_chunks(path)
    return (info["width"], info["height"])


def sample_png_pixel(path: Path, *, x: int = 0, y: int = 0) -> tuple[int, int, int, int]:
    info, compressed = _read_png_chunks(path)
    if info["interlace"] != 0:
        raise ValueError(f"{path} must be a non-interlaced PNG")
    if info["bit_depth"] not in {8, 16}:
        raise ValueError(f"{path} must be an 8-bit or 16-bit PNG")
    channels_by_color_type = {2: 3, 6: 4}
    channels = channels_by_color_type.get(info["color_type"])
    if channels is None:
        raise ValueError(f"{path} must be RGB or RGBA PNG")
    width = info["width"]
    height = info["height"]
    if not (0 <= x < width and 0 <= y < height):
        raise ValueError(f"Pixel ({x}, {y}) outside {path.name} bounds {width}x{height}")

    raw = zlib.decompress(compressed)
    bytes_per_sample = info["bit_depth"] // 8
    bytes_per_pixel = channels * bytes_per_sample
    stride = width * bytes_per_pixel
    previous = bytearray(stride)
    offset = 0
    for row_index in range(height):
        filter_type = raw[offset]
        offset += 1
        row = bytearray(raw[offset : offset + stride])
        offset += stride
        for idx in range(stride):
            left = row[idx - bytes_per_pixel] if idx >= bytes_per_pixel else 0
            up = previous[idx]
            up_left = previous[idx - bytes_per_pixel] if idx >= bytes_per_pixel else 0
            if filter_type == 0:
                pass
            elif filter_type == 1:
                row[idx] = (row[idx] + left) & 0xFF
            elif filter_type == 2:
                row[idx] = (row[idx] + up) & 0xFF
            elif filter_type == 3:
                row[idx] = (row[idx] + ((left + up) // 2)) & 0xFF
            elif filter_type == 4:
                row[idx] = (row[idx] + _paeth_predictor(left, up, up_left)) & 0xFF
            else:
                raise ValueError(f"{path} uses unsupported PNG filter {filter_type}")
        if row_index == y:
            start = x * bytes_per_pixel
            if bytes_per_sample == 1:
                pixel = tuple(row[start : start + bytes_per_pixel])
            else:
                pixel = tuple(row[start + channel_index * 2] for channel_index in range(channels))
            if channels == 3:
                return (pixel[0], pixel[1], pixel[2], 255)
            return (pixel[0], pixel[1], pixel[2], pixel[3])
        previous = row
    raise ValueError(f"Pixel ({x}, {y}) was not decoded from {path}")
