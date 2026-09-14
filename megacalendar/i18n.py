"""UI text translation: a simple per-language JSON catalog (English source string -> translated
string), not a database of any kind. Both templates (as the Jinja global `_`) and Python code can
call `t(message)` / `_(message)`; the current request's language lives in a contextvar set by
main.py's middleware, so it's safe under concurrent requests in different languages.

To add a language:
  1. Add (code, native name) to LANGUAGES below.
  2. Create megacalendar/locale/<code>.json: a flat {"English source string": "translation"} map.
     Missing keys silently fall back to the English source text, so a translation can be added
     incrementally and is never a hard requirement for every string to be covered upfront.
  3. Extend the "%(placeholder)s"-style values exactly like the English source; t() substitutes
     keyword arguments with str.format after translation, so translators may reorder them.
"""
from __future__ import annotations

import json
from contextvars import ContextVar
from functools import lru_cache
from pathlib import Path

LOCALE_DIR = Path(__file__).parent / "locale"

# (code, name written in that language, so a reader who doesn't know the current UI language
# can still recognise their own in the picker)
LANGUAGES: list[tuple[str, str]] = [
    ("en", "English"),
    ("pl", "Polski"),
]
LANGUAGE_CODES = {code for code, _ in LANGUAGES}
DEFAULT_LANGUAGE = "en"

_current: ContextVar[str] = ContextVar("ui_language", default=DEFAULT_LANGUAGE)


@lru_cache(maxsize=None)
def _catalog(lang: str) -> dict[str, str]:
    path = LOCALE_DIR / f"{lang}.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def set_language(lang: str) -> None:
    _current.set(lang if lang in LANGUAGE_CODES else DEFAULT_LANGUAGE)


def get_language() -> str:
    return _current.get()


def t(message: str, **kwargs) -> str:
    """Translate `message` to the current request's language. Falls back to the English source
    (verbatim) for untranslated or unknown strings, so a partial catalog never breaks the page."""
    lang = _current.get()
    text = message if lang == DEFAULT_LANGUAGE else _catalog(lang).get(message, message)
    return text.format(**kwargs) if kwargs else text


def best_match(accept_language: str | None) -> str | None:
    """The first supported language in an Accept-Language header, or None if it names none."""
    if not accept_language:
        return None
    for part in accept_language.split(","):
        code = part.split(";")[0].strip().split("-")[0].lower()
        if code in LANGUAGE_CODES:
            return code
    return None
