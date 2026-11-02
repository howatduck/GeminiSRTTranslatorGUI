# -*- coding: utf-8 -*-
"""core.media 자막 트랙 선택 테스트 (SDH 우선 옵션)."""

from core.media import (
    _is_forced_stream, _is_sdh_stream, _pick_same_language_stream,
    _pick_translation_stream,
)


def _stream(index, lang="eng", title="", forced=0, hearing=0):
    return {
        "index": index,
        "codec_name": "subrip",
        "disposition": {"forced": forced, "hearing_impaired": hearing},
        "tags": {"language": lang, "title": title},
    }


# ---------- 판별 ----------

def test_is_sdh_by_disposition():
    assert _is_sdh_stream(_stream(1, hearing=1))
    assert not _is_sdh_stream(_stream(1, hearing=0))


def test_is_sdh_by_title():
    assert _is_sdh_stream(_stream(1, title="English SDH"))
    assert _is_sdh_stream(_stream(1, title="English (Hearing Impaired)"))
    assert _is_sdh_stream(_stream(1, title="English [SDH]"))
    assert _is_sdh_stream(_stream(1, title="English CC"))
    assert _is_sdh_stream(_stream(1, title="English Closed Captions"))
    assert not _is_sdh_stream(_stream(1, title="English"))
    # 단어 중간에 낀 'sdh'는 오탐하지 않는다
    assert not _is_sdh_stream(_stream(1, title="English Asdhx"))


def test_is_forced():
    assert _is_forced_stream(_stream(1, forced=1))
    assert _is_forced_stream(_stream(1, title="English Forced"))
    assert not _is_forced_stream(_stream(1))
    # SDH와 forced는 별개 판별이다
    assert not _is_forced_stream(_stream(1, hearing=1))
    assert not _is_sdh_stream(_stream(1, forced=1))


# ---------- 번역용 트랙 선택 ----------

def test_pick_translation_legacy_behavior_without_sdh():
    # 기존 동작 보존: 영어 일반 > 영어 forced > 비영어 일반 > 첫 트랙
    eng_forced = _stream(1, forced=1)
    eng_plain = _stream(2)
    kor_plain = _stream(3, lang="kor")
    assert _pick_translation_stream([eng_forced, eng_plain, kor_plain]) is eng_plain
    assert _pick_translation_stream([eng_forced, kor_plain]) is eng_forced
    assert _pick_translation_stream([kor_plain, eng_forced]) is eng_forced
    kor_forced = _stream(4, lang="kor", forced=1)
    assert _pick_translation_stream([kor_forced, kor_plain]) is kor_plain
    assert _pick_translation_stream([kor_forced]) is kor_forced


def test_pick_translation_default_prefers_regular_over_sdh():
    eng_sdh = _stream(1, title="English SDH")
    eng_plain = _stream(2)
    # 순서와 무관하게 일반 자막 우선
    assert _pick_translation_stream([eng_sdh, eng_plain]) is eng_plain
    assert _pick_translation_stream([eng_plain, eng_sdh]) is eng_plain
    kor = _stream(3, lang="kor")
    assert _pick_translation_stream([kor, eng_sdh, eng_plain]) is eng_plain


def test_pick_translation_prefer_sdh():
    eng_sdh = _stream(1, hearing=1)
    eng_plain = _stream(2)
    assert _pick_translation_stream([eng_plain, eng_sdh], prefer_sdh=True) is eng_sdh
    # 언어 우선순위는 SDH 선호보다 위: 영어 일반 > 비영어 SDH
    kor_sdh = _stream(3, lang="kor", hearing=1)
    assert _pick_translation_stream([kor_sdh, eng_plain], prefer_sdh=True) is eng_plain


def test_pick_translation_sdh_only():
    eng_sdh = _stream(1, title="SDH")
    assert _pick_translation_stream([eng_sdh]) is eng_sdh
    assert _pick_translation_stream([eng_sdh], prefer_sdh=True) is eng_sdh


