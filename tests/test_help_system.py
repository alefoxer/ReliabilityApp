from __future__ import annotations

from app.gui.help_content import ABOUT_TEXT, HELP_TOPICS
from app.utils.paths import docs_path


def test_help_topics_cover_main_user_workflows() -> None:
    titles = {title for title, _html in HELP_TOPICS}

    assert "Быстрый старт" in titles
    assert "Графический редактор" in titles
    assert "Калькулятор" in titles
    assert "Справочник / номенклатура" in titles
    assert "Генератор формул" in titles
    assert "Экспорт отчётов" in titles
    assert "Импорт и сохранение" in titles
    assert "Ошибки и FAQ" in titles


def test_help_texts_are_real_content_not_placeholders() -> None:
    combined = ABOUT_TEXT + "\n".join(html for _title, html in HELP_TOPICS)

    assert "TODO" not in combined
    assert "AUTO.COMPOSITION" in combined
    assert "P(t)" in combined
    assert "Kг" in combined
    assert "Демо СНЭ" in combined
    assert "справочник" in combined.lower()
    assert "генератор формул" in combined.lower()


def test_user_guide_exists_and_matches_help_scope() -> None:
    guide = docs_path("USER_GUIDE.md")
    text = guide.read_text(encoding="utf-8")

    assert "Графический редактор" in text
    assert "Калькулятор" in text
    assert "Генератор формул" in text
    assert "Импорт и сохранение" in text
    assert "Экспорт отчётов" in text or "Экспорт отчетов" in text
    assert "Частые вопросы" in text
    assert "Демо СНЭ" in text
