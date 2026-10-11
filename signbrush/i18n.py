"""Tiny i18n: Russian source strings, English translations in :mod:`i18n_en`.

``tr("Текст {0}")`` returns the string for the current language. Templates use
``str.format`` placeholders, so ``tr("Загружено: {0}").format(name)``.
"""

from __future__ import annotations

LANGUAGES = {"ru": "RU", "en": "EN"}
_lang = "ru"


def system_language() -> str:
    try:
        from PyQt6.QtCore import QLocale
        return "ru" if QLocale.system().name().lower().startswith(("ru", "uk", "be", "kk")) else "en"
    except Exception:
        import locale
        loc = (locale.getlocale()[0] or "").lower()
        return "ru" if loc.startswith(("ru", "russian")) else "en"


def set_language(code: str) -> None:
    global _lang
    _lang = code if code in LANGUAGES else "en"


def language() -> str:
    return _lang


def tr(text: str) -> str:
    if _lang == "ru" or not text:
        return text
    from .i18n_en import EN
    return EN.get(text, text)
