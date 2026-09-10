# Bundled fonts

Every family here is free and open-source, embeddable in PDFs, and ships with its licence text as
`LICENSE-<Family>.txt`. The app picks up any `<Family>.ttf` (+ optional `<Family>-Bold.ttf`) in this
directory. Refresh or add families with `python scripts/fetch_fonts.py` (see the `FAMILIES` list there).

| Family (app name) | Licence | Source | Notes |
| --- | --- | --- | --- |
| DejaVuSans | Bitstream Vera licence (permissive) | https://dejavu-fonts.github.io | default font |
| Roboto | Apache-2.0 | https://github.com/googlefonts/roboto |  |
| OpenSans | OFL-1.1 | https://github.com/googlefonts/opensans |  |
| Lato | OFL-1.1 | https://github.com/google/fonts |  |
| Montserrat | OFL-1.1 | https://github.com/JulietaUla/Montserrat |  |
| SourceSans3 | OFL-1.1 | https://github.com/adobe-fonts/source-sans |  |
| NotoSans | OFL-1.1 | https://github.com/notofonts/notofonts.github.io | very wide script coverage (Latin, Greek, Cyrillic, …) |
| LiberationSans | OFL-1.1 | https://github.com/liberationfonts/liberation-fonts | metric-compatible with Arial |
| LiberationSerif | OFL-1.1 | https://github.com/liberationfonts/liberation-fonts | metric-compatible with Times New Roman |
| FreeSans | GPL-3.0-or-later with font exception | https://ftp.gnu.org/gnu/freefont/freefont-ttf-20120503.zip | GNU FreeFont |
| FreeSerif | GPL-3.0-or-later with font exception | https://ftp.gnu.org/gnu/freefont/freefont-ttf-20120503.zip | GNU FreeFont |
| Oswald | OFL-1.1 | https://github.com/googlefonts/OswaldFont | condensed, good for tight table columns |
| Lora | OFL-1.1 | https://github.com/cyrealtype/Lora-Cyrillic | serif |
| Merriweather | OFL-1.1 | https://github.com/SorkinType/Merriweather | serif, designed for screens and print |

SIL OFL 1.1 and the GPL font exception both allow embedding the fonts in documents such as the
generated calendars without placing the documents under the font licence. Redistributing the font
files themselves (as this repository does) requires keeping the licence texts alongside, which the
`LICENSE-*.txt` files do.
