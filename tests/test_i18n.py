# -*- coding: utf-8 -*-
"""app.i18n 무결성 테스트: 한/영 키 패리티."""

from app.i18n import I18N


def test_languages_present():
    assert "ko" in I18N
    assert "en" in I18N


def test_key_parity():
    # 한쪽에만 있는 키가 있으면 UI 언어 전환 시 KeyError/폴백 발생
    ko_keys = set(I18N["ko"].keys())
    en_keys = set(I18N["en"].keys())
    assert ko_keys == en_keys, (
        f"ko 전용: {sorted(ko_keys - en_keys)}, en 전용: {sorted(en_keys - ko_keys)}"
    )


def test_no_empty_templates():
    for lang, strings in I18N.items():
        empty = [k for k, v in strings.items() if not v]
        assert not empty, f"{lang} 빈 문자열: {empty}"


def test_format_placeholders_safe():
    # {name} 플레이스홀더가 있는 템플릿은 format 호출 시 깨지지 않아야 한다
    import string

    for lang, strings in I18N.items():
        for key, template in strings.items():
            fields = [
                fname for _, fname, _, _ in string.Formatter().parse(template)
                if fname
            ]
            if fields:
                try:
                    template.format(**{f: "X" for f in fields})
                except Exception as e:  # noqa: BLE001
                    raise AssertionError(f"{lang}.{key} 포맷 오류: {e}")
