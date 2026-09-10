#!/usr/bin/env python3
"""Download open-licence fonts into assets/fonts as <Family>.ttf / <Family>-Bold.ttf plus LICENSE-<Family>.txt.

All sources are free/open-source fonts (SIL Open Font License 1.1, Apache 2.0 or GNU GPL v3 with font
exception). Re-run at any time; existing files are overwritten. Families whose download fails are
reported and skipped, so a broken upstream URL never blocks the others.

    .venv/bin/python scripts/fetch_fonts.py            # everything
    .venv/bin/python scripts/fetch_fonts.py Lato Oswald
"""
from __future__ import annotations

import io
import sys
import tarfile
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path

FONT_DIR = Path(__file__).resolve().parent.parent / "assets" / "fonts"
GH = "https://github.com"
LIBERATION = f"{GH}/liberationfonts/liberation-fonts/files/7261482/liberation-fonts-ttf-2.1.5.tar.gz"
FREEFONT = "https://ftp.gnu.org/gnu/freefont/freefont-ttf-20120503.zip"
ROBOTO = f"{GH}/googlefonts/roboto/releases/download/v2.138/roboto-android.zip"
SOURCE_SANS = f"{GH}/adobe-fonts/source-sans/releases/download/3.052R/TTF-source-sans-3.052R.zip"


@dataclass(frozen=True)
class Source:
    url: str
    member: str | None = None  # path inside a zip/tar archive; None = the URL is the file itself


@dataclass(frozen=True)
class Family:
    name: str  # file stem used by the app
    licence: str  # short licence label
    regular: Source
    bold: Source
    licence_file: Source
    notes: str = ""


FAMILIES: list[Family] = [
    Family("Roboto", "Apache-2.0",
           Source(ROBOTO, "Roboto-Regular.ttf"), Source(ROBOTO, "Roboto-Bold.ttf"),
           Source(f"{GH}/googlefonts/roboto/raw/main/LICENSE")),
    Family("OpenSans", "OFL-1.1",
           Source(f"{GH}/googlefonts/opensans/raw/main/fonts/ttf/OpenSans-Regular.ttf"),
           Source(f"{GH}/googlefonts/opensans/raw/main/fonts/ttf/OpenSans-Bold.ttf"),
           Source(f"{GH}/googlefonts/opensans/raw/main/OFL.txt")),
    Family("Lato", "OFL-1.1",
           Source(f"{GH}/google/fonts/raw/main/ofl/lato/Lato-Regular.ttf"),
           Source(f"{GH}/google/fonts/raw/main/ofl/lato/Lato-Bold.ttf"),
           Source(f"{GH}/google/fonts/raw/main/ofl/lato/OFL.txt")),
    Family("Montserrat", "OFL-1.1",
           Source(f"{GH}/JulietaUla/Montserrat/raw/master/fonts/ttf/Montserrat-Regular.ttf"),
           Source(f"{GH}/JulietaUla/Montserrat/raw/master/fonts/ttf/Montserrat-Bold.ttf"),
           Source(f"{GH}/JulietaUla/Montserrat/raw/master/OFL.txt")),
    Family("SourceSans3", "OFL-1.1",
           Source(SOURCE_SANS, "TTF/SourceSans3-Regular.ttf"), Source(SOURCE_SANS, "TTF/SourceSans3-Bold.ttf"),
           Source(f"{GH}/adobe-fonts/source-sans/raw/release/LICENSE.md")),
    Family("NotoSans", "OFL-1.1",
           Source(f"{GH}/notofonts/notofonts.github.io/raw/main/fonts/NotoSans/full/ttf/NotoSans-Regular.ttf"),
           Source(f"{GH}/notofonts/notofonts.github.io/raw/main/fonts/NotoSans/full/ttf/NotoSans-Bold.ttf"),
           Source(f"{GH}/notofonts/latin-greek-cyrillic/raw/main/OFL.txt"),
           notes="very wide script coverage (Latin, Greek, Cyrillic, …)"),
    Family("LiberationSans", "OFL-1.1",
           Source(LIBERATION, "liberation-fonts-ttf-2.1.5/LiberationSans-Regular.ttf"),
           Source(LIBERATION, "liberation-fonts-ttf-2.1.5/LiberationSans-Bold.ttf"),
           Source(LIBERATION, "liberation-fonts-ttf-2.1.5/LICENSE"),
           notes="metric-compatible with Arial"),
    Family("LiberationSerif", "OFL-1.1",
           Source(LIBERATION, "liberation-fonts-ttf-2.1.5/LiberationSerif-Regular.ttf"),
           Source(LIBERATION, "liberation-fonts-ttf-2.1.5/LiberationSerif-Bold.ttf"),
           Source(LIBERATION, "liberation-fonts-ttf-2.1.5/LICENSE"),
           notes="metric-compatible with Times New Roman"),
    Family("FreeSans", "GPL-3.0-or-later with font exception",
           Source(FREEFONT, "freefont-20120503/FreeSans.ttf"), Source(FREEFONT, "freefont-20120503/FreeSansBold.ttf"),
           Source(FREEFONT, "freefont-20120503/COPYING"), notes="GNU FreeFont"),
    Family("FreeSerif", "GPL-3.0-or-later with font exception",
           Source(FREEFONT, "freefont-20120503/FreeSerif.ttf"), Source(FREEFONT, "freefont-20120503/FreeSerifBold.ttf"),
           Source(FREEFONT, "freefont-20120503/COPYING"), notes="GNU FreeFont"),
    Family("Oswald", "OFL-1.1",
           Source(f"{GH}/googlefonts/OswaldFont/raw/main/fonts/ttf/Oswald-Regular.ttf"),
           Source(f"{GH}/googlefonts/OswaldFont/raw/main/fonts/ttf/Oswald-Bold.ttf"),
           Source(f"{GH}/googlefonts/OswaldFont/raw/main/OFL.txt"),
           notes="condensed, good for tight table columns"),
    Family("Lora", "OFL-1.1",
           Source(f"{GH}/cyrealtype/Lora-Cyrillic/raw/main/fonts/ttf/Lora-Regular.ttf"),
           Source(f"{GH}/cyrealtype/Lora-Cyrillic/raw/main/fonts/ttf/Lora-Bold.ttf"),
           Source(f"{GH}/cyrealtype/Lora-Cyrillic/raw/main/OFL.txt"),
           notes="serif"),
    Family("Merriweather", "OFL-1.1",
           Source(f"{GH}/SorkinType/Merriweather/raw/master/fonts/ttf/Merriweather-Regular.ttf"),
           Source(f"{GH}/SorkinType/Merriweather/raw/master/fonts/ttf/Merriweather-Bold.ttf"),
           Source(f"{GH}/SorkinType/Merriweather/raw/master/OFL.txt"),
           notes="serif, designed for screens and print"),
]

