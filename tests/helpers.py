"""Assertions about print-readiness of a produced PDF."""
from __future__ import annotations

import io
import re

from pypdf import PdfReader
from pypdf.generic import IndirectObject

RGB_OPS = re.compile(rb"(?:^|\s)(?:rg|RG|g|G)(?=\s)")  # DeviceRGB / DeviceGray fill+stroke operators
GRAY_OPS = re.compile(rb"(?:^|\s)(?:g|G)(?=\s)")
CMYK_OPS = re.compile(rb"(?:^|\s)(?:k|K)(?=\s)")


def _resolve(obj):
    return obj.get_object() if isinstance(obj, IndirectObject) else obj


def assert_print_ready(pdf_bytes: bytes, expect_width_mm: float, expect_height_mm: float, expect_images: int = 0,
                       mode: str = "CMYK"):
    """Page size, single colour model (no Gray, no operators of the other model),
    embedded fonts, and image colour spaces matching the colour model."""
    reader = PdfReader(io.BytesIO(pdf_bytes))
    assert len(reader.pages) == 1
    page = reader.pages[0]

    box = page.mediabox
    w_mm, h_mm = float(box.width) / 72 * 25.4, float(box.height) / 72 * 25.4
    assert abs(w_mm - expect_width_mm) < 0.5, w_mm
    assert abs(h_mm - expect_height_mm) < 0.5, h_mm

    content = page.get_contents().get_data()
    if mode == "CMYK":
        assert CMYK_OPS.search(content), "no CMYK colour operators in page content"
        assert not RGB_OPS.search(content), "RGB/Gray colour operators found in page content"
    else:
        assert RGB_OPS.search(content) and not GRAY_OPS.search(content), "expected DeviceRGB operators only"
        assert not CMYK_OPS.search(content), "CMYK colour operators found in an RGB document"

    resources = _resolve(page["/Resources"])
    fonts = _resolve(resources.get("/Font", {}))
    assert fonts, "no fonts used"
    for ref in fonts.values():
        font = _resolve(ref)
        desc = font.get("/FontDescriptor")
        if desc is None and "/DescendantFonts" in font:
            desc = _resolve(_resolve(font["/DescendantFonts"])[0]).get("/FontDescriptor")
        desc = _resolve(desc)
        assert desc is not None, f"font {font.get('/BaseFont')} has no descriptor (not embedded)"
        assert any(k in desc for k in ("/FontFile", "/FontFile2", "/FontFile3")), f"font {font.get('/BaseFont')} not embedded"

    xobjects = _resolve(resources.get("/XObject", {}))
    images = [_resolve(x) for x in xobjects.values() if _resolve(x).get("/Subtype") == "/Image"]
    assert len(images) == expect_images, f"expected {expect_images} images, found {len(images)}"
    for img in images:
        assert img["/ColorSpace"] == f"/Device{mode}", img["/ColorSpace"]
    return reader
