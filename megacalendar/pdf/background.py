"""Full-page background artwork (SVG or raster), embedded in the project's colour model."""
from __future__ import annotations

import io
from pathlib import Path

import numpy as np
from PIL import Image
from reportlab.graphics import renderPDF
from reportlab.graphics.shapes import Group
from reportlab.lib.colors import CMYKColor, Color
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen.canvas import Canvas

from svglib.svglib import svg2rlg

from .spec import CMYK, RGB

Image.MAX_IMAGE_PIXELS = None  # A0 at 300 dpi is ~140 Mpx; trust our own uploads


def _fit(src_w: float, src_h: float, page_w: float, page_h: float, mode: str) -> tuple[float, float, float, float]:
    """Return (scale_x, scale_y, offset_x, offset_y) for the given fit mode."""
    if mode == "stretch":
        return page_w / src_w, page_h / src_h, 0.0, 0.0
    if mode == "contain":
        s = min(page_w / src_w, page_h / src_h)
    elif mode == "cover":
        s = max(page_w / src_w, page_h / src_h)
    else:
        raise ValueError(f"unknown background mode {mode!r}")
    return s, s, (page_w - src_w * s) / 2, (page_h - src_h * s) / 2


# ---------------------------------------------------------------- SVG

def _convert_color(color, color_mode: str, opacity: float):
    if color is None or not isinstance(color, Color):
        return color
    alpha = (color.alpha if color.alpha is not None else 1.0) * opacity
    if color_mode == "CMYK":
        if isinstance(color, CMYKColor):
            out = color.clone()
        else:
            out = CMYK.from_rgb(color.red, color.green, color.blue).to_reportlab()
    else:
        out = RGB(round(color.red * 255), round(color.green * 255), round(color.blue * 255)).to_reportlab()
    out.alpha = alpha
    return out


def convert_drawing_colors(node, color_mode: str, opacity: float = 1.0) -> None:
    """Walk a reportlab.graphics tree, converting every colour to the colour
    model and multiplying in the opacity."""
    for attr in ("fillColor", "strokeColor"):
        if hasattr(node, attr):
            setattr(node, attr, _convert_color(getattr(node, attr), color_mode, opacity))
    if isinstance(node, Group):
        for child in node.contents:
            convert_drawing_colors(child, color_mode, opacity)


def artwork_size(path: Path) -> tuple[float, float]:
    """Natural size of an artwork file (SVG user units or raster pixels); only the ratio matters."""
    if path.suffix.lower() == ".svg":
        drawing = svg2rlg(str(path))
        if drawing is None or not drawing.width or not drawing.height:
            raise ValueError(f"could not parse SVG {path.name}")
        return float(drawing.width), float(drawing.height)
    with Image.open(path) as im:
        return float(im.width), float(im.height)


def _draw_svg(c: Canvas, path: Path, box_x: float, box_y: float, box_w: float, box_h: float, mode: str,
              font_name: str, color_mode: str, opacity: float) -> None:
    drawing = svg2rlg(str(path))
    if drawing is None:
        raise ValueError(f"could not parse SVG {path.name}")
    convert_drawing_colors(drawing, color_mode, opacity)
    # The graphics renderer seeds its state from these attributes; without them it
    # references an un-embedded base-14 font and RGB black in the page stream.
    black = (CMYK(0, 0, 0, 100) if color_mode == "CMYK" else RGB(0, 0, 0)).to_reportlab()
    for attr, value in (("initialFontName", font_name), ("initialFillColor", black), ("initialStrokeColor", black)):
        object.__setattr__(drawing, attr, value)
    sx, sy, ox, oy = _fit(drawing.width, drawing.height, box_w, box_h, mode)
    drawing.scale(sx, sy)
    renderPDF.draw(drawing, c, box_x + ox, box_y + oy)


# ---------------------------------------------------------------- raster

