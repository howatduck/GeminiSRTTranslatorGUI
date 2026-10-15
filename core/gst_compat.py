# -*- coding: utf-8 -*-
"""gemini-srt-translator 라이브러리 호환 레이어.

라이브러리 임포트(실패 시 그레이스풀 디그레이드)와 GUI 안정성을 위한
몽키패치를 모듈 임포트 시점에 적용한다.
"""

# =====================================================================
# [패치] ImportError만 잡으면 하위 의존성이 깨졌을 때(특히 PyInstaller로
# 빌드했을 때 흔함) 원인을 알 수 없으므로 Exception 전체를 잡고, 에러
# 내용을 문자열로 저장해뒀다가 앱 시작 시 사용자에게 팝업으로 보여준다.
# --windowed로 빌드하면 콘솔이 없어서 print()만으로는 원인을 알 수 없다.
# =====================================================================
GST_IMPORT_ERROR = None
try:
    import gemini_srt_translator as gst
except Exception as e:
    print(f"경고: 'gemini-srt-translator' 라이브러리를 찾을 수 없거나 오류가 있습니다. 'pip install gemini-srt-translator'로 설치하세요. ({e})")
    gst = None
    GST_IMPORT_ERROR = repr(e)

GENAI_IMPORT_ERROR = None
try:
    from google import genai
except Exception as e:
    print(f"경고: 'google-genai' 라이브러리를 찾을 수 없습니다. 'pip install google-genai>=2.18.0' 명령어로 설치하세요. ({e})")
    genai = None
    GENAI_IMPORT_ERROR = repr(e)


# =====================================================================
# [패치] gemini-srt-translator 몽키패치 (v3.8.0~v3.8.3 대응)
# 1) f-string backslash 문법 오류 방지
# 2) LLM 응답 JSON 파싱 시 키-값 역전/형변환 실패(ValueError: invalid literal for int) 방지
# 3) ffmpeg_utils sys.exit(1) 방지
# 4) SubtitleSession 타임스탬프 보존 및 원천 싱크 밀림 방지
# =====================================================================
GeminiSRTTranslator = None
Subtitle = None
SubtitleSession = None
install_skill = None
get_skill_path = None

if gst is not None:
    try:
        from gemini_srt_translator.main import GeminiSRTTranslator as _GST
        GeminiSRTTranslator = _GST
        try:
            from gemini_srt_translator.skill import (
                install_skill as _install_skill,
                get_skill_path as _get_skill_path,
            )
            install_skill = _install_skill
            get_skill_path = _get_skill_path
        except ImportError:
            pass
        try:
            from gemini_srt_translator.session import Subtitle as _Sub, SubtitleSession as _SubSession
            Subtitle = _Sub
            SubtitleSession = _SubSession
        except ImportError:
            from gemini_srt_translator.main import Subtitle as _Sub
            Subtitle = _Sub
            SubtitleSession = None
    except Exception:
        pass


# =====================================================================
# [패치] gemini-srt-translator 몽키패치 — 버전별 레지스트리 경유 적용
# (core/gst_patches.py)
#
# Phase (a): 기존 인라인 패치를 버전별 패치셋으로 분리. 적용되는 패치의
# 내용과 순서는 기존과 동일하며, 행위 100% 보존이 목표.
# 미검증 버전에서는 최신 검증 패치셋을 적용하고 경고를 출력한다.
# =====================================================================
_APPLIED_GST_VERSION = None
if gst is not None and GeminiSRTTranslator is not None:
    try:
        from core.gst_patches import apply_patches
        _APPLIED_GST_VERSION = apply_patches(GeminiSRTTranslator, Subtitle, SubtitleSession)
    except Exception:
        pass

_GST_INIT_PARAMS = None
def _get_gst_params():
    global _GST_INIT_PARAMS
    if _GST_INIT_PARAMS is None and GeminiSRTTranslator is not None:
        import inspect as _inspect
        params = set(_inspect.signature(GeminiSRTTranslator.__init__).parameters.keys())
        params.discard('self')
        _GST_INIT_PARAMS = params
    return _GST_INIT_PARAMS or set()


def reset_library_logger():
    """라이브러리(gemini_srt_translator.logger)의 전역 진행 상태 및 이전 메시지 버퍼를 초기화"""
    try:
        import gemini_srt_translator.logger as gst_logger
        gst_logger._has_started = False
        gst_logger._last_chunk_size = 0
        gst_logger._last_printed_lines = 0
        gst_logger._last_progress = None
        gst_logger._line_number = 1
        gst_logger._loading_bars_index = -1
        gst_logger._output_token_count = 0
        if isinstance(getattr(gst_logger, '_previous_messages', None), list):
            gst_logger._previous_messages.clear()
        gst_logger._prompt_token_count = 0
        if isinstance(getattr(gst_logger, '_thoughts_list', None), list):
            gst_logger._thoughts_list.clear()
        gst_logger._thoughts_token_count = 0
        gst_logger._total_token_count = 0
    except Exception:
        pass
