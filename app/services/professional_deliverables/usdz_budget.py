from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

AR_QUICK_LOOK_MAX_BYTES = 8 * 1024 * 1024
AR_QUICK_LOOK_MAX_TRIANGLES = 200_000
AR_QUICK_LOOK_MAX_TEXTURE_PX = 2048
AR_QUICK_LOOK_LITE_TEXTURE_PX = 1024


class USDZBudgetError(RuntimeError):
    pass


@dataclass(frozen=True)
class USDZBudgetReport:
    size_bytes: int
    triangle_count: int
    max_texture_px: int

    @property
    def within_budget(self) -> bool:
        return (
            self.size_bytes <= AR_QUICK_LOOK_MAX_BYTES
            and self.triangle_count <= AR_QUICK_LOOK_MAX_TRIANGLES
            and self.max_texture_px <= AR_QUICK_LOOK_MAX_TEXTURE_PX
        )

    def as_dict(self) -> dict:
        return {
            "size_bytes": self.size_bytes,
            "triangle_count": self.triangle_count,
            "max_texture_px": self.max_texture_px,
            "within_budget": self.within_budget,
        }


def assert_usdz_budget(path: Path, report: USDZBudgetReport) -> None:
    if not path.exists():
        raise USDZBudgetError(f"{path.name} was not produced")
    if report.size_bytes > AR_QUICK_LOOK_MAX_BYTES:
        raise USDZBudgetError(f"{path.name} is {report.size_bytes} bytes > {AR_QUICK_LOOK_MAX_BYTES}")
    if report.triangle_count > AR_QUICK_LOOK_MAX_TRIANGLES:
        raise USDZBudgetError(
            f"{path.name} has {report.triangle_count} triangles > {AR_QUICK_LOOK_MAX_TRIANGLES}"
        )
    if report.max_texture_px > AR_QUICK_LOOK_MAX_TEXTURE_PX:
        raise USDZBudgetError(f"{path.name} has texture dimension {report.max_texture_px} > {AR_QUICK_LOOK_MAX_TEXTURE_PX}")
