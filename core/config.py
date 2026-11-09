# -*- coding: utf-8 -*-
"""애플리케이션 전역 상수."""

# --- 상수 정의 ---
APP_NAME = "Gemini SRT 번역/전사 GUI"
SETTINGS_ORG = "GeminiSrtTranslatorGUI"
SETTINGS_APP = "GeminiSrtTranslatorGUI"
NUM_API_KEYS = 10
API_KEY_SETTINGS = [f"gemini_api_key_{i+1}" for i in range(NUM_API_KEYS)]
DEFAULT_MODEL = "gemini-3.5-flash-lite"
DEFAULT_BATCH_SIZE = 1000

# 텍스트 생성(번역)에 쓸 수 없는 모델 이름 표지 — 임베딩·이미지·영상·
# 음성 합성·음악 생성 전용이거나 실시간 오디오/로보틱스/컴퓨터 조작/
# 리서치 에이전트 같은 특수 용도 모델은 모델 목록과 폴백 순서에서
# 애초에 제외한다. generateContent를 지원해도 용도가 다른 모델이
# 섞여 들어오기 때문에 이름으로 한 번 더 거른다.
_NON_TEXT_MODEL_MARKERS = (
    "embedding",     # 임베딩 전용
    "imagen",        # 이미지 생성
    "veo",           # 영상 생성
    "tts",           # 음성 합성 전용
    "image",         # 이미지 출력 (gemini-2.5-flash-image 등)
    "native-audio",  # 실시간 오디오 전용
    "live",          # 실시간 API 전용 (gemini-live-*)
    "robotics",      # 로보틱스 전용
    "computer-use",  # 컴퓨터 조작 전용
    "deep-research",  # 리서치 에이전트 전용
    "lyria",         # 음악 생성
    "aqa",           # 구형 AQA 전용
    "omni",          # 동영상 생성·편집 (gemini-omni-*-flash, Interactions API 전용)
    "banana",        # 이미지 생성 (gemini-nano-banana-* — 이름에 image가 없음)
)


def is_text_model(name):
    """이름 기준 텍스트 생성 모델 여부. 'models/' 접두사는 무시한다."""
    n = str(name or "").replace("models/", "").strip().lower()
    if not n:
        return False
    return not any(marker in n for marker in _NON_TEXT_MODEL_MARKERS)
