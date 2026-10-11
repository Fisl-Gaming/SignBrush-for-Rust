"""Every Russian string wrapped in tr() has an English translation."""

import ast
import re
from pathlib import Path

from signbrush import i18n
from signbrush.gui.help_texts import HELP
from signbrush.gui.help_texts_en import HELP_EN
from signbrush.i18n_en import EN

PKG = Path(i18n.__file__).parent
CYR = re.compile("[А-Яа-яЁё]")
PLACEHOLDER = re.compile(r"\{[^{}]*\}")


def _tr_literals():
    for path in PKG.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "tr"
                    and node.args and isinstance(node.args[0], ast.Constant)
                    and isinstance(node.args[0].value, str)):
                yield path.name, node.args[0].value


def test_every_tr_literal_is_translated():
    missing = [(f, s) for f, s in _tr_literals() if CYR.search(s) and s not in EN]
    assert not missing


def test_translations_keep_placeholders_and_are_english():
    for ru, en in EN.items():
        assert sorted(PLACEHOLDER.findall(ru)) == sorted(PLACEHOLDER.findall(en)), ru
        assert not CYR.search(en), en


def test_help_has_both_languages():
    assert HELP.keys() == HELP_EN.keys()
    for key, d in HELP_EN.items():
        assert set(d) == set(HELP[key]), key
        assert not any(CYR.search(v) for v in d.values()), key


def test_tr_switches_language():
    try:
        i18n.set_language("en")
        assert i18n.tr("Нарисовать") == "Paint"
        assert i18n.tr("нет такого ключа") == "нет такого ключа"
        i18n.set_language("ru")
        assert i18n.tr("Нарисовать") == "Нарисовать"
        i18n.set_language("de")
        assert i18n.language() == "en"
    finally:
        i18n.set_language("ru")