_cache: dict[str, bytes] = {}


def fetch(url: str) -> bytes:
    if url not in _cache:
        req = urllib.request.Request(url, headers={"User-Agent": "megacalendar-fetch-fonts"})
        with urllib.request.urlopen(req, timeout=120) as resp:
            _cache[url] = resp.read()
    return _cache[url]


def load(source: Source) -> bytes:
    data = fetch(source.url)
    if source.member is None:
        return data
    if source.url.endswith(".zip"):
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            return zf.read(source.member)
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:*") as tf:
        member = tf.extractfile(source.member)
        if member is None:
            raise FileNotFoundError(source.member)
        return member.read()


def verify_ttf(data: bytes, label: str) -> None:
    from reportlab.pdfbase.ttfonts import TTFontFile

    if data[:4] not in (b"\x00\x01\x00\x00", b"true"):
        raise ValueError(f"{label}: not a TrueType font")
    TTFontFile(io.BytesIO(data))  # raises if ReportLab cannot embed it


def install(family: Family) -> None:
    regular, bold, licence = load(family.regular), load(family.bold), load(family.licence_file)
    verify_ttf(regular, f"{family.name} regular")
    verify_ttf(bold, f"{family.name} bold")
    (FONT_DIR / f"{family.name}.ttf").write_bytes(regular)
    (FONT_DIR / f"{family.name}-Bold.ttf").write_bytes(bold)
    (FONT_DIR / f"LICENSE-{family.name}.txt").write_bytes(licence)


def main(argv: list[str]) -> int:
    FONT_DIR.mkdir(parents=True, exist_ok=True)
    wanted = set(argv) or {f.name for f in FAMILIES}
    unknown = wanted - {f.name for f in FAMILIES}
    if unknown:
        print(f"unknown families: {sorted(unknown)}; available: {[f.name for f in FAMILIES]}", file=sys.stderr)
        return 2
    failed = []
    for family in FAMILIES:
        if family.name not in wanted:
            continue
        try:
            install(family)
            print(f"ok    {family.name:<16} {family.licence}")
        except Exception as exc:  # noqa: BLE001  keep going for the other families
            failed.append(family.name)
            print(f"FAIL  {family.name:<16} {type(exc).__name__}: {exc}")
    if failed:
        print(f"\n{len(failed)} famil{'y' if len(failed) == 1 else 'ies'} failed: {', '.join(failed)}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
