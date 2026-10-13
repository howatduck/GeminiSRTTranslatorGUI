# -*- coding: utf-8 -*-
"""core.style_presets 테스트."""

from core.style_presets import (
    STYLE_PRESETS,
    CUSTOM_PRESET_COUNT,
    CUSTOM_PRESET_IDS,
    all_presets,
    compose_description,
    custom_slot_index,
    default_custom_name,
    get_preset,
    is_custom_preset,
    preset_instruction,
    resolve_custom_preset,
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


def test_custom_preset_ids():
    assert CUSTOM_PRESET_COUNT == 3
    assert CUSTOM_PRESET_IDS == ["custom_1", "custom_2", "custom_3"]
    assert all(is_custom_preset(pid) for pid in CUSTOM_PRESET_IDS)
    assert not is_custom_preset("default")
    assert custom_slot_index("custom_2") == 1
    assert custom_slot_index("default") is None


def test_default_custom_name():
    assert default_custom_name(0, "ko") == "커스텀 1"
    assert default_custom_name(2, "en") == "Custom 3"


def test_resolve_custom_preset_empty():
    p = resolve_custom_preset("custom_1", {}, "ko")
    assert p["name"] == "커스텀 1"
    assert p["instruction"] == ""
    assert preset_instruction("custom_1", {}) == ""


def test_resolve_custom_preset_filled():
    data = {"custom_2": {"name": "내 스타일", "instruction": "반말로 번역해라."}}
    p = resolve_custom_preset("custom_2", data, "ko")
    assert p["name"] == "내 스타일"
    assert preset_instruction("custom_2", data) == "반말로 번역해라."
    desc = compose_description("", "custom_2", data)
    assert "반말로 번역해라." in desc


def test_resolve_custom_preset_blank_name_uses_default():
    data = {"custom_3": {"name": "   ", "instruction": "x"}}
    assert resolve_custom_preset("custom_3", data, "en")["name"] == "Custom 3"


def test_all_presets_includes_custom():
    presets = all_presets({}, "ko")
    assert len(presets) == len(STYLE_PRESETS) + 3
    assert presets[-1]["id"] == "custom_3"


def test_builtin_unaffected_by_custom_data():
    data = {"custom_1": {"name": "x", "instruction": "y"}}
    assert "Natural Colloquial" in preset_instruction("natural_speech", data)
