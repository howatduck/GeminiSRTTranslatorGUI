# -*- coding: utf-8 -*-
"""언어 데이터 및 정규화 유틸리티."""

import re

TARGET_LANGUAGES = [
    "Korean", "English", "Bahasa Indonesia", "French", "German", "Spanish",
    "Italian", "Russian", "Simplified Chinese", "Japanese", "Portuguese",
    "Shuddh Hindi", "Arabic"
]

# mpv 등 미디어플레이어 호환 ISO 639-1 언어 코드 매핑
LANG_TO_ISO = {
    "Korean": "ko",
    "English": "en",
    "Bahasa Indonesia": "id",
    "French": "fr",
    "German": "de",
    "Spanish": "es",
    "Italian": "it",
    "Russian": "ru",
    "Simplified Chinese": "zh",
    "Japanese": "ja",
    "Portuguese": "pt",
    "Shuddh Hindi": "hi",
    "Arabic": "ar",
}

def _get_iso_lang_code(lang_name: str) -> str:
    """언어 이름에 대응하는 ISO 639-1 코드 반환 (mpv 호환용)"""
    if not lang_name:
        return ""
    code = LANG_TO_ISO.get(lang_name)
    if not code:
        code = LANG_TO_ISO.get(lang_name.strip().title())
    if not code:
        code = lang_name.strip().lower().replace(" ", "-")
    return code

_LANG_NORM_MAP = {
    "kor": "korean", "ko": "korean", "한국어": "korean", "korean": "korean",
    "eng": "english", "en": "english", "영어": "english", "english": "english",
    "fra": "french", "fre": "french", "fr": "french", "french": "french",
    "deu": "german", "ger": "german", "de": "german", "german": "german",
    "spa": "spanish", "es": "spanish", "spanish": "spanish",
    "ita": "italian", "it": "italian", "italian": "italian",
    "rus": "russian", "ru": "russian", "russian": "russian",
    "zho": "chinese", "chi": "chinese", "zh": "chinese", "chinese": "chinese", "simplified chinese": "chinese",
    "jpn": "japanese", "ja": "japanese", "japanese": "japanese",
    "por": "portuguese", "pt": "portuguese", "portuguese": "portuguese",
    "ara": "arabic", "ar": "arabic", "arabic": "arabic",
    "hin": "hindi", "hi": "hindi", "hindi": "hindi",
    "ind": "indonesian", "id": "indonesian", "indonesian": "indonesian",
}
_LANG_NORM_KEYS_SORTED = sorted(_LANG_NORM_MAP.keys(), key=len, reverse=True)

def _normalize_lang_name(name: str) -> str:
    """언어 코드/이름을 소문자 키워드로 정규화"""
    if not name:
        return ""
    n = name.lower().strip()
    if n in _LANG_NORM_MAP:
        return _LANG_NORM_MAP[n]
    for k in _LANG_NORM_KEYS_SORTED:
        if len(k) <= 3:
            if re.search(rf"(?<![a-z0-9]){re.escape(k)}(?![a-z0-9])", n):
                return _LANG_NORM_MAP[k]
        else:
            if k in n:
                return _LANG_NORM_MAP[k]
    return n
