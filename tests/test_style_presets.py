# -*- coding: utf-8 -*-
"""core.style_presets 테스트."""

from core.style_presets import (
    STYLE_PRESETS,
    compose_description,
    get_preset,
    preset_instruction,
)


def test_ids_unique():
    ids = [p["id"] for p in STYLE_PRESETS]
    assert len(ids) == len(set(ids))


def test_names_present_bilingual():
    for p in STYLE_PRESETS:
        assert p["name_ko"].strip()
        assert p["name_en"].strip()


def test_default_has_empty_instruction():
    assert preset_instruction("default") == ""


def test_non_default_have_instructions():
    for p in STYLE_PRESETS:
        if p["id"] == "default":
            continue
        assert len(p["instruction"].strip()) > 20


def test_get_preset_unknown_falls_back_to_default():
    assert get_preset("no_such_preset")["id"] == "default"


def test_compose_description_both():
    desc = compose_description("주인공은 의사다.", "natural_speech")
    assert "주인공은 의사다." in desc
    assert "Natural Colloquial" in desc


def test_compose_description_preset_only():
    desc = compose_description("", "documentary")
    assert "Documentary Narration" in desc


def test_compose_description_none_when_empty():
    assert compose_description("", "default") is None
    assert compose_description("   ", "default") is None
