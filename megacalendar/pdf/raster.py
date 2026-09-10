"""Rasterises a rendered PDF page into PNG or TIFF.

PNG has no CMYK colour type, so it is always produced in RGB (a screen preview).
TIFF keeps the document's own colour model, so a CMYK project yields a true CMYK
TIFF suitable for print, channel-for-channel identical to the PDF's ink values.
"""
from __future__ import annotations

import io

import pymupdf
from PIL import Image

IMAGE_FORMATS = ("png", "tiff")
DEFAULT_DPI = 200.0
MIN_DPI = 72.0
MAX_DPI = 300.0  # higher risks multi-hundred-MB rasters for A0/A1 sheets


def render_to_image(pdf_bytes: bytes, fmt: str, color_mode: str, dpi: float = DEFAULT_DPI) -> bytes:
    if fmt not in IMAGE_FORMATS:
        raise ValueError(f"unknown image format {fmt!r}; choose one of {IMAGE_FORMATS}")
    if not MIN_DPI <= dpi <= MAX_DPI:
        raise ValueError(f"dpi must be between {MIN_DPI:.0f} and {MAX_DPI:.0f}")
    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    page = doc[0]
    dpi_int = round(dpi)  # pymupdf's pixmap DPI setter requires an int
    if fmt == "png":
        pix = page.get_pixmap(dpi=dpi_int, colorspace=pymupdf.csRGB)
        return pix.tobytes("png")
    mode, colorspace = ("CMYK", pymupdf.csCMYK) if color_mode == "CMYK" else ("RGB", pymupdf.csRGB)
    pix = page.get_pixmap(dpi=dpi_int, colorspace=colorspace)
    image = Image.frombytes(mode, (pix.width, pix.height), pix.samples)
    buf = io.BytesIO()
    image.save(buf, format="TIFF", dpi=(dpi_int, dpi_int), compression="tiff_lzw")
    return buf.getvalue()