def rgb_to_cmyk_array(rgb: np.ndarray) -> np.ndarray:
    """RGB uint8 (h,w,3) -> CMYK uint8 (h,w,4) with black generation (same
    formula as CMYK.from_rgb, vectorised)."""
    rgbf = rgb.astype(np.float32) / 255.0
    k = 1.0 - rgbf.max(axis=2)
    denom = np.where(k < 1.0, 1.0 - k, 1.0)
    cmy = (1.0 - rgbf - k[..., None]) / denom[..., None]
    cmy = np.where(k[..., None] < 1.0, cmy, 0.0)
    out = np.concatenate([cmy, k[..., None]], axis=2)
    return np.clip(np.rint(out * 255.0), 0, 255).astype(np.uint8)


def raster_to_cmyk_jpeg(path: Path, quality: int = 95) -> tuple[io.BytesIO, int, int]:
    """Return a CMYK JPEG byte stream (ReportLab passes JPEG data through
    untouched, so this is the only way to keep DeviceCMYK for rasters)."""
    with Image.open(path) as im:
        if im.mode == "CMYK":
            if im.format == "JPEG":
                return io.BytesIO(path.read_bytes()), im.width, im.height
            cmyk = im.copy()
        else:
            if im.mode in ("RGBA", "LA", "P"):
                # Flatten transparency onto white paper.
                rgba = im.convert("RGBA")
                paper = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
                im_rgb = Image.alpha_composite(paper, rgba).convert("RGB")
            else:
                im_rgb = im.convert("RGB")
            cmyk = Image.fromarray(rgb_to_cmyk_array(np.asarray(im_rgb)), mode="CMYK")
        buf = io.BytesIO()
        cmyk.save(buf, format="JPEG", quality=quality, subsampling=0)
        buf.seek(0)
        return buf, cmyk.width, cmyk.height


def _draw_raster(c: Canvas, path: Path, box_x: float, box_y: float, box_w: float, box_h: float, mode: str,
                 color_mode: str, opacity: float) -> None:
    if color_mode == "CMYK":
        buf, w, h = raster_to_cmyk_jpeg(path)
        reader, mask = ImageReader(buf), None
    else:
        with Image.open(path) as im:
            w, h = im.size
            if im.mode == "CMYK":  # ReportLab would embed DeviceCMYK; convert for an RGB document
                buf = io.BytesIO()
                im.convert("RGB").save(buf, format="PNG")
                buf.seek(0)
                reader, mask = ImageReader(buf), None
            else:
                reader, mask = ImageReader(str(path)), "auto"  # keep PNG alpha
    sx, sy, ox, oy = _fit(w, h, box_w, box_h, mode)
    c.setFillAlpha(opacity)
    c.drawImage(reader, box_x + ox, box_y + oy, width=w * sx, height=h * sy, mask=mask)


# ---------------------------------------------------------------- entry

def draw_artwork(c: Canvas, path: Path, x: float, y: float, w: float, h: float, mode: str = "contain",
                 font_name: str = "Helvetica", color_mode: str = "RGB", opacity: float = 1.0) -> None:
    """Draw an SVG or raster file into the box (x, y, w, h), clipped to it."""
    if opacity <= 0 or w <= 0 or h <= 0:
        return
    c.saveState()
    clip = c.beginPath()
    clip.rect(x, y, w, h)
    c.clipPath(clip, stroke=0, fill=0)
    if path.suffix.lower() == ".svg":
        _draw_svg(c, path, x, y, w, h, mode, font_name, color_mode, opacity)
    else:
        _draw_raster(c, path, x, y, w, h, mode, color_mode, opacity)
    c.restoreState()


def draw_background(c: Canvas, path: Path, page_w: float, page_h: float, mode: str = "cover",
                    font_name: str = "Helvetica", color_mode: str = "RGB", opacity: float = 1.0) -> None:
    draw_artwork(c, path, 0, 0, page_w, page_h, mode, font_name, color_mode, opacity)