def test_pick_translation_empty():
    assert _pick_translation_stream([]) is None


def test_pick_translation_forced_sdh_combinations():
    forced_sdh = _stream(1, title="English Forced SDH", forced=1)
    forced_plain = _stream(2, title="English Forced", forced=1)
    # forced끼리는 SDH 정책이 갈린다
    assert _pick_translation_stream([forced_sdh, forced_plain]) is forced_plain
    assert _pick_translation_stream(
        [forced_plain, forced_sdh], prefer_sdh=True) is forced_sdh


def test_pick_translation_non_english_sdh_policy():
    kor_sdh = _stream(1, lang="kor", hearing=1)
    kor_plain = _stream(2, lang="kor")
    assert _pick_translation_stream([kor_sdh, kor_plain]) is kor_plain
    assert _pick_translation_stream(
        [kor_plain, kor_sdh], prefer_sdh=True) is kor_sdh


def test_pick_translation_unknown_language_tracks():
    und_forced = _stream(1, lang="und", forced=1)
    und_plain = _stream(2, lang="und")
    assert _pick_translation_stream([und_forced, und_plain]) is und_plain
    assert _pick_translation_stream([und_plain, und_forced]) is und_plain


# ---------- 목표 언어 직접 추출 선택 ----------

def test_pick_same_language_default_prefers_regular():
    kor_sdh = _stream(1, lang="kor", title="Korean SDH")
    kor_plain = _stream(2, lang="kor")
    targets = {"Korean": "korean"}
    s, lang = _pick_same_language_stream([kor_sdh, kor_plain], targets)
    assert s is kor_plain and lang == "Korean"
    s, lang = _pick_same_language_stream([kor_plain, kor_sdh], targets)
    assert s is kor_plain


def test_pick_same_language_prefer_sdh():
    kor_sdh = _stream(1, lang="kor", hearing=1)
    kor_plain = _stream(2, lang="kor")
    s, _ = _pick_same_language_stream(
        [kor_plain, kor_sdh], {"Korean": "korean"}, prefer_sdh=True)
    assert s is kor_sdh


def test_pick_same_language_no_match():
    eng = _stream(1, lang="eng")
    s, lang = _pick_same_language_stream([eng], {"Korean": "korean"})
    assert s is None and lang is None


def test_pick_same_language_forced_is_last_resort():
    kor_forced = _stream(1, lang="kor", title="Korean Forced", forced=1)
    kor_sdh = _stream(2, lang="kor", hearing=1)
    kor_plain = _stream(3, lang="kor")
    targets = {"Korean": "korean"}
    # 기본: forced는 SDH보다도 뒤 (부분 자막 회피)
    s, _ = _pick_same_language_stream([kor_forced, kor_sdh], targets)
    assert s is kor_sdh
    s, _ = _pick_same_language_stream([kor_forced, kor_plain], targets)
    assert s is kor_plain
    # SDH 우선이어도 forced가 일반 SDH를 이기지는 않는다
    s, _ = _pick_same_language_stream(
        [kor_forced, kor_plain], targets, prefer_sdh=True)
    assert s is kor_plain


def test_pick_same_language_multi_target_order_preserved():
    kor_sdh = _stream(1, lang="kor", hearing=1)
    eng_plain = _stream(2, lang="eng")
    # 목표 언어를 한국어를 먼저 지정하면 SDH여도 한국어가 유지된다
    targets = {"Korean": "korean", "English": "english"}
    s, lang = _pick_same_language_stream([kor_sdh, eng_plain], targets)
    assert s is kor_sdh and lang == "Korean"
    # 영어 먼저 지정이면 영어가 이긴다
    targets = {"English": "english", "Korean": "korean"}
    s, lang = _pick_same_language_stream([kor_sdh, eng_plain], targets)
    assert s is eng_plain and lang == "English"
