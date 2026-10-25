# -*- coding: utf-8 -*-
"""core.languages 테스트."""

import pytest

from core.languages import (
    LANG_TO_ISO,
    TARGET_LANGUAGES,
    _get_iso_lang_code,
    _normalize_lang_name,
)


@pytest.mark.parametrize(
    "name,expected",
    [
        ("Korean", "ko"),
        ("English", "en"),
        ("Simplified Chinese", "zh"),
        ("Japanese", "ja"),
        ("Arabic", "ar"),
        ("Shuddh Hindi", "hi"),
        ("Bahasa Indonesia", "id"),
    ],
)
def test_iso_known_languages(name, expected):
    assert _get_iso_lang_code(name) == expected


def test_iso_empty():
    assert _get_iso_lang_code("") == ""
    assert _get_iso_lang_code(None) == ""


def test_iso_case_insensitive_lookup():
    # LANG_TO_ISO에 직접 없는 표기는 title() 폴백을 탄다
    assert _get_iso_lang_code("korean") == "ko"
    assert _get_iso_lang_code(" JAPANESE ") == "ja"


def test_iso_unknown_falls_back_to_slug():
    # 알 수 없는 언어는 슬러그 폴백 (호출자가 유효성 판단)
    assert _get_iso_lang_code("Klingon") == "klingon"


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("ko", "korean"),
        ("KO", "korean"),
        ("kor", "korean"),
        ("한국어", "korean"),
        ("korean", "korean"),
        ("en", "english"),
        ("eng", "english"),
        ("영어", "english"),
        ("zh", "chinese"),
        ("zho", "chinese"),
        ("chi", "chinese"),
        ("simplified chinese", "chinese"),
        ("ja", "japanese"),
        ("jpn", "japanese"),
        ("hi", "hindi"),
        ("hin", "hindi"),
    ],
)
def test_normalize_variants(raw, expected):
    assert _normalize_lang_name(raw) == expected


def test_normalize_empty():
    assert _normalize_lang_name("") == ""
    assert _normalize_lang_name(None) == ""


def test_normalize_unknown_passthrough():
    # 매핑에 없는 값은 소문자 정규화 형태로 그대로 반환
    assert _normalize_lang_name("Klingon") == "klingon"


def test_target_languages_all_have_iso():
    # UI에서 선택 가능한 모든 언어는 ISO 코드 매핑이 있어야 한다 (mpv 호환)
    missing = [lang for lang in TARGET_LANGUAGES if not LANG_TO_ISO.get(lang)]
    assert not missing, f"ISO 코드 누락: {missing}"


def test_target_languages_normalize_roundtrip():
    # TARGET_LANGUAGES의 각 항목은 정규화 후에도 식별 가능해야 한다
    for lang in TARGET_LANGUAGES:
        norm = _normalize_lang_name(lang)
        assert norm, f"정규화 실패: {lang}"


def test_clean_custom_language_name():
    from core.languages import clean_custom_language_name
    assert clean_custom_language_name("  Vietnamese  ") == "Vietnamese"
    assert clean_custom_language_name("Hong   Kong") == "Hong Kong"
    assert clean_custom_language_name("") == ""
    assert clean_custom_language_name("   ") == ""
    assert clean_custom_language_name(None) == ""


def test_clean_custom_language_name_comma_guard():
    # 설정 저장 구분자(쉼표)와 충돌하지 않도록 공백으로 치환
    from core.languages import clean_custom_language_name
    assert "," not in clean_custom_language_name("Foo, Bar")
    assert clean_custom_language_name("Foo,Bar") == "Foo Bar"


def test_clean_custom_language_name_length_cap():
    from core.languages import clean_custom_language_name
    assert len(clean_custom_language_name("x" * 100)) <= 50


def test_find_language_match():
    from core.languages import find_language_match
    items = ["Korean", "Vietnamese"]
    assert find_language_match("vietnamese", items) == "Vietnamese"
    assert find_language_match("KOREAN", items) == "Korean"
    assert find_language_match("Thai", items) == ""
    assert find_language_match("", items) == ""


def test_custom_language_iso_fallback():
    # 프리셋에 없는 언어도 파일명용 ISO 코드가 비지 않아야 한다
    from core.languages import _get_iso_lang_code
    assert _get_iso_lang_code("Vietnamese") == "vietnamese"


def test_clean_custom_language_name_forbidden_chars():
    # 파일명 금지 문자는 제거되어야 한다 (ISO 코드가 파일명으로 파생됨)
    from core.languages import clean_custom_language_name
    for bad in ['Foo/Bar', 'Foo\\Bar', 'Foo:Bar', 'Foo*Bar', 'Foo?Bar',
                'Foo"Bar', 'Foo<Bar', 'Foo>Bar', 'Foo|Bar']:
        cleaned = clean_custom_language_name(bad)
        for ch in '<>:"/\\|?*':
            assert ch not in cleaned, f"{bad!r} -> {cleaned!r}"
