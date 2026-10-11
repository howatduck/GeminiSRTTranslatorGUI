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
