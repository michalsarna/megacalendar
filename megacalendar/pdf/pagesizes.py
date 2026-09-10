"""Supported sheet sizes. Add new formats here; everything else scales."""
from __future__ import annotations

from dataclasses import dataclass

from reportlab.lib.units import mm


@dataclass(frozen=True)
class PageSize:
    code: str
    width_mm: float
    height_mm: float  # portrait dimensions

    def points(self, orientation: str) -> tuple[float, float]:
        w, h = self.width_mm * mm, self.height_mm * mm
        if orientation == "landscape":
            return h, w
        if orientation == "portrait":
            return w, h
        raise ValueError(f"unknown orientation {orientation!r}")


PAGE_SIZES: dict[str, PageSize] = {
    "A0": PageSize("A0", 841, 1189),
    "A1": PageSize("A1", 594, 841),
    "A2": PageSize("A2", 420, 594),
    "A3": PageSize("A3", 297, 420),
    "A4": PageSize("A4", 210, 297),
    "A5": PageSize("A5", 148, 210),
}

ORIENTATIONS = ("portrait", "landscape")


def get_page_size(code: str) -> PageSize:
    try:
        return PAGE_SIZES[code]
    except KeyError:
        raise ValueError(f"unsupported page size {code!r}; choose one of {sorted(PAGE_SIZES)}") from None
