# -*- coding: utf-8 -*-
"""
Gemini SRT Translator GUI (v3.8.3 호환, Pyte VT100 터미널)
v3.8.0 ~ v3.8.3 최신 변경사항 반영 (SubtitleSession 엔진, 적응형 배치/오디오청크 감축, context_size 통일 등)
"""

import sys
import builtins
# [패치] PyInstaller windowed 모드에서 exit()가 없는 문제 방지
try:
    exit
except NameError:
    builtins.exit = sys.exit

import os
import re
import queue
import threading
import io
import time
import signal
import logging
import itertools
import unicodedata

# =====================================================================
# [FFmpeg 번들 경로 자동 등록] (PyInstaller sys._MEIPASS 또는 EXE 디렉토리)
# =====================================================================
def _setup_ffmpeg_path():
    search_dirs = []
    if getattr(sys, 'frozen', False):
        if hasattr(sys, '_MEIPASS'):
            search_dirs.append(sys._MEIPASS)
        exe_dir = os.path.dirname(sys.executable)
        search_dirs.append(exe_dir)
        search_dirs.append(os.path.join(exe_dir, 'ffmpeg'))
    else:
        app_dir = os.path.dirname(os.path.abspath(__file__)) if '__file__' in globals() else os.getcwd()
        search_dirs.append(app_dir)
        search_dirs.append(os.path.join(app_dir, 'ffmpeg'))

    current_path = os.environ.get("PATH", "")
    for d in search_dirs:
        if os.path.exists(d):
            ffmpeg_exe = os.path.join(d, "ffmpeg.exe" if sys.platform == "win32" else "ffmpeg")
            ffprobe_exe = os.path.join(d, "ffprobe.exe" if sys.platform == "win32" else "ffprobe")
            if os.path.exists(ffmpeg_exe) or os.path.exists(ffprobe_exe):
                if d not in current_path:
                    os.environ["PATH"] = d + os.pathsep + current_path
                    current_path = os.environ["PATH"]
                # pydub 경로 강제 지정
                try:
                    import pydub.utils
                    if os.path.exists(ffmpeg_exe):
                        pydub.AudioSegment.converter = ffmpeg_exe
                    if os.path.exists(ffprobe_exe):
                        pydub.utils.get_prober_name = lambda: ffprobe_exe
                except Exception:
                    pass

_setup_ffmpeg_path()

# =====================================================================
# [패치 1] GUI 환경 및 워커 스레드 안전화 패치
# 1) signal.signal 및 signal.raise_signal: 메인 스레드가 아니거나 오류 시 예외 방지
#    특히 라이브러리가 과부하/오류 3회 초과 시 signal.raise_signal(signal.SIGINT)를 호출하여
#    메인 프로세스 전체를 비정상 종료(SIGINT/중지됨)시키는 현상을 방지
# 2) exit/sys.exit: 워커 스레드에서 exit() 호출 시 전체 GUI 앱이 강제 종료되지 않고
#    WorkerLibraryExit 예외를 발생시켜 번역 워커의 작업 재시도/실패 처리 로직으로 안전하게 회수
# =====================================================================
class WorkerLibraryExit(RuntimeError):
    """라이브러리가 exit()를 호출하여 프로세스를 종료하려 할 때 워커 스레드에서 발생하는 안전 예외"""
    def __init__(self, code=0):
        self.code = code
        super().__init__(f"라이브러리가 종료(exit {code})를 요청했습니다.")

_original_sys_exit = sys.exit

def _safe_app_exit(code=0):
    if threading.current_thread() is threading.main_thread():
        _original_sys_exit(code)
    else:
        raise WorkerLibraryExit(code)

builtins.exit = _safe_app_exit
sys.exit = _safe_app_exit

_original_signal = signal.signal
def _safe_signal(signalnum, handler):
    try:
        # 워커 스레드에서는 signal 핸들러 등록을 시도하지 않고 무시
        if threading.current_thread() is not threading.main_thread():
            return None
        return _original_signal(signalnum, handler)
    except (ValueError, OSError, RuntimeError):
        return None

signal.signal = _safe_signal

if hasattr(signal, 'raise_signal'):
    def _safe_raise_signal(signum):
        # 라이브러리가 모델 오버로드 3회, 연속 오류 초과 등으로 SIGINT를 발생시킬 때
        # GUI 프로세스 전체를 종료하지 않고 WorkerLibraryExit를 던져 안전하게 처리
        if threading.current_thread() is not threading.main_thread():
            raise WorkerLibraryExit(130)
        try:
            return _original_signal(signum, signal.SIG_DFL)
        except (ValueError, OSError, RuntimeError):
            pass
    signal.raise_signal = _safe_raise_signal


# --- 필수 라이브러리 임포트 및 확인 ---
try:
    from PyQt6.QtWidgets import (
        QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
        QPushButton, QFileDialog, QComboBox, QSpinBox, QCheckBox, QTextEdit,
        QMessageBox, QGroupBox, QFormLayout, QListWidget, QListWidgetItem,
        QSizePolicy, QFrame, QDoubleSpinBox, QProgressBar,
        QToolButton, QScrollArea, QLayout, QDialog
    )
    from PyQt6.QtCore import Qt, QSettings, QThread, pyqtSignal, QObject, QTimer
    from PyQt6.QtGui import QFont, QTextCursor, QTextCharFormat, QColor, QStandardItemModel, QStandardItem
except ImportError:
    print("치명적 오류: 'PyQt6' 라이브러리를 찾을 수 없습니다. 'pip install PyQt6' 명령어로 설치하세요.")
    sys.exit(1)

try:
    import pyte
except ImportError:
    print("치명적 오류: 'pyte' 라이브러리를 찾을 수 없습니다.\n'pip install pyte' 명령어로 설치하세요.")
    sys.exit(1)

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

# --- 상수 정의 ---
APP_NAME = "Gemini SRT 번역/전사 GUI"
SETTINGS_ORG = "GeminiSrtTranslatorGUI"
SETTINGS_APP = "GeminiSrtTranslatorGUI"
NUM_API_KEYS = 10
API_KEY_SETTINGS = [f"gemini_api_key_{i+1}" for i in range(NUM_API_KEYS)]

TARGET_LANGUAGES = [
    "Korean", "English", "Bahasa Indonesia", "French", "German", "Spanish",
    "Italian", "Russian", "Simplified Chinese", "Japanese", "Portuguese",
    "Shuddh Hindi", "Arabic"
]
DEFAULT_MODEL = "gemini-3.5-flash-lite"
DEFAULT_BATCH_SIZE = 1000

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

if gst is not None:
    try:
        from gemini_srt_translator.main import GeminiSRTTranslator as _GST
        GeminiSRTTranslator = _GST
        try:
            from gemini_srt_translator.session import Subtitle as _Sub, SubtitleSession as _SubSession
            Subtitle = _Sub
            SubtitleSession = _SubSession
        except ImportError:
            from gemini_srt_translator.main import Subtitle as _Sub
            Subtitle = _Sub
            SubtitleSession = None

        import pysubs2
        import json_repair
        from datetime import timedelta

        def _patched_parse_subtitle_file(file_path: str) -> list:
            subs = pysubs2.load(file_path, encoding="utf-8", keep_html_tags=True)
            srt_subs = []
            for i, ev in enumerate(subs):
                text = ev.text.replace(r"\N", "\n").replace(r"\n", "\n")
                srt_subs.append(
                    Subtitle(
                        index=i + 1,
                        start=timedelta(milliseconds=ev.start),
                        end=timedelta(milliseconds=ev.end),
                        content=text,
                    )
                )
            return srt_subs

        def _patched_save_subtitle_file(*args, **kwargs):
            # 싱크 버그 방지: Subtitle 객체에 저장된 원본 start/end 타임스탬프를
            # 직접 사용하여 SRT 형식으로 안전하게 기록
            #
            # 하위/상위 버전 라이브러리 호출 시그니처 모두 호환:
            # 1) v3.8.3 SubtitleSession: (input_file: str, translated_subtitle: list, output_file: str)
            # 2) v3.7.x GeminiSRTTranslator 인스턴스 메서드: (self, translated_subtitle: list, output_file: str)
            # 3) v3.7.x _write_translated_subtitles: (self, translated_subtitle: list) [output_file은 self.output_file]
            if len(args) == 3:
                input_file, translated_subtitle, output_file = args
            elif len(args) == 2:
                first, second = args
                if isinstance(first, str):
                    input_file = first
                    translated_subtitle = second
                    output_file = kwargs.get('output_file') or getattr(second, 'output_file', None) or input_file
                else:
                    # first is self
                    input_file = getattr(first, 'input_file', '')
                    translated_subtitle = second
                    output_file = kwargs.get('output_file') or getattr(first, 'output_file', '')
            elif len(args) == 1:
                first = args[0]
                if isinstance(first, list):
                    input_file = kwargs.get('input_file', '')
                    translated_subtitle = first
                    output_file = kwargs.get('output_file', '')
                else:
                    input_file = getattr(first, 'input_file', '')
                    translated_subtitle = getattr(first, 'translated_subtitle', []) or getattr(first, 'translated_subtitles', [])
                    output_file = getattr(first, 'output_file', '')
            else:
                input_file = kwargs.get('input_file', '')
                translated_subtitle = kwargs.get('translated_subtitle', [])
                output_file = kwargs.get('output_file', '')

            def _ms_to_srt(td):
                if hasattr(td, 'total_seconds'):
                    total_ms = int(round(td.total_seconds() * 1000))
                elif isinstance(td, (int, float)):
                    total_ms = int(round(td))
                else:
                    total_ms = 0
                if total_ms < 0:
                    total_ms = 0
                h = total_ms // 3_600_000
                m = (total_ms % 3_600_000) // 60_000
                s = (total_ms % 60_000) // 1_000
                ms = total_ms % 1_000
                return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

            ext = os.path.splitext(output_file)[1].lower() if output_file else ".srt"
            temp_dir = os.path.dirname(os.path.abspath(output_file)) if output_file else "."
            temp_dir = temp_dir or "."
            os.makedirs(temp_dir, exist_ok=True)
            temp_out = os.path.join(temp_dir, f".tmp_{os.path.basename(output_file)}") if output_file else ".tmp_sub.srt"

            if ext == ".srt":
                lines = []
                for i, sub in enumerate(translated_subtitle, start=1):
                    start_str = _ms_to_srt(sub.start)
                    end_str = _ms_to_srt(sub.end)
                    text = sub.content.replace(r"\N", "\n").replace(r"\n", "\n").strip("\r\n")
                    lines.append(f"{i}\n{start_str} --> {end_str}\n{text}\n")
                with open(temp_out, "w", encoding="utf-8") as f:
                    f.write("\n".join(lines) + "\n")
                os.replace(temp_out, output_file)
            else:
                # ASS/SSA 등 다른 형식은 pysubs2를 사용하여 저장
                subs = pysubs2.load(input_file, encoding="utf-8")
                # 순서(position) 기반으로 매핑하여 싱크 보장
                sorted_subs = sorted(translated_subtitle, key=lambda s: s.index)
                for i, sub in enumerate(sorted_subs):
                    if i < len(subs):
                        subs[i].text = sub.content.replace("\n", r"\N")
                subs.save(temp_out, encoding="utf-8")
                os.replace(temp_out, output_file)

        def _patched_process_translated_lines(
            self,
            translated_lines: list,
            translated_subtitle: list,
            batch: list,
            finished: bool,
        ) -> bool:
            """
            AI 응답 라인을 자막 객체에 매핑할 때,
            배치 순서(position i)를 우선하여 AI 인덱스 왜곡(1-based, int/str 불일치)으로 인한
            싱크 밀림 현상을 원천 방지
            """
            if not translated_lines:
                raise ValueError("Gemini has returned an empty translation.")

            last_translated_line = translated_lines[-1]
            for i, line in enumerate(translated_lines):
                if not isinstance(line, dict) or "text" not in line:
                    if line != last_translated_line or finished:
                        raise ValueError(f"Gemini has returned a malformed object at item {i + 1}.")
                    else:
                        continue

                text = str(line.get("text", ""))

                # 핵심: batch[i]의 고유 index를 우선 매핑하여 인덱스 왜곡/오프셋 방지
                if i < len(batch):
                    target_idx = int(batch[i]["index"])
                else:
                    try:
                        target_idx = int(str(line.get("index", i)))
                    except (ValueError, TypeError):
                        target_idx = i

                if 0 <= target_idx < len(translated_subtitle):
                    if hasattr(self, '_dominant_strong_direction') and self._dominant_strong_direction(text) == "rtl":
                        translated_subtitle[target_idx].content = f"\u202b{text}\u202c"
                    else:
                        translated_subtitle[target_idx].content = text

        def _patched_parse_response(self, response_text: str, batch: list) -> list:
            """LLM 응답을 안전하게 파싱하여 번역된 Subtitle 리스트 반환 (형변환 오류 완벽 방어)"""
            parsed = json_repair.loads(response_text)
            translated_dict = {}

            if isinstance(parsed, dict):
                for k, v in parsed.items():
                    # 1) 정상 형태: key가 인덱스 숫자, value가 번역 텍스트
                    try:
                        k_int = int(str(k).strip())
                        translated_dict[k_int] = str(v)
                        continue
                    except (ValueError, TypeError):
                        pass

                    # 2) 역전 형태: value가 인덱스 숫자, key가 번역 텍스트
                    try:
                        v_int = int(str(v).strip())
                        translated_dict[v_int] = str(k)
                        continue
                    except (ValueError, TypeError):
                        pass

            elif isinstance(parsed, list):
                for item in parsed:
                    if isinstance(item, dict):
                        for k, v in item.items():
                            try:
                                k_int = int(str(k).strip())
                                translated_dict[k_int] = str(v)
                            except (ValueError, TypeError):
                                pass

            # batch의 각 subtitle에 매핑 (누락 시 원본 유지)
            result = []
            for i, sub in enumerate(batch):
                if sub.index in translated_dict:
                    new_content = translated_dict[sub.index]
                elif (i + 1) in translated_dict:
                    new_content = translated_dict[i + 1]
                elif isinstance(parsed, list) and i < len(parsed) and isinstance(parsed[i], str):
                    new_content = parsed[i]
                else:
                    new_content = sub.content
                result.append(
                    Subtitle(
                        index=sub.index,
                        start=sub.start,
                        end=sub.end,
                        content=new_content,
                    )
                )
            return result

        # GeminiSRTTranslator 패치 등록
        # 1) _save_subtitle_file: 구버전(v3.7.x) 및 신버전(v3.8.x) 모두에서 안전하게 호출되도록 등록
        GeminiSRTTranslator._save_subtitle_file = _patched_save_subtitle_file
        if hasattr(GeminiSRTTranslator, '_process_translated_lines'):
            GeminiSRTTranslator._process_translated_lines = _patched_process_translated_lines
        if hasattr(GeminiSRTTranslator, '_parse_response'):
            GeminiSRTTranslator._parse_response = _patched_parse_response

        # [패치] GeminiSRTTranslator._process_batch: chunk.candidates[0].content가 None일 때
        # AttributeError 방지 (google-genai >= 2.18에서 빈 청크 발생)
        if hasattr(GeminiSRTTranslator, '_process_batch'):
            _original_gst_process_batch = GeminiSRTTranslator._process_batch

            def _patched_gst_process_batch(self, *args, **kwargs):
                try:
                    return _original_gst_process_batch(self, *args, **kwargs)
                except (AttributeError, IndexError, TypeError) as _chunk_err:
                    _err_msg = str(_chunk_err)
                    if 'content' in _err_msg or 'candidates' in _err_msg or 'parts' in _err_msg:
                        raise RuntimeError(
                            f"Gemini API 스트림 청크 오류 (빈 응답 청크): {_chunk_err}"
                        ) from _chunk_err
                    raise

            GeminiSRTTranslator._process_batch = _patched_gst_process_batch

        # SubtitleSession 패치 등록 (v3.8.x 신규 클래스)
        if SubtitleSession is not None:
            # SubtitleSession._save_subtitle_file: SRT 싱크 보장 패치
            SubtitleSession._save_subtitle_file = staticmethod(_patched_save_subtitle_file)
            if hasattr(SubtitleSession, '_process_batch'):
                _original_session_process_batch = SubtitleSession._process_batch

                def _patched_session_process_batch(self, *args, **kwargs):
                    try:
                        return _original_session_process_batch(self, *args, **kwargs)
                    except (AttributeError, IndexError, TypeError) as _chunk_err:
                        _err_msg = str(_chunk_err)
                        if 'content' in _err_msg or 'candidates' in _err_msg or 'parts' in _err_msg:
                            raise RuntimeError(
                                f"Gemini API 스트림 청크 오류 (빈 응답 청크): {_chunk_err}"
                            ) from _chunk_err
                        raise

                SubtitleSession._process_batch = _patched_session_process_batch

        # [패치] gemini-3.5-flash-lite 등 모델에서 영어 -> 한국어 번역 시 영어가 그대로 출력되는 현상 방지
        # 대상 언어가 한국어인 경우 한글(Hangul)로 반드시 번역하도록 명시적 지침 추가
        import gemini_srt_translator.helpers as gst_helpers
        if hasattr(gst_helpers, 'get_translate_instruction'):
            _orig_get_translate_instruction = gst_helpers.get_translate_instruction

            def _patched_get_translate_instruction(language, thinking, thinking_compatible, audio_file=None, description=None):
                prompt = _orig_get_translate_instruction(language, thinking, thinking_compatible, audio_file=audio_file, description=description)
                norm_l = (language or "").strip().lower()
                if norm_l in ("korean", "한국어", "ko", "kor"):
                    korean_rule = (
                        "\n---\n## 3.1. Language Requirement (STRICT)\n"
                        "- **Target Language**: Every line of the `text` field MUST be translated into natural **Korean (한국어/한글)**.\n"
                        "- **CRITICAL**: Do NOT leave the subtitle text in English or the original language. Translate the meaning faithfully into fluent Korean."
                    )
                    prompt += korean_rule
                return prompt

            gst_helpers.get_translate_instruction = _patched_get_translate_instruction

            # SubtitleSession 모듈에서도 이미 임포트된 참조 업데이트
            try:
                import gemini_srt_translator.session as gst_session
                gst_session.get_translate_instruction = _patched_get_translate_instruction
            except Exception:
                pass
            try:
                import gemini_srt_translator.main as gst_main
                gst_main.get_translate_instruction = _patched_get_translate_instruction
            except Exception:
                pass

        # [패치] ffmpeg_utils._run_command에서 sys.exit(1) 호출 방지 (GUI 크래시 방지)
        try:
            import gemini_srt_translator.ffmpeg_utils as ff_utils
            def _patched_run_command(cmd, capture_output=True, text=True):
                import subprocess
                try:
                    return subprocess.run(cmd, capture_output=capture_output, text=text, check=True, encoding="utf-8", errors="replace")
                except FileNotFoundError:
                    raise RuntimeError(f"FFmpeg 실행 파일을 찾을 수 없습니다: '{cmd[0]}'. FFmpeg를 설치하고 PATH에 추가하세요.")
                except subprocess.CalledProcessError as e:
                    err_detail = e.stderr.strip() if getattr(e, 'stderr', None) else str(e)
                    raise RuntimeError(f"FFmpeg 실행 오류 ({' '.join(cmd[:2])}...): {err_detail}")

            ff_utils._run_command = _patched_run_command
        except Exception:
            pass

        # [패치] consecutive error 발생 시 배치 사이즈 및 오디오 청크 감소 방지
        # _reduce_batch_size, _reduce_transcribe_chunk_size를 no-op으로 대체하여 크기를 항상 유지
        def _noop_reduce(self, *args, **kwargs):
            pass

        GeminiSRTTranslator._reduce_batch_size = _noop_reduce
        if hasattr(GeminiSRTTranslator, '_reduce_transcribe_chunk_size'):
            GeminiSRTTranslator._reduce_transcribe_chunk_size = _noop_reduce

    except Exception as _patch_err:
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


# =====================================================================
# [미디어/자막 헬퍼 함수] FFprobe 및 FFmpeg를 통한 자막 트랙 검사 및 추출
# =====================================================================
def _get_video_subtitle_streams(video_path: str) -> list:
    """ffprobe를 통해 비디오 파일 내의 모든 자막 스트림 정보 반환"""
    import subprocess, json
    cmd = [
        "ffprobe", "-v", "error",
        "-select_streams", "s",
        "-show_entries", "stream=index,codec_name,disposition:stream_tags=language,title",
        "-of", "json",
        video_path
    ]
    try:
        startupinfo = None
        if sys.platform == "win32":
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        res = subprocess.run(
            cmd, capture_output=True, text=True, check=True,
            encoding="utf-8", errors="replace", startupinfo=startupinfo
        )
        data = json.loads(res.stdout)
        return data.get("streams", [])
    except Exception:
        return []

def _get_media_duration(file_path: str) -> float:
    """ffprobe를 통해 미디어 파일의 총 재생 시간(초) 반환"""
    import subprocess
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        file_path
    ]
    try:
        startupinfo = None
        if sys.platform == "win32":
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        res = subprocess.run(
            cmd, capture_output=True, text=True, check=True,
            encoding="utf-8", errors="replace", startupinfo=startupinfo
        )
        return float(res.stdout.strip())
    except Exception:
        return 0.0

def _extract_subtitle_track(video_path: str, stream_index: int, output_srt_path: str, progress_callback=None) -> bool:
    """ffmpeg를 사용하여 지정된 자막 스트림을 .srt 파일로 추출 (실시간 진행률 콜백 지원)"""
    import subprocess
    total_duration = _get_media_duration(video_path) if progress_callback else 0.0

    out_dir = os.path.dirname(os.path.abspath(output_srt_path))
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    cmd = [
        "ffmpeg", "-y", "-v", "error",
        "-i", video_path,
        "-map", f"0:{stream_index}",
        "-c:s", "srt",
    ]
    if progress_callback:
        cmd.extend(["-progress", "pipe:1", "-nostats"])
    cmd.append(output_srt_path)

    try:
        startupinfo = None
        if sys.platform == "win32":
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

        if progress_callback:
            process = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, encoding="utf-8", errors="replace", startupinfo=startupinfo
            )
            for line in process.stdout:
                line = line.strip()
                if line.startswith("out_time_us="):
                    try:
                        us = int(line.split("=", 1)[1])
                        curr_sec = us / 1_000_000.0
                        if total_duration > 0:
                            pct = min(100.0, max(0.0, (curr_sec / total_duration) * 100.0))
                            progress_callback(pct, curr_sec, total_duration)
                    except (ValueError, TypeError):
                        pass
                elif line.startswith("progress="):
                    val = line.split("=", 1)[1]
                    if val == "end" and total_duration > 0:
                        progress_callback(100.0, total_duration, total_duration)
            process.wait()
            return process.returncode == 0 and os.path.exists(output_srt_path) and os.path.getsize(output_srt_path) > 0
        else:
            subprocess.run(
                cmd, capture_output=True, text=True, check=True,
                encoding="utf-8", errors="replace", startupinfo=startupinfo
            )
            return os.path.exists(output_srt_path) and os.path.getsize(output_srt_path) > 0
    except Exception:
        return False

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




# =====================================================================
# [신규] 다중 선택 가능한 체크박스 콤보박스
# =====================================================================
class CheckableComboBox(QComboBox):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._model = QStandardItemModel(self)
        self.setModel(self._model)
        self._model.itemChanged.connect(self._on_item_changed)
        self.view().pressed.connect(self.handle_item_pressed)
        self.setEditable(True)
        self.lineEdit().setReadOnly(True)
        self.lineEdit().setPlaceholderText("언어를 선택하세요...")
        self.setMinimumWidth(200)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def handle_item_pressed(self, index):
        item = self._model.itemFromIndex(index)
        if item and (item.flags() & Qt.ItemFlag.ItemIsUserCheckable):
            new_state = Qt.CheckState.Unchecked if item.checkState() == Qt.CheckState.Checked else Qt.CheckState.Checked
            item.setCheckState(new_state)

    def _on_item_changed(self, item):
        self.update_text()

    def set_placeholder_text(self, text):
        self.lineEdit().setPlaceholderText(text)

    def update_text(self):
        texts = [
            self._model.item(i).text()
            for i in range(self._model.rowCount())
            if self._model.item(i) and self._model.item(i).checkState() == Qt.CheckState.Checked
        ]
        display = ", ".join(texts)
        self.lineEdit().setText(display)
        if not display:
            self.lineEdit().clear()

    def addItem(self, text, user_data=None):
        item = QStandardItem(text)
        item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable)
        item.setData(Qt.CheckState.Unchecked, Qt.ItemDataRole.CheckStateRole)
        if user_data is not None:
            item.setData(user_data, Qt.ItemDataRole.UserRole)
        self._model.appendRow(item)

    def checked_items(self):
        return [
            self._model.item(i).text()
            for i in range(self._model.rowCount())
            if self._model.item(i) and self._model.item(i).checkState() == Qt.CheckState.Checked
        ]

    def set_checked_items(self, items):
        self._model.blockSignals(True)
        for i in range(self._model.rowCount()):
            item = self._model.item(i)
            if item:
                checked = item.text() in items
                item.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
        self._model.blockSignals(False)
        self.update_text()

    def clear(self):
        self._model.clear()
        self.update_text()



# =====================================================================
# [패치 2] Pyte 기반 완벽한 VT100 터미널 에뮬레이터 위젯
# =====================================================================
class PyteTerminalWidget(QTextEdit):
    """pyte 기반 VT100 터미널 에뮬레이터 위젯"""

    def __init__(self, cols=150, lines=50, history=2000):
        super().__init__()
        self.setReadOnly(True)
        self.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)

        self.setStyleSheet("""
            QTextEdit {
                background-color: #0c0c0c;
                color: #cccccc;
                font-family: Consolas, "Courier New", "Liberation Mono", monospace;
                font-size: 13px;
                border: none;
                padding: 4px;
            }
        """)

        self._cols = cols
        self._lines = lines
        self._history = history
        self.screen = pyte.HistoryScreen(cols, lines, history=history)
        self.screen.set_mode(pyte.modes.LNM)
        self.stream = pyte.Stream(self.screen)

        self.text_queue = queue.Queue()
        self._update_timer = QTimer(self)
        self._update_timer.timeout.connect(self._render_terminal)
        self._update_timer.start(30)
        self._dirty = False

        self._flushed_history_len = 0
        self._last_flushed_signature = None
        self._live_start_pos = None

        self._div_style = (
            "white-space: pre; font-family: Consolas, \"Courier New\", monospace; "
            "font-size: 13px; line-height: 1.25;"
        )

        self._status_cycle_step = 0
        self._status_pending_erase = False

    _STATUS_LINE_1 = "Validating token size..."
    _STATUS_LINE_2 = "Token size validated. Translating..."
    _STATUS_LINE_3 = "✅ Translation completed successfully!"

    @staticmethod
    def _normalize_for_match(s):
        cleaned = "".join(ch for ch in s if unicodedata.category(ch) != "Cf")
        return cleaned.strip().lower()

    def feed(self, text):
        """텍스트를 터미널에 피드 (VT100 시퀀스 지원)"""
        if not text:
            return

        pieces = text.split("\n")
        out_pieces = []
        for line in pieces:
            norm = self._normalize_for_match(line)
            erase_prefix = ""

            if norm == "":
                pass
            elif "validating token size" in norm:
                if self._status_pending_erase:
                    erase_prefix = "\x1b[3A\r\x1b[0J"
                    self._status_pending_erase = False
                self._status_cycle_step = 1
            elif "token size validated" in norm and self._status_cycle_step == 1:
                self._status_cycle_step = 2
            elif "translation completed successfully" in norm and self._status_cycle_step == 2:
                self._status_cycle_step = 0
                self._status_pending_erase = True
            else:
                self._status_cycle_step = 0
                self._status_pending_erase = False

            out_pieces.append(erase_prefix + line)

        text = "\n".join(out_pieces)
        text = text.replace("\r\n", "\n").replace("\n", "\r\n")
        self.text_queue.put(text)

    def feed_line(self, text):
        self.feed(text + "\n")

    def clear_screen(self):
        self.screen.reset()
        if hasattr(pyte, 'modes') and hasattr(pyte.modes, 'LNM'):
            self.screen.set_mode(pyte.modes.LNM)
        if hasattr(self.screen, 'history'):
            self.screen.history.top.clear()
            self.screen.history.bottom.clear()
        self._flushed_history_len = 0
        self._last_flushed_signature = None
        self._live_start_pos = None
        self._status_cycle_step = 0
        self._status_pending_erase = False
        while not self.text_queue.empty():
            try:
                self.text_queue.get_nowait()
            except queue.Empty:
                break
        self._dirty = False
        self.clear()
        cursor = QTextCursor(self.document())
        cursor.movePosition(QTextCursor.MoveOperation.Start)
        self.setTextCursor(cursor)

    _COLOR_MAP = {
        'black': '#0c0c0c', 'red': '#e74856', 'green': '#16c60c',
        'brown': '#f9f1a5', 'blue': '#3b78ff', 'magenta': '#b4009e',
        'cyan': '#61d6d6', 'white': '#cccccc',
        'lightblack': '#767676', 'lightred': '#f96270', 'lightgreen': '#23d11b',
        'lightbrown': '#fdf6af', 'lightblue': '#548cff', 'lightmagenta': '#c810b1',
        'lightcyan': '#78e2e2', 'lightwhite': '#ffffff'
    }

    def _color_to_hex(self, color_name):
        if not color_name or color_name == 'default':
            return None
        if isinstance(color_name, str):
            if color_name.startswith('#'):
                return color_name
            mapped = self._COLOR_MAP.get(color_name)
            if mapped:
                return mapped
            if len(color_name) == 6:
                return f"#{color_name}"
            if len(color_name) == 3:
                return f"#{color_name[0]*2}{color_name[1]*2}{color_name[2]*2}"
        return None

    def _line_last_col(self, line_dict):
        last_col = self.screen.columns - 1
        while last_col >= 0:
            char_obj = line_dict[last_col]
            if char_obj.data != ' ':
                break
            if char_obj.bg != 'default' and char_obj.bg is not None:
                break
            last_col -= 1
        return last_col

    def _line_to_html(self, line_dict):
        chunks = []
        last_fg = None
        last_bg = None
        span_open = False

        last_col = self._line_last_col(line_dict)

        for col in range(last_col + 1):
            char_obj = line_dict[col]
            fg = self._color_to_hex(char_obj.fg)
            bg = self._color_to_hex(char_obj.bg)

            if fg != last_fg or bg != last_bg:
                if span_open:
                    chunks.append("</span>")
                style = ""
                if fg:
                    style += f"color: {fg};"
                if bg:
                    style += f"background-color: {bg};"
                if style:
                    chunks.append(f"<span style='{style}'>")
                    span_open = True
                else:
                    span_open = False
                last_fg = fg
                last_bg = bg

            ch = char_obj.data
            if ch == '<':
                chunks.append('&lt;')
            elif ch == '>':
                chunks.append('&gt;')
            elif ch == '&':
                chunks.append('&amp;')
            else:
                chunks.append(ch)

        if span_open:
            chunks.append("</span>")
        return "".join(chunks)

    def _line_signature(self, line_dict):
        last_col = self._line_last_col(line_dict)
        return "".join(line_dict[c].data for c in range(last_col + 1))

    def _lines_block_html(self, line_dicts):
        parts = [f"<div style='{self._div_style}'>"]
        for line_dict in line_dicts:
            parts.append(self._line_to_html(line_dict))
            parts.append("\n")
        parts.append("</div>")
        return "".join(parts)

    def _render_terminal(self):
        while not self.text_queue.empty():
            try:
                self.stream.feed(self.text_queue.get_nowait())
                self._dirty = True
            except queue.Empty:
                break

        if not self._dirty:
            return
        self._dirty = False

        scrollbar = self.verticalScrollBar()
        is_at_bottom = scrollbar.value() >= scrollbar.maximum() - 5

        history_top = self.screen.history.top
        history_len = len(history_top)

        needs_full_rebuild = self._live_start_pos is None
        if not needs_full_rebuild and self._flushed_history_len > 0:
            check_idx = self._flushed_history_len - 1
            if check_idx >= history_len:
                needs_full_rebuild = True
            else:
                current_sig = self._line_signature(history_top[check_idx])
                if current_sig != self._last_flushed_signature:
                    needs_full_rebuild = True

        cursor = QTextCursor(self.document())

        def insert_block_html(html):
            if not self.document().isEmpty():
                cursor.insertBlock()
            cursor.insertHtml(html)

        if needs_full_rebuild:
            self.setHtml("")
            self._live_start_pos = None
        elif self._live_start_pos is not None:
            doc_len = self.document().characterCount()
            pos = min(self._live_start_pos, max(0, doc_len - 1))
            cursor.setPosition(pos)
            cursor.movePosition(QTextCursor.MoveOperation.End, QTextCursor.MoveMode.KeepAnchor)
            cursor.removeSelectedText()

        if needs_full_rebuild:
            if history_len:
                cursor.movePosition(QTextCursor.MoveOperation.End)
                insert_block_html(self._lines_block_html(history_top))
            self._flushed_history_len = history_len
        elif history_len > self._flushed_history_len:
            new_lines = list(itertools.islice(history_top, self._flushed_history_len, history_len))
            cursor.movePosition(QTextCursor.MoveOperation.End)
            insert_block_html(self._lines_block_html(new_lines))
            self._flushed_history_len = history_len

        if history_len:
            self._last_flushed_signature = self._line_signature(history_top[self._flushed_history_len - 1])

        buffer_lines = [self.screen.buffer[i] for i in range(self.screen.lines)]
        while buffer_lines:
            last_line = buffer_lines[-1]
            if self._line_last_col(last_line) < 0:
                buffer_lines.pop()
            else:
                break

        cursor.movePosition(QTextCursor.MoveOperation.End)
        self._live_start_pos = cursor.position()
        if buffer_lines:
            insert_block_html(self._lines_block_html(buffer_lines))

        if is_at_bottom:
            scrollbar.setValue(scrollbar.maximum())


# =====================================================================
# [스트림 캡처] 예외를 던져 강제 탈출 + 터미널 위젯으로 텍스트 전달
# =====================================================================
class ForceAbortException(BaseException):
    """사용자 중단을 위한 특수 예외 (Exception이 아닌 BaseException 상속)"""
    pass


class WorkerStream(QObject):
    text_written = pyqtSignal(str)

    def __init__(self, worker_thread):
        super().__init__()
        self.worker_thread = worker_thread

    def write(self, text):
        if self.worker_thread.isInterruptionRequested():
            raise ForceAbortException("사용자 중단 요청")
        if text is not None:
            self.text_written.emit(str(text))

    def flush(self):
        pass

    def isatty(self):
        return False


# =====================================================================
# [모델 가져오기 스레드]
# =====================================================================
class ModelFetcherThread(QThread):
    models_fetched = pyqtSignal(list)
    error_occurred = pyqtSignal(str)

    def __init__(self, api_key):
        super().__init__()
        self.api_key = api_key

    def run(self):
        if not genai:
            self.error_occurred.emit("google-genai 라이브러리가 없습니다.")
            return
        if not self.api_key:
            self.error_occurred.emit("모델 목록을 가져오려면 기본 API 키가 필요합니다.")
            return
        try:
            client = genai.Client(api_key=self.api_key)
            available_models = []
            for m in client.models.list():
                supported = getattr(m, 'supported_generation_methods', [])
                if 'generateContent' in supported:
                    model_name = m.name.replace('models/', '')
                    available_models.append(model_name)
                elif hasattr(m, 'name'):
                    model_name = m.name.replace('models/', '')
                    if "gemini" in model_name:
                        available_models.append(model_name)

            available_models = sorted(list(set(available_models)))
            if available_models:
                self.models_fetched.emit(available_models)
            else:
                self.error_occurred.emit("사용 가능한 생성 모델을 찾을 수 없습니다.")
        except Exception as e:
            self.error_occurred.emit(f"모델 가져오기 실패: {e}")


# =====================================================================
# [번역/전사 워커 스레드]
# =====================================================================
class TranslationWorker(QThread):
    progress_update = pyqtSignal(str)
    raw_output_update = pyqtSignal(str)
    job_translated = pyqtSignal(str, str)
    job_error = pyqtSignal(str)
    finished_signal = pyqtSignal()

    def __init__(self, valid_api_keys, job_queue, base_config):
        super().__init__()
        self.api_keys = list(valid_api_keys)
        self.job_queue = job_queue
        self.base_config = base_config
        self.current_key_index = 0

        self.gui_stream_out = WorkerStream(self)
        self.gui_stream_out.text_written.connect(self.raw_output_update.emit)

        self._consecutive_failures = 0
        self._max_consecutive_failures = 5
        self._base_backoff_seconds = 3.0
        self._max_backoff_seconds = 60.0

    def run(self):
        task_mode = self.base_config.get('task_mode', 'translate')
        task_name = "전사(Transcribe)" if task_mode == 'transcribe' else "번역(Translate)"

        key_count = len(self.api_keys) if self.api_keys else 0
        self.progress_update.emit(
            f"\x1b[36m==== {task_name} 워커 시작 (총 API 키: {key_count}개) ====\x1b[0m\n"
        )

        original_stdout = sys.stdout
        original_stderr = sys.stderr
        sys.stdout = self.gui_stream_out
        sys.stderr = self.gui_stream_out

        original_sleep = time.sleep
        worker_thread_id = threading.get_ident()

        def patched_sleep(seconds):
            if threading.get_ident() == worker_thread_id:
                end_time = time.time() + seconds
                while time.time() < end_time:
                    if self.isInterruptionRequested():
                        raise ForceAbortException("사용자 중단 요청")
                    original_sleep(0.1)
            else:
                original_sleep(seconds)

        time.sleep = patched_sleep

        try:
            while not self.isInterruptionRequested():
                try:
                    job = self.job_queue.get_nowait()
                    if job is None:
                        break

                    job_input_source, target_language, output_file_path, source_is_media_only, media_type, job_video_file = job
                    is_transcribe_mode = (task_mode == 'transcribe')
                    actual_input_file_for_lib = (
                        None
                        if (source_is_media_only and not is_transcribe_mode)
                        else job_input_source
                    )
                    base_name = os.path.basename(job_input_source)

                    if source_is_media_only and media_type == 'video':
                        video_file_for_job = job_input_source
                        audio_file_for_job = None
                    elif source_is_media_only and media_type == 'audio':
                        video_file_for_job = None
                        audio_file_for_job = job_input_source
                    else:
                        video_file_for_job = job_video_file or self.base_config.get('video_file', None)
                        audio_file_for_job = self.base_config.get('audio_file', None)

                    if os.path.exists(output_file_path):
                        if actual_input_file_for_lib and os.path.abspath(output_file_path) == os.path.abspath(actual_input_file_for_lib):
                            pass
                        else:
                            try:
                                os.remove(output_file_path)
                            except OSError:
                                pass

                    max_key_attempts = max(1, len(self.api_keys))
                    job_successful = False
                    last_error_msg = ""

                    for attempt in range(max_key_attempts):
                        if self.isInterruptionRequested():
                            break

                        current_primary_api_key = (
                            self.api_keys[self.current_key_index] if self.api_keys else None
                        )
                        key_display_index = self.current_key_index + 1 if self.api_keys else 0
                        msg_key = f"키 {key_display_index}/{key_count}"

                        if attempt > 0:
                            self.progress_update.emit(
                                f"\x1b[33m\n[작업 재시도 ({attempt+1}/{max_key_attempts}) ({msg_key})] [{target_language}] {base_name}\x1b[0m\n"
                            )
                        else:
                            self.progress_update.emit(
                                f"\x1b[33m\n[작업 시작 ({msg_key})] [{target_language}] {base_name}\x1b[0m\n"
                            )

                        reset_library_logger()
                        captured_stderr_io_for_lib = io.StringIO()
                        original_thread_stderr = sys.stderr
                        sys.stderr = captured_stderr_io_for_lib

                        try:
                            translator_args = {
                                'gemini_api_key': current_primary_api_key,
                                'gemini_api_key2': self.base_config.get('gemini_api_key2', None),
                                'target_language': target_language,
                                'input_file': actual_input_file_for_lib,
                                'output_file': output_file_path,
                                'start_line': self.base_config.get('start_line', 1),
                                'description': self.base_config.get('description', '') or None,
                                'model_name': self.base_config.get('model_name', DEFAULT_MODEL),
                                'batch_size': self.base_config.get('batch_size', DEFAULT_BATCH_SIZE),
                                'streaming': self.base_config.get('streaming', True),
                                'thinking': self.base_config.get('thinking', True),
                                'thinking_budget': self.base_config.get('thinking_budget', 2048),
                                'temperature': self.base_config.get('temperature'),
                                'top_p': self.base_config.get('top_p'),
                                'top_k': self.base_config.get('top_k'),
                                'free_quota': self.base_config.get('free_quota', True),
                                'use_colors': True,
                                'progress_log': self.base_config.get('progress_log', False),
                                'thoughts_log': self.base_config.get('thoughts_log', False),
                                'video_file': video_file_for_job,
                                'audio_file': audio_file_for_job,
                                'extract_audio': self.base_config.get('extract_audio', False),
                                'audio_chunk_size': self.base_config.get('audio_chunk_size', 300),
                                'isolate_voice': self.base_config.get('isolate_voice', True),
                                'token_stats': self.base_config.get('token_stats', True),
                                'preserve_context': self.base_config.get('preserve_context', True),
                                'token_report': self.base_config.get('token_report', False),
                                'context_size': self.base_config.get('context_size', self.base_config.get('resume_context_size', 0)),
                                'resume_context_size': self.base_config.get('resume_context_size', 0),
                                'batch_size_error_step': self.base_config.get('batch_size_error_step', 100),
                                'audio_chunk_error_step': self.base_config.get('audio_chunk_error_step', 60),
                                'service_tier': self.base_config.get('service_tier', None),
                                'use_enterprise': self.base_config.get('use_enterprise', False),
                                'cloud_project': self.base_config.get('cloud_project', None),
                                'cloud_location': self.base_config.get('cloud_location', None),
                                'cloud_api_key': self.base_config.get('cloud_api_key', None),
                                'request_type': self.base_config.get('request_type', None),
                            }

                            t_level = self.base_config.get('thinking_level', 'Default')
                            if t_level != 'Default':
                                translator_args['thinking_level'] = t_level.lower()

                            filtered_params = {k: v for k, v in translator_args.items() if v is not None}
                            if GeminiSRTTranslator is not None:
                                # 라이브러리 버전 호환성: 실제 __init__ 파라미터만 전달 (캐시된 시그니처 활용)
                                _gst_params = _get_gst_params()
                                filtered_params = {k: v for k, v in filtered_params.items() if k in _gst_params}
                                translator_instance = GeminiSRTTranslator(**filtered_params)
                                if is_transcribe_mode:
                                    translator_instance.transcribe()
                                else:
                                    translator_instance.translate()
                            else:
                                for key, value in filtered_params.items():
                                    setattr(gst, key, value)
                                if is_transcribe_mode:
                                    gst.transcribe()
                                else:
                                    gst.translate()

                            job_successful = True

                        except ForceAbortException:
                            break

                        except Exception as e:
                            if self.isInterruptionRequested():
                                break

                            import traceback as _tb
                            err_str = str(e).lower()
                            err_type = type(e).__name__.lower()
                            err_base = f"작업 실패 ({msg_key}): '{base_name}'"
                            err_tb = _tb.format_exc()

                            if isinstance(e, WorkerLibraryExit):
                                err_msg = f"{err_base} - AI 모델 과부하(Overloaded 3회) 또는 라이브러리 종료 요청으로 중단됨."
                            elif "blocked" in err_type or "blocked" in err_str:
                                err_msg = f"{err_base} - AI 안전 설정 차단."
                            elif "stop" in err_type and "candidate" in err_type:
                                err_msg = f"{err_base} - AI 응답 생성 중단."
                            elif err_type in ("attributeerror", "typeerror", "indexerror") and (
                                "content" in err_str or "candidates" in err_str or "parts" in err_str
                            ):
                                # 라이브러리 내부 스트림 청크 None 접근 오류 (google-genai SDK 호환성 문제)
                                err_msg = f"{err_base} - API 스트림 응답 오류 ({type(e).__name__}: {e})"
                            elif err_type in ("attributeerror", "typeerror", "indexerror", "keyerror"):
                                # 기타 Python 런타임 오류 - 실제 내용을 표시
                                err_msg = f"{err_base} - 라이브러리 내부 오류 ({type(e).__name__}: {e})"
                            elif 'content' in err_str or 'text' in err_str:
                                # ValueError 등 라이브러리의 Schema/응답 검증 실패
                                err_msg = f"{err_base} - API 응답 데이터(Schema) 오류 ({e})"
                            elif "deadline" in err_str or "504" in err_str:
                                err_msg = f"{err_base} - 서버 응답 시간 초과."
                            elif "quota" in err_str or "429" in err_str:
                                err_msg = f"{err_base} - API 할당량 고갈 (429)."
                            elif "permission" in err_str or "403" in err_str:
                                err_msg = f"{err_base} - 권한 없음 (API 인증 오류)."
                            else:
                                err_msg = f"{err_base} - 라이브러리 예외: {e}"

                            last_error_msg = err_msg
                            err_logs = captured_stderr_io_for_lib.getvalue()
                            if err_logs.strip():
                                self.progress_update.emit(f"\x1b[33m[라이브러리 로그]\n{err_logs}\x1b[0m\n")
                            self.progress_update.emit(f"\n\x1b[31m[오류] {err_msg}\x1b[0m\n")
                            # Traceback 상세 로그 (디버그용)
                            self.progress_update.emit(f"\x1b[33m[디버그 Traceback]\n{err_tb}\x1b[0m\n")

                        finally:
                            sys.stderr = original_thread_stderr
                            captured_stderr_io_for_lib.close()


                        if job_successful:
                            break
                        else:
                            if self.api_keys:
                                self.current_key_index = (self.current_key_index + 1) % len(self.api_keys)

                    if self.isInterruptionRequested():
                        break

                    if job_successful:
                        self.job_translated.emit(output_file_path, target_language)
                        self._consecutive_failures = 0
                        if self.api_keys:
                            self.current_key_index = (self.current_key_index + 1) % len(self.api_keys)
                    else:
                        self.job_error.emit(last_error_msg or "모든 API 키 시도 실패")
                        self._consecutive_failures += 1

                        if self._consecutive_failures >= self._max_consecutive_failures:
                            self.progress_update.emit(
                                f"\n\x1b[31m==== 🛑 연속 실패 {self._consecutive_failures}회 감지 "
                                f"→ 시스템 보호를 위해 작업을 중단합니다. "
                                f"(API 키/네트워크/할당량 상태를 확인하세요) ====\x1b[0m\n"
                            )
                            self.job_queue.task_done()
                            break

                        backoff = min(
                            self._base_backoff_seconds * (2 ** (self._consecutive_failures - 1)),
                            self._max_backoff_seconds,
                        )
                        self.progress_update.emit(
                            f"\x1b[33m[대기] 연속 실패 {self._consecutive_failures}회 "
                            f"→ {backoff:.0f}초 대기 후 재시도 (자원 과부하 방지)\x1b[0m\n"
                        )
                        try:
                            time.sleep(backoff)
                        except ForceAbortException:
                            self.job_queue.task_done()
                            break

                    self.job_queue.task_done()

                except queue.Empty:
                    if not self.isInterruptionRequested():
                        self.progress_update.emit(
                            "\x1b[32m\n모든 작업 큐가 비워졌습니다.\x1b[0m\n"
                        )
                    break
                except Exception as e:
                    if not self.isInterruptionRequested():
                        self.progress_update.emit(
                            f"\n\x1b[31m[심각] 워커 루프 예외: {e}\x1b[0m\n"
                        )
                        self.job_error.emit(f"루프 오류: {e}")
                    break
        finally:
            sys.stdout = original_stdout
            sys.stderr = original_stderr
            time.sleep = original_sleep

            msg = f"\n\x1b[36m==== {task_name} 워커 스레드 종료 ====\x1b[0m\n"
            if self.isInterruptionRequested():
                msg += "\x1b[33m(사용자 수동 중단 요청에 의해 멈춤)\x1b[0m\n"
            self.progress_update.emit(msg)
            self.finished_signal.emit()


# =====================================================================
# [다국어 지원] 다국어(한국어 / English) 텍스트 리소스
# =====================================================================
I18N = {
    "ko": {
        "app_title": "Gemini SRT Translator GUI (Pyte Terminal)",
        "api_group_title": "API 키 설정",
        "btn_manage_api_keys": "API 키 관리...",
        "lbl_api_keys_summary": "등록된 키: {filled} / {total}",
        "lbl_app_lang": "언어/Lang:",
        "chk_use_enterprise": "Agent Platform (Enterprise) 사용",
        "cloud_project_label": "Cloud Project:",
        "cloud_project_ph": "Google Cloud Project ID (ADC)",
        "cloud_api_key_label": "Cloud API Key:",
        "cloud_api_key_ph": "Google Cloud API Key (Express)",
        "cloud_location_label": "Cloud Location:",
        "cloud_location_ph": "Region (기본: global)",
        "request_type_label": "Request Type:",
        "btn_save_api": "설정 저장",

        "dialog_api_title": "API 키 관리 (최대 10개)",
        "dialog_api_info": "무료 할당량을 극대화하려면 여러 개의 Gemini API 키를 등록하세요.\n작업(job)마다 아래 순서대로 키를 돌려가며 사용합니다.",
        "api_key_label": "API 키 {index}:",
        "api_key_ph_primary": "기본 API 키 (필수)",
        "api_key_ph_extra": "추가 API 키 {index}",
        "api_key_ph_secondary_suffix": " (gemini_api_key2로 사용)",
        "btn_save": "저장",
        "btn_close": "닫기",

        "file_lang_group_title": "파일 및 언어 설정",
        "lbl_task_mode": "작업 모드:",
        "task_mode_translate": "자막 번역 (Translate SRT/ASS)",
        "task_mode_transcribe": "비디오/오디오 전사 (Transcribe to SRT)",
        "btn_files": "입력 SRT/ASS 파일 선택 (번역용)",
        "btn_out": "출력 폴더 선택",
        "btn_video_file": "비디오 파일 선택 (다중 가능)",
        "lst_video_files_tt": "전사 타겟(순차 처리) 또는 번역 컨텍스트로 사용될 비디오 파일 목록",
        "btn_audio_file": "오디오 파일 선택",
        "lbl_audio_file_ph": "오디오 파일 (전사 타겟 또는 번역 컨텍스트)",
        "lbl_target_lang": "출력 대상 언어:",
        "btn_all_lang": "전체 선택",
        "btn_none_lang": "전체 해제",
        "cmb_langs_ph": "언어를 선택하세요...",

        "main_options_group_title": "기본 설정",
        "btn_fetch": "모델 가져오기",
        "lbl_model": "사용 모델:",
        "chk_append_lang": "출력 파일명에 언어명 접미사 추가",
        "chk_reuse_extracted": "추출된 자막 재사용 (재추출 안 함)",
        "lbl_batch": "배치 크기:",
        "lbl_prompt": "프롬프트/지침 입력 (선택):",
        "txt_desc_ph": "번역/전사 시 AI가 참고할 문맥을 입력하세요.",

        "btn_advanced": "⚙ 고급 설정 및 튜닝 (v3.8.3 기능) 열기",
        "advanced_dialog_title": "고급 설정 및 튜닝 (v3.8.3 기능)",
        "lbl_service_tier": "서비스 티어:",
        "lbl_start_line": "시작 라인:",
        "spin_default": "기본값",
        "lbl_thinking_budget": "사고 예산:",
        "lbl_audio_chunk": "오디오청크:",
        "lbl_thinking_level": "사고 수준:",
        "spin_resume_default": "기본값 (자동)",
        "lbl_resume_help": "(문맥/재개 시 참조 라인 수, 0: 비활성)",
        "lbl_batch_step": "배치 축소단위:",
        "lbl_audio_step": "오디오 축소단위:",
        "lbl_adaptive_help": "(API/파싱 오류 발생 시 자동 감축 단위)",
        "chk_streaming": "스트리밍",
        "chk_thinking": "사고기능",
        "chk_preserve_context": "문맥 유지",
        "chk_isolate_voice": "보이스 격리",
        "chk_extract_audio": "번역 전 추출",
        "chk_free": "무료 쿼터",
        "chk_token_stats": "토큰 실시간 통계",
        "chk_token_report": "비용 리포트 저장 (.json)",
        "chk_thoughts_log": "사고 로그",

        "action_log_group_title": "터미널 출력 (VT100 Engine)",
        "btn_start": "🚀 작업 시작",
        "btn_stop": "🛑 작업 중단",
        "progress_idle": "대기 중",
        "progress_format": "{current} / {total} 완료",
        "progress_format_err": "{current} / {total} 완료 (오류 발생)",
        "progress_completed": "완료",
        "progress_interrupted": "{current} / {total} (중단됨)",

        "dlg_exit_title": "종료 확인",
        "dlg_exit_msg": "작업이 진행 중입니다. 프로그램을 종료하시겠습니까?\n\n(현재 작업은 중단되며, 재개 기능으로 나중에 이어서 할 수 있습니다.)",
        "dlg_need_api_key_title": "API 키 필요",
        "dlg_need_api_key_msg": "기본 API 키(1)가 필요합니다.",
        "dlg_need_api_key_msg_all": "API 키를 하나 이상 입력해야 합니다.",
        "dlg_need_media_title": "미디어 필요",
        "dlg_need_media_msg": "전사할 대상 비디오/오디오 파일을 선택하세요.",
        "dlg_need_file_title": "파일 필요",
        "dlg_need_file_msg": "번역할 SRT/ASS 파일을 선택하세요.",
        "dlg_need_output_err_title": "출력 폴더 오류",
        "dlg_need_output_err_msg": "출력 폴더를 생성할 수 없습니다:\n{err}",
        "dlg_need_model_title": "모델 선택",
        "dlg_need_model_msg": "사용할 모델을 선택하세요.",
        "dlg_need_lang_title": "언어 선택",
        "dlg_need_lang_msg": "대상 언어를 하나 이상 선택하세요.",
        "dlg_job_failed_title": "작업 생성 실패",
        "dlg_job_failed_msg": "생성된 작업이 없습니다.",
        "dlg_in_progress_title": "작업 중",
        "dlg_in_progress_msg": "이미 작업이 진행 중입니다.",

        "log_settings_loaded": "설정이 성공적으로 로드되었습니다.",
        "log_models_fetched": "모델 업데이트 완료: {count}개",
        "log_models_fetch_err": "[오류] 모델 로딩 실패: {err}",
        "log_user_stop": "==== 🛑 사용자 중단 요청 (현재 진행 중인 배치 마무리 후 안전하게 종료됩니다) ====",
        "log_all_done": "==== ✅ 모든 작업 완료 ====",
        "log_interrupted": "==== ⚠️ 작업 중단됨 (미완료: {count}개) ====",
        "log_skipped": "==== ⚠️ 일부 작업 누락됨 ({completed}/{total}) ====",
        "log_job_success": "[성공] ({current}/{total}): [{lang}] {file}",
        "log_job_fail": "[실패] ({current}/{total}): {err}",

        "fd_select_video": "비디오 파일 선택 (다중 선택 가능)",
        "fd_select_audio": "오디오 파일 선택",
        "fd_select_srt": "SRT/ASS 파일 선택",
        "fd_select_out": "출력 폴더 선택",
    },
    "en": {
        "app_title": "Gemini SRT Translator GUI (Pyte Terminal)",
        "api_group_title": "API Key Settings",
        "btn_manage_api_keys": "Manage API Keys...",
        "lbl_api_keys_summary": "Registered Keys: {filled} / {total}",
        "lbl_app_lang": "Language:",
        "chk_use_enterprise": "Use Agent Platform (Enterprise)",
        "cloud_project_label": "Cloud Project:",
        "cloud_project_ph": "Google Cloud Project ID (ADC)",
        "cloud_api_key_label": "Cloud API Key:",
        "cloud_api_key_ph": "Google Cloud API Key (Express)",
        "cloud_location_label": "Cloud Location:",
        "cloud_location_ph": "Region (Default: global)",
        "request_type_label": "Request Type:",
        "btn_save_api": "Save Settings",

        "dialog_api_title": "Manage API Keys (Max 10)",
        "dialog_api_info": "Register multiple Gemini API keys to maximize free quota allocation.\nKeys will be rotated sequentially for each job.",
        "api_key_label": "API Key {index}:",
        "api_key_ph_primary": "Primary API Key (Required)",
        "api_key_ph_extra": "Additional API Key {index}",
        "api_key_ph_secondary_suffix": " (Used as gemini_api_key2)",
        "btn_save": "Save",
        "btn_close": "Close",

        "file_lang_group_title": "File & Language Settings",
        "lbl_task_mode": "Task Mode:",
        "task_mode_translate": "Subtitle Translation (Translate SRT/ASS)",
        "task_mode_transcribe": "Video/Audio Transcription (Transcribe to SRT)",
        "btn_files": "Select Input SRT/ASS Files (Translate)",
        "btn_out": "Select Output Folder",
        "btn_video_file": "Select Video Files (Multiple allowed)",
        "lst_video_files_tt": "List of video files used as transcription targets or translation contexts",
        "btn_audio_file": "Select Audio File",
        "lbl_audio_file_ph": "Audio file (Transcription target or translation context)",
        "lbl_target_lang": "Target Languages:",
        "btn_all_lang": "Select All",
        "btn_none_lang": "Deselect All",
        "cmb_langs_ph": "Select languages...",

        "main_options_group_title": "Basic Settings",
        "btn_fetch": "Fetch Models",
        "lbl_model": "Model:",
        "chk_append_lang": "Append language suffix to output filename",
        "chk_reuse_extracted": "Reuse extracted subtitles (do not re-extract)",
        "lbl_batch": "Batch Size:",
        "lbl_prompt": "Prompt / Instructions (Optional):",
        "txt_desc_ph": "Enter context or guidelines for AI to reference during translation/transcription.",

        "btn_advanced": "⚙ Open Advanced Settings & Tuning (v3.8.3)",
        "advanced_dialog_title": "Advanced Settings & Tuning (v3.8.3)",
        "lbl_service_tier": "Service Tier:",
        "lbl_start_line": "Start Line:",
        "spin_default": "Default",
        "lbl_thinking_budget": "Thinking Budget:",
        "lbl_audio_chunk": "Audio Chunk:",
        "lbl_thinking_level": "Thinking Level:",
        "spin_resume_default": "Default (Auto)",
        "lbl_resume_help": "(Context lines for resume/sliding context, 0: disable)",
        "lbl_batch_step": "Batch Error Step:",
        "lbl_audio_step": "Audio Error Step:",
        "lbl_adaptive_help": "(Adaptive sizing reduction per error)",
        "chk_streaming": "Streaming",
        "chk_thinking": "Thinking",
        "chk_preserve_context": "Preserve Context",
        "chk_isolate_voice": "Voice Isolation",
        "chk_extract_audio": "Extract Audio First",
        "chk_free": "Free Quota",
        "chk_token_stats": "Real-time Token Stats",
        "chk_token_report": "Save Cost Report (.json)",
        "chk_thoughts_log": "Thinking Log",

        "action_log_group_title": "Terminal Output (VT100 Engine)",
        "btn_start": "🚀 Start Task",
        "btn_stop": "🛑 Stop Task",
        "progress_idle": "Idle",
        "progress_format": "{current} / {total} Completed",
        "progress_format_err": "{current} / {total} Completed (Errors)",
        "progress_completed": "Completed",
        "progress_interrupted": "{current} / {total} (Interrupted)",

        "dlg_exit_title": "Confirm Exit",
        "dlg_exit_msg": "A task is currently running. Do you want to exit?\n\n(Current progress will be stopped and can be resumed later.)",
        "dlg_need_api_key_title": "API Key Required",
        "dlg_need_api_key_msg": "Primary API Key (1) is required.",
        "dlg_need_api_key_msg_all": "At least one API key must be entered.",
        "dlg_need_media_title": "Media Required",
        "dlg_need_media_msg": "Please select target video/audio file for transcription.",
        "dlg_need_file_title": "File Required",
        "dlg_need_file_msg": "Please select SRT/ASS file to translate.",
        "dlg_need_output_err_title": "Output Folder Error",
        "dlg_need_output_err_msg": "Cannot create output folder:\n{err}",
        "dlg_need_model_title": "Model Selection",
        "dlg_need_model_msg": "Please select a model to use.",
        "dlg_need_lang_title": "Language Selection",
        "dlg_need_lang_msg": "Please select at least one target language.",
        "dlg_job_failed_title": "Job Creation Failed",
        "dlg_job_failed_msg": "No jobs were created.",
        "dlg_in_progress_title": "Task Running",
        "dlg_in_progress_msg": "A task is already running.",

        "log_settings_loaded": "Settings loaded successfully.",
        "log_models_fetched": "Model update completed: {count} models",
        "log_models_fetch_err": "[Error] Model loading failed: {err}",
        "log_user_stop": "==== 🛑 User stop requested (Safely shutting down after completing current batch) ====",
        "log_all_done": "==== ✅ All tasks completed ====",
        "log_interrupted": "==== ⚠️ Task interrupted (Incomplete: {count}) ====",
        "log_skipped": "==== ⚠️ Some tasks were skipped ({completed}/{total}) ====",
        "log_job_success": "[Success] ({current}/{total}): [{lang}] {file}",
        "log_job_fail": "[Failed] ({current}/{total}): {err}",

        "fd_select_video": "Select Video Files (Multiple allowed)",
        "fd_select_audio": "Select Audio File",
        "fd_select_srt": "Select SRT/ASS Files",
        "fd_select_out": "Select Output Folder",
    }
}


# =====================================================================
# [메인 GUI 애플리케이션]
# =====================================================================
class TranslatorApp(QWidget):
    def __init__(self):
        super().__init__()
        self.settings = QSettings(SETTINGS_ORG, SETTINGS_APP)
        self.input_files = []
        out_dir = self.settings.value("output_dir", os.path.expanduser("~"))
        self.output_dir = out_dir if os.path.isdir(out_dir) else os.path.expanduser("~")
        self.model_fetcher_thread = None
        self.translation_worker = None
        self.job_queue = None
        self.total_jobs = 0
        self.completed_jobs = 0
        self.job_completion_lock = threading.Lock()
        self.api_key_inputs = []
        self.api_key_labels = []
        self._stop_requested = False
        self.video_file_paths = []
        self.audio_file_path = ""
        self.app_lang = "ko"

        self.init_ui()
        self.load_settings()

        if GST_IMPORT_ERROR or GENAI_IMPORT_ERROR:
            msg = ""
            if GST_IMPORT_ERROR:
                msg += (
                    "gemini-srt-translator 로드 실패 → '작업 시작' 버튼이 비활성화됩니다.\n"
                    f"오류 내용: {GST_IMPORT_ERROR}\n\n"
                )
            if GENAI_IMPORT_ERROR:
                msg += (
                    "google-genai 로드 실패 → '모델 가져오기' 버튼이 비활성화됩니다.\n"
                    f"오류 내용: {GENAI_IMPORT_ERROR}\n"
                )
            QMessageBox.warning(self, "라이브러리 로드 경고", msg)

    def tr_str(self, key, **kwargs):
        lang = getattr(self, "app_lang", "ko")
        template = I18N.get(lang, I18N["ko"]).get(key, I18N["ko"].get(key, key))
        if kwargs:
            try:
                return template.format(**kwargs)
            except Exception:
                return template
        return template

    def _on_app_lang_changed(self, index):
        self.app_lang = "ko" if index == 0 else "en"
        self.update_ui_language()
        self.save_settings()

    def update_ui_language(self):
        self.setWindowTitle(self.tr_str("app_title"))
        if hasattr(self, 'api_group'):
            self.api_group.setTitle(self.tr_str("api_group_title"))
        if hasattr(self, 'btn_manage_api_keys'):
            self.btn_manage_api_keys.setText(self.tr_str("btn_manage_api_keys"))
        if hasattr(self, 'lbl_app_lang'):
            self.lbl_app_lang.setText(self.tr_str("lbl_app_lang"))
        self._update_api_keys_summary()
        if hasattr(self, 'chk_use_enterprise'):
            self.chk_use_enterprise.setText(self.tr_str("chk_use_enterprise"))
        if hasattr(self, 'cloud_project_label'):
            self.cloud_project_label.setText(self.tr_str("cloud_project_label"))
        if hasattr(self, 'cloud_project_input'):
            self.cloud_project_input.setPlaceholderText(self.tr_str("cloud_project_ph"))
        if hasattr(self, 'cloud_api_key_label'):
            self.cloud_api_key_label.setText(self.tr_str("cloud_api_key_label"))
        if hasattr(self, 'cloud_api_key_input'):
            self.cloud_api_key_input.setPlaceholderText(self.tr_str("cloud_api_key_ph"))
        if hasattr(self, 'cloud_location_label'):
            self.cloud_location_label.setText(self.tr_str("cloud_location_label"))
        if hasattr(self, 'cloud_location_input'):
            self.cloud_location_input.setPlaceholderText(self.tr_str("cloud_location_ph"))
        if hasattr(self, 'request_type_label'):
            self.request_type_label.setText(self.tr_str("request_type_label"))
        if hasattr(self, 'btn_save_api'):
            self.btn_save_api.setText(self.tr_str("btn_save_api"))

        # API Key Dialog
        if hasattr(self, 'api_keys_dialog'):
            self.api_keys_dialog.setWindowTitle(self.tr_str("dialog_api_title"))
        if hasattr(self, 'dialog_info_label'):
            self.dialog_info_label.setText(self.tr_str("dialog_api_info"))
        if hasattr(self, 'api_key_labels') and hasattr(self, 'api_key_inputs'):
            for i in range(NUM_API_KEYS):
                if i < len(self.api_key_labels):
                    self.api_key_labels[i].setText(self.tr_str("api_key_label", index=i+1))
                if i < len(self.api_key_inputs):
                    ph = self.tr_str("api_key_ph_primary") if i == 0 else self.tr_str("api_key_ph_extra", index=i+1)
                    if i == 1:
                        ph += self.tr_str("api_key_ph_secondary_suffix")
                    self.api_key_inputs[i].setPlaceholderText(ph)
        if hasattr(self, 'btn_dialog_save'):
            self.btn_dialog_save.setText(self.tr_str("btn_save"))
        if hasattr(self, 'btn_dialog_close'):
            self.btn_dialog_close.setText(self.tr_str("btn_close"))

        # File & Language Group
        if hasattr(self, 'file_lang_group'):
            self.file_lang_group.setTitle(self.tr_str("file_lang_group_title"))
        if hasattr(self, 'lbl_task_mode'):
            self.lbl_task_mode.setText(self.tr_str("lbl_task_mode"))
        if hasattr(self, 'cmb_task_mode'):
            self.cmb_task_mode.setItemText(0, self.tr_str("task_mode_translate"))
            self.cmb_task_mode.setItemText(1, self.tr_str("task_mode_transcribe"))
        if hasattr(self, 'btn_files'):
            self.btn_files.setText(self.tr_str("btn_files"))
        if hasattr(self, 'btn_out'):
            self.btn_out.setText(self.tr_str("btn_out"))
        if hasattr(self, 'btn_video_file'):
            self.btn_video_file.setText(self.tr_str("btn_video_file"))
        if hasattr(self, 'lst_video_files'):
            self.lst_video_files.setToolTip(self.tr_str("lst_video_files_tt"))
        if hasattr(self, 'btn_audio_file'):
            self.btn_audio_file.setText(self.tr_str("btn_audio_file"))
        if hasattr(self, 'lbl_audio_file'):
            self.lbl_audio_file.setPlaceholderText(self.tr_str("lbl_audio_file_ph"))
        if hasattr(self, 'lbl_target_lang'):
            self.lbl_target_lang.setText(self.tr_str("lbl_target_lang"))
        if hasattr(self, 'btn_all_lang'):
            self.btn_all_lang.setText(self.tr_str("btn_all_lang"))
        if hasattr(self, 'btn_none_lang'):
            self.btn_none_lang.setText(self.tr_str("btn_none_lang"))
        if hasattr(self, 'cmb_langs'):
            self.cmb_langs.set_placeholder_text(self.tr_str("cmb_langs_ph"))

        # Main Options Group
        if hasattr(self, 'main_options_group'):
            self.main_options_group.setTitle(self.tr_str("main_options_group_title"))
        if hasattr(self, 'btn_fetch'):
            self.btn_fetch.setText(self.tr_str("btn_fetch"))
        if hasattr(self, 'lbl_model'):
            self.lbl_model.setText(self.tr_str("lbl_model"))
        if hasattr(self, 'chk_append_lang'):
            self.chk_append_lang.setText(self.tr_str("chk_append_lang"))
        if hasattr(self, 'chk_reuse_extracted'):
            self.chk_reuse_extracted.setText(self.tr_str("chk_reuse_extracted"))
        if hasattr(self, 'lbl_batch'):
            self.lbl_batch.setText(self.tr_str("lbl_batch"))
        if hasattr(self, 'lbl_prompt'):
            self.lbl_prompt.setText(self.tr_str("lbl_prompt"))
        if hasattr(self, 'txt_desc'):
            self.txt_desc.setPlaceholderText(self.tr_str("txt_desc_ph"))

        # Advanced Settings Dialog
        if hasattr(self, 'btn_advanced'):
            self.btn_advanced.setText(self.tr_str("btn_advanced"))
        if hasattr(self, 'advanced_dialog'):
            self.advanced_dialog.setWindowTitle(self.tr_str("advanced_dialog_title"))
        if hasattr(self, 'lbl_service_tier'):
            self.lbl_service_tier.setText(self.tr_str("lbl_service_tier"))
        if hasattr(self, 'lbl_start_line'):
            self.lbl_start_line.setText(self.tr_str("lbl_start_line"))
        if hasattr(self, 'spin_temp'):
            self.spin_temp.setSpecialValueText(self.tr_str("spin_default"))
        if hasattr(self, 'spin_top_p'):
            self.spin_top_p.setSpecialValueText(self.tr_str("spin_default"))
        if hasattr(self, 'spin_top_k'):
            self.spin_top_k.setSpecialValueText(self.tr_str("spin_default"))
        if hasattr(self, 'lbl_thinking_budget'):
            self.lbl_thinking_budget.setText(self.tr_str("lbl_thinking_budget"))
        if hasattr(self, 'lbl_audio_chunk'):
            self.lbl_audio_chunk.setText(self.tr_str("lbl_audio_chunk"))
        if hasattr(self, 'lbl_thinking_level'):
            self.lbl_thinking_level.setText(self.tr_str("lbl_thinking_level"))
        if hasattr(self, 'spin_resume_context'):
            self.spin_resume_context.setSpecialValueText(self.tr_str("spin_resume_default"))
        if hasattr(self, 'lbl_resume_help'):
            self.lbl_resume_help.setText(self.tr_str("lbl_resume_help"))
        if hasattr(self, 'lbl_batch_step'):
            self.lbl_batch_step.setText(self.tr_str("lbl_batch_step"))
        if hasattr(self, 'lbl_audio_step'):
            self.lbl_audio_step.setText(self.tr_str("lbl_audio_step"))
        if hasattr(self, 'lbl_adaptive_help'):
            self.lbl_adaptive_help.setText(self.tr_str("lbl_adaptive_help"))
        if hasattr(self, 'chk_streaming'):
            self.chk_streaming.setText(self.tr_str("chk_streaming"))
        if hasattr(self, 'chk_thinking'):
            self.chk_thinking.setText(self.tr_str("chk_thinking"))
        if hasattr(self, 'chk_preserve_context'):
            self.chk_preserve_context.setText(self.tr_str("chk_preserve_context"))
        if hasattr(self, 'chk_isolate_voice'):
            self.chk_isolate_voice.setText(self.tr_str("chk_isolate_voice"))
        if hasattr(self, 'chk_extract_audio'):
            self.chk_extract_audio.setText(self.tr_str("chk_extract_audio"))
        if hasattr(self, 'chk_free'):
            self.chk_free.setText(self.tr_str("chk_free"))
        if hasattr(self, 'chk_token_stats'):
            self.chk_token_stats.setText(self.tr_str("chk_token_stats"))
        if hasattr(self, 'chk_token_report'):
            self.chk_token_report.setText(self.tr_str("chk_token_report"))
        if hasattr(self, 'chk_thoughts_log'):
            self.chk_thoughts_log.setText(self.tr_str("chk_thoughts_log"))
        if hasattr(self, 'btn_adv_close'):
            self.btn_adv_close.setText(self.tr_str("btn_close"))

        # Action & Log Group
        if hasattr(self, 'action_log_group'):
            self.action_log_group.setTitle(self.tr_str("action_log_group_title"))
        if hasattr(self, 'btn_start'):
            self.btn_start.setText(self.tr_str("btn_start"))
        if hasattr(self, 'btn_stop'):
            self.btn_stop.setText(self.tr_str("btn_stop"))

        if hasattr(self, 'progress_bar'):
            if not (self.translation_worker and self.translation_worker.isRunning()):
                if self.completed_jobs == 0:
                    self.progress_bar.setFormat(self.tr_str("progress_idle"))
                elif self.completed_jobs >= self.total_jobs and self.total_jobs > 0:
                    self.progress_bar.setFormat(self.tr_str("progress_completed"))
                elif self.total_jobs > 0:
                    self.progress_bar.setFormat(self.tr_str("progress_interrupted", current=self.completed_jobs, total=self.total_jobs))

    def init_ui(self):
        self.setWindowTitle(APP_NAME)
        self.setGeometry(100, 100, 1000, 700)
        main_layout = QVBoxLayout(self)

        top_layout = QHBoxLayout()
        left_layout = QVBoxLayout()
        self._create_api_group(left_layout)
        self._create_main_options_group(left_layout)
        self._create_options_group(left_layout)
        left_layout.addStretch(1)

        right_layout = QVBoxLayout()
        self._create_file_lang_group(right_layout)

        top_layout.addLayout(left_layout, 1)
        top_layout.addLayout(right_layout, 1)

        main_layout.addLayout(top_layout)
        self._create_action_log_group(main_layout)
        self.setLayout(main_layout)

    def _create_api_group(self, parent_layout):
        self.api_group = QGroupBox("API 키 설정")
        api_layout = QFormLayout()
        self.api_key_inputs = []
        self.api_key_labels = []

        self._build_api_keys_dialog()

        api_keys_row = QHBoxLayout()
        self.btn_manage_api_keys = QPushButton("API 키 관리...")
        self.btn_manage_api_keys.clicked.connect(self._open_api_keys_dialog)
        self.lbl_api_keys_summary = QLabel("등록된 키: 0 / " + str(NUM_API_KEYS))
        
        self.lbl_app_lang = QLabel("언어/Lang:")
        self.cmb_app_lang = QComboBox()
        self.cmb_app_lang.addItems(["한국어", "English"])
        self.cmb_app_lang.currentIndexChanged.connect(self._on_app_lang_changed)

        api_keys_row.addWidget(self.btn_manage_api_keys)
        api_keys_row.addWidget(self.lbl_api_keys_summary)
        api_keys_row.addSpacing(15)
        api_keys_row.addWidget(self.lbl_app_lang)
        api_keys_row.addWidget(self.cmb_app_lang)
        api_keys_row.addStretch()
        api_layout.addRow(api_keys_row)

        enterprise_layout = QHBoxLayout()
        self.chk_use_enterprise = QCheckBox("Agent Platform (Enterprise) 사용")
        self.chk_use_enterprise.setChecked(False)
        self.chk_use_enterprise.stateChanged.connect(self._on_enterprise_changed)
        enterprise_layout.addWidget(self.chk_use_enterprise)
        enterprise_layout.addStretch()
        api_layout.addRow(enterprise_layout)

        self.cloud_project_input = QLineEdit()
        self.cloud_project_input.setPlaceholderText("Google Cloud Project ID (ADC)")
        self.cloud_api_key_input = QLineEdit()
        self.cloud_api_key_input.setPlaceholderText("Google Cloud API Key (Express)")
        self.cloud_api_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.cloud_location_input = QLineEdit()
        self.cloud_location_input.setPlaceholderText("Region (기본: global)")
        self.cmb_request_type = QComboBox()
        self.cmb_request_type.addItems(["Default", "shared", "dedicated"])

        self.cloud_project_label = QLabel("Cloud Project:")
        self.cloud_api_key_label = QLabel("Cloud API Key:")
        self.cloud_location_label = QLabel("Cloud Location:")
        self.request_type_label = QLabel("Request Type:")

        api_layout.addRow(self.cloud_project_label, self.cloud_project_input)
        api_layout.addRow(self.cloud_api_key_label, self.cloud_api_key_input)
        api_layout.addRow(self.cloud_location_label, self.cloud_location_input)
        api_layout.addRow(self.request_type_label, self.cmb_request_type)

        self._set_enterprise_visible(False)

        self.btn_save_api = QPushButton("설정 저장")
        self.btn_save_api.clicked.connect(self.save_settings)
        api_layout.addRow(self.btn_save_api)
        self.api_group.setLayout(api_layout)
        parent_layout.addWidget(self.api_group)

    def _build_api_keys_dialog(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("API 키 관리 (최대 10개)")
        dialog.setModal(True)

        outer_layout = QVBoxLayout(dialog)

        self.dialog_info_label = QLabel(
            "무료 할당량을 극대화하려면 여러 개의 Gemini API 키를 등록하세요.\n"
            "작업(job)마다 아래 순서대로 키를 돌려가며 사용합니다."
        )
        self.dialog_info_label.setWordWrap(True)
        outer_layout.addWidget(self.dialog_info_label)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll_content = QWidget()
        form_layout = QFormLayout(scroll_content)

        self.api_key_inputs = []
        self.api_key_labels = []

        for i in range(NUM_API_KEYS):
            label_text = f"API 키 {i+1}:"
            placeholder = "기본 API 키 (필수)" if i == 0 else f"추가 API 키 {i+1}"
            if i == 1:
                placeholder += " (gemini_api_key2로 사용)"
            label = QLabel(label_text)
            line_edit = QLineEdit()
            line_edit.setEchoMode(QLineEdit.EchoMode.Normal)
            line_edit.setPlaceholderText(placeholder)
            line_edit.textChanged.connect(self._update_api_keys_summary)
            form_layout.addRow(label, line_edit)
            self.api_key_labels.append(label)
            self.api_key_inputs.append(line_edit)

        scroll.setWidget(scroll_content)
        outer_layout.addWidget(scroll)

        btn_row = QHBoxLayout()
        self.btn_dialog_save = QPushButton("저장")
        self.btn_dialog_save.clicked.connect(self.save_settings)
        self.btn_dialog_close = QPushButton("닫기")
        self.btn_dialog_close.clicked.connect(dialog.accept)
        btn_row.addStretch()
        btn_row.addWidget(self.btn_dialog_save)
        btn_row.addWidget(self.btn_dialog_close)
        outer_layout.addLayout(btn_row)

        dialog.resize(480, 500)
        self.api_keys_dialog = dialog

    def _open_api_keys_dialog(self):
        self._update_api_keys_summary()
        self.api_keys_dialog.exec()
        self._update_api_keys_summary()

    def _update_api_keys_summary(self):
        filled = sum(1 for le in self.api_key_inputs if le.text().strip())
        self.lbl_api_keys_summary.setText(
            self.tr_str("lbl_api_keys_summary", filled=filled, total=NUM_API_KEYS)
        )

    def _set_enterprise_visible(self, visible):
        widgets = [
            self.cloud_project_label, self.cloud_project_input,
            self.cloud_api_key_label, self.cloud_api_key_input,
            self.cloud_location_label, self.cloud_location_input,
            self.request_type_label, self.cmb_request_type,
        ]
        for w in widgets:
            w.setVisible(visible)

    def _on_enterprise_changed(self, state):
        self._set_enterprise_visible(state == Qt.CheckState.Checked.value)

    def _create_file_lang_group(self, parent_layout):
        self.file_lang_group = QGroupBox("파일 및 언어 설정")
        layout = QVBoxLayout()

        task_mode_layout = QHBoxLayout()
        self.lbl_task_mode = QLabel("작업 모드:")
        task_mode_layout.addWidget(self.lbl_task_mode)
        self.cmb_task_mode = QComboBox()
        self.cmb_task_mode.addItems([
            "자막 번역 (Translate SRT/ASS)",
            "비디오/오디오 전사 (Transcribe to SRT)"
        ])
        self.cmb_task_mode.currentIndexChanged.connect(self._on_task_mode_changed)
        task_mode_layout.addWidget(self.cmb_task_mode, 1)
        layout.addLayout(task_mode_layout)

        input_layout = QHBoxLayout()
        self.btn_files = QPushButton("입력 SRT/ASS 파일 선택 (번역용)")
        self.btn_files.clicked.connect(self.select_input_files)
        input_layout.addWidget(self.btn_files)
        self.btn_clear_files = QPushButton("X")
        self.btn_clear_files.clicked.connect(self.clear_input_files)
        self.btn_clear_files.setFixedWidth(30)
        input_layout.addWidget(self.btn_clear_files)
        layout.addLayout(input_layout)

        self.lst_files = QListWidget()
        self.lst_files.setMinimumHeight(40)
        self.lst_files.setMaximumHeight(80)
        layout.addWidget(self.lst_files)

        output_layout = QHBoxLayout()
        self.btn_out = QPushButton("출력 폴더 선택")
        self.btn_out.clicked.connect(self.select_output_directory)
        self.lbl_out = QLineEdit(self.output_dir)
        self.lbl_out.setReadOnly(True)
        output_layout.addWidget(self.btn_out)
        output_layout.addWidget(self.lbl_out, 1)
        layout.addLayout(output_layout)

        video_file_layout = QHBoxLayout()
        self.btn_video_file = QPushButton("비디오 파일 선택 (다중 가능)")
        self.btn_video_file.clicked.connect(self.select_video_file)
        video_file_layout.addWidget(self.btn_video_file)
        self.btn_clear_video_file = QPushButton("X")
        self.btn_clear_video_file.clicked.connect(self.clear_video_file)
        self.btn_clear_video_file.setFixedWidth(30)
        video_file_layout.addWidget(self.btn_clear_video_file)
        layout.addLayout(video_file_layout)

        self.lst_video_files = QListWidget()
        self.lst_video_files.setMinimumHeight(40)
        self.lst_video_files.setMaximumHeight(80)
        self.lst_video_files.setToolTip("전사 타겟(순차 처리) 또는 번역 컨텍스트로 사용될 비디오 파일 목록")
        layout.addWidget(self.lst_video_files)

        audio_file_layout = QHBoxLayout()
        self.btn_audio_file = QPushButton("오디오 파일 선택")
        self.btn_audio_file.clicked.connect(self.select_audio_file)
        audio_file_layout.addWidget(self.btn_audio_file)
        self.lbl_audio_file = QLineEdit()
        self.lbl_audio_file.setPlaceholderText("오디오 파일 (전사 타겟 또는 번역 컨텍스트)")
        self.lbl_audio_file.setReadOnly(True)
        audio_file_layout.addWidget(self.lbl_audio_file, 1)
        self.btn_clear_audio_file = QPushButton("X")
        self.btn_clear_audio_file.clicked.connect(self.clear_audio_file)
        self.btn_clear_audio_file.setFixedWidth(30)
        audio_file_layout.addWidget(self.btn_clear_audio_file)
        layout.addLayout(audio_file_layout)

        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        layout.addWidget(line)

        lang_header_layout = QHBoxLayout()
        self.lbl_target_lang = QLabel("출력 대상 언어:")
        lang_header_layout.addWidget(self.lbl_target_lang)
        lang_header_layout.addStretch()
        self.btn_all_lang = QPushButton("전체 선택")
        self.btn_all_lang.clicked.connect(self.select_all_languages)
        self.btn_none_lang = QPushButton("전체 해제")
        self.btn_none_lang.clicked.connect(self.deselect_all_languages)
        lang_header_layout.addWidget(self.btn_all_lang)
        lang_header_layout.addWidget(self.btn_none_lang)
        layout.addLayout(lang_header_layout)

        self.cmb_langs = CheckableComboBox()
        for lang in TARGET_LANGUAGES:
            self.cmb_langs.addItem(lang)
        layout.addWidget(self.cmb_langs)
        self.file_lang_group.setLayout(layout)
        parent_layout.addWidget(self.file_lang_group)

    def _on_task_mode_changed(self, index):
        is_transcribe = (index == 1)
        self.btn_files.setEnabled(not is_transcribe)
        self.lst_files.setEnabled(not is_transcribe)
        self.btn_clear_files.setEnabled(not is_transcribe)
        if is_transcribe:
            self.btn_video_file.setStyleSheet("font-weight: bold; color: #4CAF50;")
            self.btn_audio_file.setStyleSheet("font-weight: bold; color: #4CAF50;")
        else:
            self.btn_video_file.setStyleSheet("")
            self.btn_audio_file.setStyleSheet("")

    def _create_main_options_group(self, parent_layout):
        self.main_options_group = QGroupBox("기본 설정")
        form_layout = QFormLayout()

        model_layout = QHBoxLayout()
        self.btn_fetch = QPushButton("모델 가져오기")
        self.btn_fetch.clicked.connect(self.fetch_models)
        if not genai:
            self.btn_fetch.setEnabled(False)
        self.cmb_model = QComboBox()
        self.cmb_model.addItem(DEFAULT_MODEL)
        model_layout.addWidget(self.btn_fetch)
        model_layout.addWidget(self.cmb_model, 1)
        self.lbl_model = QLabel("사용 모델:")
        form_layout.addRow(self.lbl_model, model_layout)

        self.chk_append_lang = QCheckBox("출력 파일명에 언어명 접미사 추가")
        self.chk_append_lang.setChecked(True)
        self.chk_reuse_extracted = QCheckBox("추출된 자막 재사용 (재추출 안 함)")
        self.chk_reuse_extracted.setChecked(True)
        lang_row_layout = QHBoxLayout()
        lang_row_layout.setContentsMargins(0, 0, 0, 0)
        lang_row_layout.addWidget(self.chk_append_lang)
        lang_row_layout.addSpacing(16)
        lang_row_layout.addWidget(self.chk_reuse_extracted)
        lang_row_layout.addStretch()
        form_layout.addRow(lang_row_layout)

        batch_layout = QHBoxLayout()
        self.spin_batch = QSpinBox()
        self.spin_batch.setRange(1, 5000)
        self.spin_batch.setValue(DEFAULT_BATCH_SIZE)
        batch_layout.addWidget(self.spin_batch)
        batch_layout.addStretch()
        self.lbl_batch = QLabel("배치 크기:")
        form_layout.addRow(self.lbl_batch, batch_layout)

        self.lbl_prompt = QLabel("프롬프트/지침 입력 (선택):")
        self.txt_desc = QTextEdit()
        self.txt_desc.setMinimumHeight(60)
        self.txt_desc.setMaximumHeight(80)
        self.txt_desc.setPlaceholderText("번역/전사 시 AI가 참고할 문맥을 입력하세요.")
        form_layout.addRow(self.lbl_prompt)
        form_layout.addRow(self.txt_desc)

        self.main_options_group.setLayout(form_layout)
        parent_layout.addWidget(self.main_options_group)

    def _create_options_group(self, parent_layout):
        btn_layout = QHBoxLayout()
        self.btn_advanced = QPushButton("⚙ 고급 설정 및 튜닝 (v3.8.3 기능) 열기")
        self.btn_advanced.clicked.connect(self.open_advanced_settings)
        btn_layout.addWidget(self.btn_advanced)
        parent_layout.addLayout(btn_layout)

        self.advanced_dialog = QDialog(self)
        self.advanced_dialog.setWindowTitle("고급 설정 및 튜닝 (v3.8.3 기능)")
        self.advanced_dialog.setMinimumWidth(440)
        dialog_layout = QVBoxLayout(self.advanced_dialog)

        main_form_layout = QFormLayout()

        service_layout = QHBoxLayout()
        self.cmb_service_tier = QComboBox()
        self.cmb_service_tier.addItems(["Default", "standard", "flex", "priority"])
        service_layout.addWidget(self.cmb_service_tier)
        service_layout.addStretch()
        self.lbl_service_tier = QLabel("서비스 티어:")
        main_form_layout.addRow(self.lbl_service_tier, service_layout)

        start_layout = QHBoxLayout()
        self.spin_start = QSpinBox()
        self.spin_start.setRange(1, 99999)
        self.spin_start.setValue(1)
        start_layout.addWidget(self.spin_start)
        start_layout.addStretch()
        self.lbl_start_line = QLabel("시작 라인:")
        main_form_layout.addRow(self.lbl_start_line, start_layout)

        tuning_grid_layout = QFormLayout()

        temp_top_p_layout = QHBoxLayout()
        self.spin_temp = QDoubleSpinBox()
        self.spin_temp.setRange(0.0, 2.0)
        self.spin_temp.setValue(0.9)
        self.spin_temp.setSingleStep(0.1)
        self.spin_temp.setSpecialValueText("기본값")
        temp_top_p_layout.addWidget(self.spin_temp)
        temp_top_p_layout.addSpacing(10)
        self.lbl_top_p = QLabel("Top_p:")
        temp_top_p_layout.addWidget(self.lbl_top_p)
        self.spin_top_p = QDoubleSpinBox()
        self.spin_top_p.setRange(0.0, 1.0)
        self.spin_top_p.setValue(1.0)
        self.spin_top_p.setSingleStep(0.1)
        self.spin_top_p.setSpecialValueText("기본값")
        temp_top_p_layout.addWidget(self.spin_top_p)
        tuning_grid_layout.addRow("Temp:", temp_top_p_layout)

        top_k_budget_layout = QHBoxLayout()
        self.spin_top_k = QSpinBox()
        self.spin_top_k.setRange(0, 100)
        self.spin_top_k.setValue(0)
        self.spin_top_k.setSpecialValueText("기본값")
        top_k_budget_layout.addWidget(self.spin_top_k)
        top_k_budget_layout.addSpacing(10)
        self.lbl_thinking_budget = QLabel("사고 예산:")
        top_k_budget_layout.addWidget(self.lbl_thinking_budget)
        self.spin_thinking_budget = QSpinBox()
        self.spin_thinking_budget.setRange(0, 32768)
        self.spin_thinking_budget.setValue(2048)
        top_k_budget_layout.addWidget(self.spin_thinking_budget)
        tuning_grid_layout.addRow("Top_k:", top_k_budget_layout)

        level_layout = QHBoxLayout()
        self.cmb_thinking_level = QComboBox()
        self.cmb_thinking_level.addItems(["Default", "Minimal", "Low", "Medium", "High"])
        level_layout.addWidget(self.cmb_thinking_level)
        level_layout.addSpacing(10)
        self.lbl_audio_chunk = QLabel("오디오청크:")
        level_layout.addWidget(self.lbl_audio_chunk)
        self.spin_audio_chunk = QSpinBox()
        self.spin_audio_chunk.setRange(60, 3600)
        self.spin_audio_chunk.setValue(300)
        level_layout.addWidget(self.spin_audio_chunk)
        self.lbl_thinking_level = QLabel("사고 수준:")
        tuning_grid_layout.addRow(self.lbl_thinking_level, level_layout)
        main_form_layout.addRow(tuning_grid_layout)

        resume_layout = QHBoxLayout()
        self.spin_resume_context = QSpinBox()
        self.spin_resume_context.setRange(0, 10000)
        self.spin_resume_context.setValue(0)
        self.spin_resume_context.setSpecialValueText("기본값 (자동)")
        resume_layout.addWidget(self.spin_resume_context)
        self.lbl_resume_help = QLabel("(문맥/재개 시 참조 라인 수, 0: 비활성)")
        resume_layout.addWidget(self.lbl_resume_help)
        resume_layout.addStretch()
        self.lbl_resume_context = QLabel("Context Size:")
        main_form_layout.addRow(self.lbl_resume_context, resume_layout)

        adaptive_layout = QHBoxLayout()
        self.lbl_batch_step = QLabel("배치 축소단위:")
        adaptive_layout.addWidget(self.lbl_batch_step)
        self.spin_batch_error_step = QSpinBox()
        self.spin_batch_error_step.setRange(10, 1000)
        self.spin_batch_error_step.setValue(100)
        self.spin_batch_error_step.setSingleStep(50)
        adaptive_layout.addWidget(self.spin_batch_error_step)
        adaptive_layout.addSpacing(10)

        self.lbl_audio_step = QLabel("오디오 축소단위:")
        adaptive_layout.addWidget(self.lbl_audio_step)
        self.spin_audio_chunk_error_step = QSpinBox()
        self.spin_audio_chunk_error_step.setRange(10, 600)
        self.spin_audio_chunk_error_step.setValue(60)
        self.spin_audio_chunk_error_step.setSingleStep(30)
        adaptive_layout.addWidget(self.spin_audio_chunk_error_step)
        adaptive_layout.addSpacing(10)

        self.lbl_adaptive_help = QLabel("(오류 시 자동감축)")
        adaptive_layout.addWidget(self.lbl_adaptive_help)
        adaptive_layout.addStretch()
        main_form_layout.addRow("적응형 복구:", adaptive_layout)

        box1 = QHBoxLayout()
        self.chk_streaming = QCheckBox("스트리밍")
        self.chk_streaming.setChecked(True)
        self.chk_thinking = QCheckBox("사고기능")
        self.chk_thinking.setChecked(True)
        self.chk_preserve_context = QCheckBox("문맥 유지")
        self.chk_preserve_context.setChecked(True)
        box1.addWidget(self.chk_streaming)
        box1.addWidget(self.chk_thinking)
        box1.addWidget(self.chk_preserve_context)
        main_form_layout.addRow(box1)

        box2 = QHBoxLayout()
        self.chk_isolate_voice = QCheckBox("보이스 격리")
        self.chk_isolate_voice.setChecked(True)
        self.chk_extract_audio = QCheckBox("번역 전 추출")
        self.chk_extract_audio.setChecked(False)
        self.chk_free = QCheckBox("무료 쿼터")
        self.chk_free.setChecked(True)
        box2.addWidget(self.chk_isolate_voice)
        box2.addWidget(self.chk_extract_audio)
        box2.addWidget(self.chk_free)
        main_form_layout.addRow(box2)

        box3 = QHBoxLayout()
        self.chk_token_stats = QCheckBox("토큰 실시간 통계")
        self.chk_token_stats.setChecked(True)
        self.chk_token_report = QCheckBox("비용 리포트 저장 (.json)")
        self.chk_token_report.setChecked(False)
        self.chk_thoughts_log = QCheckBox("사고 로그")
        self.chk_thoughts_log.setChecked(False)
        box3.addWidget(self.chk_token_stats)
        box3.addWidget(self.chk_token_report)
        box3.addWidget(self.chk_thoughts_log)
        main_form_layout.addRow(box3)

        dialog_layout.addLayout(main_form_layout)

        dialog_btn_layout = QHBoxLayout()
        dialog_btn_layout.addStretch()
        self.btn_adv_close = QPushButton("닫기")
        self.btn_adv_close.clicked.connect(self.advanced_dialog.accept)
        dialog_btn_layout.addWidget(self.btn_adv_close)
        dialog_layout.addLayout(dialog_btn_layout)

    def open_advanced_settings(self):
        self.advanced_dialog.exec()

    def _create_action_log_group(self, parent_layout):
        self.action_log_group = QGroupBox("터미널 출력 (VT100 Engine)")
        layout = QVBoxLayout()

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFormat("대기 중")
        layout.addWidget(self.progress_bar)

        button_layout = QHBoxLayout()
        self.btn_start = QPushButton("🚀 작업 시작")
        self.btn_start.setFont(QFont('Arial', 12, QFont.Weight.Bold))
        self.btn_start.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.btn_start.clicked.connect(self.start_translation)
        if not gst:
            self.btn_start.setEnabled(False)

        self.btn_stop = QPushButton("🛑 작업 중단")
        self.btn_stop.setFont(QFont('Arial', 12, QFont.Weight.Bold))
        self.btn_stop.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self.stop_translation)

        button_layout.addWidget(self.btn_start)
        button_layout.addWidget(self.btn_stop)
        layout.addLayout(button_layout)

        self.log_output = PyteTerminalWidget()
        self.log_output.setMinimumHeight(250)
        layout.addWidget(self.log_output)
        self.action_log_group.setLayout(layout)
        parent_layout.addWidget(self.action_log_group)

    # ---------------------------------------------------------------
    # [버그 수정] 자막 파일 목록 지우기 메서드 (video/audio와 동일한 패턴)
    # ---------------------------------------------------------------
    def clear_input_files(self):
        self.input_files = []
        self.lst_files.clear()

    def clear_video_file(self):
        self.video_file_paths = []
        self.lst_video_files.clear()

    def clear_audio_file(self):
        self.audio_file_path = ""
        self.lbl_audio_file.setText("")
        self.lbl_audio_file.setToolTip("")

    def select_video_file(self):
        files, _ = QFileDialog.getOpenFileNames(
            self, "비디오 파일 선택 (다중 선택 가능)",
            self.settings.value("last_media_dir", self.output_dir),
            "Video Files (*.mp4 *.mkv *.avi *.mov *.webm *.flv *.wmv);;All Files (*)"
        )
        if files:
            self.video_file_paths = files
            self.lst_video_files.clear()
            for f in files:
                item = QListWidgetItem(os.path.basename(f))
                item.setToolTip(f)
                self.lst_video_files.addItem(item)
            self.settings.setValue("last_media_dir", os.path.dirname(files[0]))

    def select_audio_file(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "오디오 파일 선택",
            self.settings.value("last_media_dir", self.output_dir),
            "Audio Files (*.mp3 *.wav *.aac *.m4a *.ogg *.flac *.wma);;All Files (*)"
        )
        if file_path:
            self.audio_file_path = file_path
            self.lbl_audio_file.setText(os.path.basename(file_path))
            self.lbl_audio_file.setToolTip(file_path)
            self.settings.setValue("last_media_dir", os.path.dirname(file_path))

    def select_input_files(self):
        last_input_dir = self.settings.value("last_input_dir", self.output_dir)
        files, _ = QFileDialog.getOpenFileNames(
            self, "SRT/ASS 파일 선택", last_input_dir,
            "Subtitle Files (*.srt *.ass);;All Files (*)"
        )
        if files:
            self.input_files = files
            self.lst_files.clear()
            for f in files:
                base_name = os.path.basename(f)
                item = QListWidgetItem(base_name)
                item.setToolTip(f)
                self.lst_files.addItem(item)
            self.settings.setValue("last_input_dir", os.path.dirname(files[0]))

    def select_output_directory(self):
        directory = QFileDialog.getExistingDirectory(self, "출력 폴더 선택", self.output_dir)
        if directory:
            self.output_dir = directory
            self.lbl_out.setText(directory)
            self.save_settings()

    def select_all_languages(self):
        self.cmb_langs.set_checked_items(TARGET_LANGUAGES)

    def deselect_all_languages(self):
        self.cmb_langs.set_checked_items([])

    def load_settings(self):
        try:
            for i in range(NUM_API_KEYS):
                if i < len(self.api_key_inputs):
                    self.api_key_inputs[i].setText(
                        self.settings.value(API_KEY_SETTINGS[i], "")
                    )

            # Restore UI language first so all subsequent tr_str() calls are correct
            saved_lang = self.settings.value("app_lang", "ko", type=str)
            self.app_lang = saved_lang if saved_lang in I18N else "ko"
            lang_index = 0 if self.app_lang == "ko" else 1
            self.cmb_app_lang.blockSignals(True)
            self.cmb_app_lang.setCurrentIndex(lang_index)
            self.cmb_app_lang.blockSignals(False)

            last_model = self.settings.value("last_model", DEFAULT_MODEL)
            if self.cmb_model.findText(last_model) >= 0:
                self.cmb_model.setCurrentText(last_model)
            else:
                self.cmb_model.setCurrentText(DEFAULT_MODEL)

            self.spin_batch.setValue(
                self.settings.value("batch_size", DEFAULT_BATCH_SIZE, type=int)
            )
            self.lbl_out.setText(self.output_dir)
            self.cmb_task_mode.setCurrentIndex(
                self.settings.value("task_mode_index", 0, type=int)
            )
            self.chk_append_lang.setChecked(
                self.settings.value("append_lang", True, type=bool)
            )
            self.chk_reuse_extracted.setChecked(
                self.settings.value("reuse_extracted", True, type=bool)
            )
            self.spin_audio_chunk.setValue(
                self.settings.value("audio_chunk_size", 300, type=int)
            )
            self.chk_isolate_voice.setChecked(
                self.settings.value("isolate_voice", True, type=bool)
            )
            self.cmb_thinking_level.setCurrentText(
                self.settings.value("thinking_level", "Default", type=str)
            )
            self.txt_desc.setText(
                self.settings.value("prompt_desc", "", type=str)
            )

            saved_video_paths_str = str(self.settings.value("video_file_paths", "") or "")
            saved_video_paths = saved_video_paths_str.split('\n') if saved_video_paths_str else []
            self.video_file_paths = [p for p in saved_video_paths if p and os.path.exists(p)]
            self.lst_video_files.clear()
            for f in self.video_file_paths:
                item = QListWidgetItem(os.path.basename(f))
                item.setToolTip(f)
                self.lst_video_files.addItem(item)

            self.audio_file_path = str(self.settings.value("audio_file_path", "") or "")
            if self.audio_file_path and os.path.exists(self.audio_file_path):
                self.lbl_audio_file.setText(os.path.basename(self.audio_file_path))
                self.lbl_audio_file.setToolTip(self.audio_file_path)
            else:
                self.audio_file_path = ""

            self.chk_extract_audio.setChecked(
                self.settings.value("extract_audio", False, type=bool)
            )
            self.chk_preserve_context.setChecked(
                self.settings.value("preserve_context", True, type=bool)
            )
            self.chk_token_stats.setChecked(
                self.settings.value("token_stats", True, type=bool)
            )
            self.chk_token_report.setChecked(
                self.settings.value("token_report", False, type=bool)
            )

            saved_languages_str = str(self.settings.value("selected_languages", "") or "")
            saved_languages = saved_languages_str.split(',') if saved_languages_str else []
            self.cmb_langs.set_checked_items([lang for lang in saved_languages if lang in TARGET_LANGUAGES])

            self.spin_temp.setValue(
                self.settings.value("temperature", 0.9, type=float)
            )
            self.spin_top_p.setValue(
                self.settings.value("top_p", 1.0, type=float)
            )
            self.spin_top_k.setValue(
                self.settings.value("top_k", 0, type=int)
            )
            self.chk_streaming.setChecked(
                self.settings.value("streaming", True, type=bool)
            )
            self.chk_thinking.setChecked(
                self.settings.value("thinking", True, type=bool)
            )
            self.spin_thinking_budget.setValue(
                self.settings.value("thinking_budget", 2048, type=int)
            )
            self.chk_thoughts_log.setChecked(
                self.settings.value("thoughts_log", False, type=bool)
            )
            self.chk_free.setChecked(
                self.settings.value("free_quota", True, type=bool)
            )

            self.spin_resume_context.setValue(
                self.settings.value("resume_context_size", 0, type=int)
            )
            self.spin_batch_error_step.setValue(
                self.settings.value("batch_size_error_step", 100, type=int)
            )
            self.spin_audio_chunk_error_step.setValue(
                self.settings.value("audio_chunk_error_step", 60, type=int)
            )
            self.cmb_service_tier.setCurrentText(
                self.settings.value("service_tier", "Default", type=str)
            )
            self.chk_use_enterprise.setChecked(
                self.settings.value("use_enterprise", False, type=bool)
            )
            self.cloud_project_input.setText(
                self.settings.value("cloud_project", "", type=str)
            )
            self.cloud_api_key_input.setText(
                self.settings.value("cloud_api_key", "", type=str)
            )
            self.cloud_location_input.setText(
                self.settings.value("cloud_location", "", type=str)
            )
            self.cmb_request_type.setCurrentText(
                self.settings.value("request_type", "Default", type=str)
            )

            self._on_enterprise_changed(
                Qt.CheckState.Checked.value if self.chk_use_enterprise.isChecked() else 0
            )

            self.update_ui_language()
            self.append_log(f"\x1b[32m{self.tr_str('log_settings_loaded')}\x1b[0m")
        except Exception as e:
            self.append_log(f"\x1b[33m[Warning] Settings load error: {e}\x1b[0m")

    def save_settings(self):
        try:
            for i in range(NUM_API_KEYS):
                if i < len(self.api_key_inputs):
                    self.settings.setValue(
                        API_KEY_SETTINGS[i], self.api_key_inputs[i].text()
                    )
            if self.cmb_model.count() > 0:
                self.settings.setValue("last_model", self.cmb_model.currentText())
            self.settings.setValue("batch_size", self.spin_batch.value())
            self.settings.setValue("output_dir", self.output_dir)
            self.settings.setValue("task_mode_index", self.cmb_task_mode.currentIndex())
            self.settings.setValue("append_lang", self.chk_append_lang.isChecked())
            self.settings.setValue("reuse_extracted", self.chk_reuse_extracted.isChecked())
            self.settings.setValue("audio_chunk_size", self.spin_audio_chunk.value())
            self.settings.setValue("isolate_voice", self.chk_isolate_voice.isChecked())
            self.settings.setValue("thinking_level", self.cmb_thinking_level.currentText())
            self.settings.setValue("prompt_desc", self.txt_desc.toPlainText())

            valid_video_paths = [p for p in self.video_file_paths if p and os.path.exists(p)]
            self.settings.setValue("video_file_paths", '\n'.join(valid_video_paths))
            self.settings.setValue(
                "audio_file_path",
                self.audio_file_path if self.audio_file_path and os.path.exists(self.audio_file_path) else ""
            )
            self.settings.setValue("extract_audio", self.chk_extract_audio.isChecked())
            self.settings.setValue("preserve_context", self.chk_preserve_context.isChecked())
            self.settings.setValue("token_stats", self.chk_token_stats.isChecked())
            self.settings.setValue("token_report", self.chk_token_report.isChecked())

            selected_languages = self.cmb_langs.checked_items()
            self.settings.setValue("selected_languages", ','.join(selected_languages))
            self.settings.setValue("temperature", self.spin_temp.value())
            self.settings.setValue("top_p", self.spin_top_p.value())
            self.settings.setValue("top_k", self.spin_top_k.value())
            self.settings.setValue("streaming", self.chk_streaming.isChecked())
            self.settings.setValue("thinking", self.chk_thinking.isChecked())
            self.settings.setValue("thinking_budget", self.spin_thinking_budget.value())
            self.settings.setValue("thoughts_log", self.chk_thoughts_log.isChecked())
            self.settings.setValue("free_quota", self.chk_free.isChecked())

            self.settings.setValue("resume_context_size", self.spin_resume_context.value())
            self.settings.setValue("batch_size_error_step", self.spin_batch_error_step.value())
            self.settings.setValue("audio_chunk_error_step", self.spin_audio_chunk_error_step.value())
            self.settings.setValue("service_tier", self.cmb_service_tier.currentText())
            self.settings.setValue("use_enterprise", self.chk_use_enterprise.isChecked())
            self.settings.setValue("cloud_project", self.cloud_project_input.text())
            self.settings.setValue("cloud_api_key", self.cloud_api_key_input.text())
            self.settings.setValue("cloud_location", self.cloud_location_input.text())
            self.settings.setValue("app_lang", self.app_lang)
            self.settings.setValue("request_type", self.cmb_request_type.currentText())
        except Exception:
            pass

    def closeEvent(self, event):
        if self.model_fetcher_thread and self.model_fetcher_thread.isRunning():
            self.model_fetcher_thread.quit()
            self.model_fetcher_thread.wait(2000)

        if self.translation_worker and self.translation_worker.isRunning():
            reply = QMessageBox.question(
                self, '종료 확인',
                "작업이 진행 중입니다. 프로그램을 종료하시겠습니까?\n\n"
                "(현재 작업은 중단되며, 재개 기능으로 나중에 이어서 할 수 있습니다.)",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.Yes:
                self.stop_translation()
                self.translation_worker.wait(5000)
                self.save_settings()
                event.accept()
            else:
                event.ignore()
        else:
            self.save_settings()
            event.accept()

    def append_log(self, text: str):
        self.log_output.feed_line(text)

    def fetch_models(self):
        if not genai:
            QMessageBox.critical(self, "오류", "'google-genai' 필요")
            return
        api_key = self.api_key_inputs[0].text().strip()
        if not api_key:
            QMessageBox.warning(self, "API 키 필요", "기본 API 키(1)가 필요합니다.")
            return

        if self.model_fetcher_thread and self.model_fetcher_thread.isRunning():
            return

        self.log_output.clear_screen()
        QApplication.processEvents()
        self.append_log("모델 목록 가져오는 중...")
        self.btn_fetch.setEnabled(False)

        self.model_fetcher_thread = ModelFetcherThread(api_key=api_key)
        self.model_fetcher_thread.models_fetched.connect(self.update_model_list)
        self.model_fetcher_thread.error_occurred.connect(self.handle_fetch_error)
        self.model_fetcher_thread.finished.connect(self._on_fetch_finished)
        self.model_fetcher_thread.start()

    def _on_fetch_finished(self):
        self.btn_fetch.setEnabled(True)
        if self.model_fetcher_thread:
            self.model_fetcher_thread.deleteLater()
            self.model_fetcher_thread = None

    def update_model_list(self, models):
        self.append_log(f"\x1b[32m{self.tr_str('log_models_fetched', count=len(models))}\x1b[0m")
        current_selection = self.cmb_model.currentText()
        last_saved_model = self.settings.value("last_model", DEFAULT_MODEL)
        self.cmb_model.clear()
        self.cmb_model.addItems(models)

        selected_model = DEFAULT_MODEL
        if current_selection in models:
            selected_model = current_selection
        elif last_saved_model in models:
            selected_model = last_saved_model
        elif DEFAULT_MODEL in models:
            selected_model = DEFAULT_MODEL
        elif models:
            selected_model = models[0]

        if self.cmb_model.findText(selected_model) >= 0:
            self.cmb_model.setCurrentText(selected_model)
        elif models:
            self.cmb_model.setCurrentIndex(0)
        else:
            self.cmb_model.addItem(DEFAULT_MODEL)
            self.cmb_model.setCurrentText(DEFAULT_MODEL)
        self.save_settings()

    def handle_fetch_error(self, error_message):
        self.append_log(f"\x1b[31m{self.tr_str('log_models_fetch_err', err=error_message)}\x1b[0m")
        if self.cmb_model.findText(DEFAULT_MODEL) < 0:
            self.cmb_model.clear()
            self.cmb_model.addItem(DEFAULT_MODEL)
        self.cmb_model.setCurrentText(DEFAULT_MODEL)

    def _create_translation_jobs(self, target_languages, primary_input_source,
                                  is_media_source_only, is_transcribe_mode, media_type=None,
                                  video_context_paths=None):
        jobs = []
        if not primary_input_source or not target_languages or not self.output_dir:
            return jobs

        if isinstance(primary_input_source, list):
            source_files_to_process = list(primary_input_source)
        elif isinstance(primary_input_source, str):
            source_files_to_process = [primary_input_source]
        else:
            source_files_to_process = []

        if is_media_source_only:
            source_files_to_process = [
                p for p in source_files_to_process if os.path.exists(p)
            ]

        if not source_files_to_process:
            return jobs

        append_lang = self.chk_append_lang.isChecked()
        valid_video_contexts = [v for v in (video_context_paths or []) if os.path.exists(v)]

        for lang in target_languages:
            for idx, src_file_path in enumerate(source_files_to_process):
                try:
                    base_name, ext = os.path.splitext(os.path.basename(src_file_path))
                    if base_name.endswith("_extracted"):
                        base_name = base_name[:-10]
                    tag = "_transcribed" if is_transcribe_mode else ""
                    if append_lang or len(target_languages) > 1:
                        iso_code = _get_iso_lang_code(lang)
                        output_filename = f"{base_name}{tag}.{iso_code}.srt"
                    else:
                        output_filename = f"{base_name}{tag}.srt"
                    output_filepath = os.path.join(self.output_dir, output_filename)

                    job_video_file = None
                    if is_media_source_only and media_type == 'video':
                        job_video_file = src_file_path
                    elif valid_video_contexts:
                        stem = base_name.lower()
                        match = next((v for v in valid_video_contexts if os.path.splitext(os.path.basename(v))[0].lower() == stem), None)
                        if match:
                            job_video_file = match
                        elif len(valid_video_contexts) == len(source_files_to_process):
                            job_video_file = valid_video_contexts[idx]
                        else:
                            job_video_file = valid_video_contexts[0]

                    jobs.append((src_file_path, lang, output_filepath, is_media_source_only, media_type, job_video_file))
                except Exception:
                    pass
        return jobs

    def start_translation(self):
        if not gst:
            QMessageBox.critical(
                self, "오류",
                "'gemini-srt-translator' 라이브러리를 불러올 수 없습니다.\n"
                f"{GST_IMPORT_ERROR or ''}"
            )
            return

        valid_api_keys_from_ui = [
            k.text().strip() for k in self.api_key_inputs if k.text().strip()
        ]
        if not valid_api_keys_from_ui:
            QMessageBox.warning(self, "API 키", "API 키를 하나 이상 입력해야 합니다.")
            return

        # 새 작업 시작 전 이전 로그 및 터미널 화면 초기화
        reset_library_logger()
        self.log_output.clear_screen()
        logging.getLogger().handlers.clear()
        QApplication.processEvents()

        is_transcribe_mode = self.cmb_task_mode.currentIndex() == 1
        primary_input_source_for_jobs = None
        source_is_media_only_for_jobs = False
        media_type_for_jobs = None

        valid_video_paths = [p for p in self.video_file_paths if os.path.exists(p)]

        selected_languages = self.cmb_langs.checked_items()
        if not selected_languages:
            QMessageBox.warning(self, "언어 선택", "대상 언어를 하나 이상 선택하세요.")
            return

        if not self.output_dir or not os.path.isdir(self.output_dir):
            try:
                os.makedirs(self.output_dir, exist_ok=True)
            except OSError as e:
                QMessageBox.critical(
                    self, "출력 폴더 오류", f"출력 폴더를 생성할 수 없습니다:\n{e}"
                )
                return

        if is_transcribe_mode:
            if valid_video_paths:
                primary_input_source_for_jobs = valid_video_paths
                source_is_media_only_for_jobs = True
                media_type_for_jobs = 'video'
            elif self.audio_file_path and os.path.exists(self.audio_file_path):
                primary_input_source_for_jobs = [self.audio_file_path]
                source_is_media_only_for_jobs = True
                media_type_for_jobs = 'audio'
            else:
                QMessageBox.warning(
                    self, "미디어 필요", "전사(Transcribe)할 대상 비디오/오디오 파일을 선택하세요."
                )
                return
        else:
            if self.input_files:
                primary_input_source_for_jobs = self.input_files
            elif valid_video_paths:
                # -------------------------------------------------------------
                # [신규 워크플로우] 자막 파일 없이 영상 파일만 선택된 경우
                # 1. 내장 자막 트랙이 있는지 ffprobe로 검사
                # 2. 자막 트랙이 있으면:
                #    - 목표 언어와 동일한 트랙 -> 번역 없이 추출하여 바로 저장
                #    - 그 외: 영어(English) 트랙 우선(없으면 첫 번째 트랙) 추출하여 번역 대상으로 설정
                # 3. 자막 트랙이 없으면: 오디오 추출 후 전사할지 사용자에게 질문
                # -------------------------------------------------------------
                extracted_sub_files = []
                videos_without_subs = []
                saved_direct_count = 0

                norm_target_langs = {l: _normalize_lang_name(l) for l in selected_languages}
                total_vids = len(valid_video_paths)

                self.progress_bar.setRange(0, 100)
                self.progress_bar.setValue(0)
                self.progress_bar.setFormat("자막 트랙 검사 중... (0%)")
                QApplication.processEvents()

                for v_idx, vpath in enumerate(valid_video_paths):
                    v_basename = os.path.splitext(os.path.basename(vpath))[0]
                    self.append_log(f"\x1b[34m[자막 트랙 검사 ({v_idx+1}/{total_vids})] '{os.path.basename(vpath)}' 분석 중...\x1b[0m")
                    QApplication.processEvents()
                    streams = _get_video_subtitle_streams(vpath)

                    if not streams:
                        self.append_log(f"\x1b[33m  → 내장 자막 트랙 없음\x1b[0m")
                        videos_without_subs.append(vpath)
                        overall_pct = int(((v_idx + 1) / total_vids) * 100)
                        self.progress_bar.setValue(overall_pct)
                        self.progress_bar.setFormat(f"자막 트랙 검사 중... ({v_idx+1}/{total_vids}) ({overall_pct}%)")
                        QApplication.processEvents()
                        continue

                    def make_progress_cb(video_index, filename):
                        last_update = [0.0]
                        def _cb(pct, curr_sec, total_sec):
                            # 과도한 UI 이벤트 방지를 위해 1% 단위 또는 마지막에 갱신
                            if pct - last_update[0] >= 1.0 or pct >= 100.0:
                                last_update[0] = pct
                                vid_prog = (video_index + (pct / 100.0)) / total_vids
                                overall_pct = int(min(100.0, max(0.0, vid_prog * 100.0)))
                                self.progress_bar.setValue(overall_pct)
                                self.progress_bar.setFormat(f"[{video_index+1}/{total_vids}] 자막 추출 중: {pct:.1f}% ({overall_pct}%)")
                                QApplication.processEvents()
                        return _cb

                    # 1) 목표 언어와 동일한 자막 트랙이 있는지 확인 -> 있으면 번역 없이 바로 추출/저장
                    same_lang_stream = None
                    target_matched_lang = None
                    for s in streams:
                        s_tags = s.get("tags", {})
                        s_lang = _normalize_lang_name(s_tags.get("language", "") or s_tags.get("title", ""))
                        for orig_l, norm_l in norm_target_langs.items():
                            if s_lang and norm_l and s_lang == norm_l:
                                same_lang_stream = s
                                target_matched_lang = orig_l
                                break
                        if same_lang_stream:
                            break

                    if same_lang_stream:
                        stream_idx = same_lang_stream.get("index", 0)
                        iso_code = _get_iso_lang_code(target_matched_lang)
                        out_direct = os.path.join(self.output_dir, f"{v_basename}.{iso_code}.srt")
                        reuse_extracted = self.chk_reuse_extracted.isChecked()
                        if reuse_extracted and os.path.exists(out_direct) and os.path.getsize(out_direct) > 0:
                            saved_direct_count += 1
                            self.append_log(
                                f"\x1b[32m  ✔ [재사용] 목표 언어({target_matched_lang}) 자막 '{os.path.basename(out_direct)}' 이미 존재 → 추출 생략\x1b[0m"
                            )
                        else:
                            self.append_log(f"\x1b[36m  → 목표 언어({target_matched_lang}) 트랙 #{stream_idx} 발견! 추출 중...\x1b[0m")
                            QApplication.processEvents()
                            cb = make_progress_cb(v_idx, os.path.basename(vpath))
                            if _extract_subtitle_track(vpath, stream_idx, out_direct, progress_callback=cb):
                                saved_direct_count += 1
                                self.append_log(
                                    f"\x1b[32m  ✔ [추출 완료] 번역 불필요: '{os.path.basename(out_direct)}' 저장됨\x1b[0m"
                                )
                        overall_pct = int(((v_idx + 1) / total_vids) * 100)
                        self.progress_bar.setValue(overall_pct)
                        self.progress_bar.setFormat(f"자막 트랙 검사/추출 완료 ({v_idx+1}/{total_vids}) ({overall_pct}%)")
                        QApplication.processEvents()
                        continue

                    # 2) 번역용 자막 트랙 선택: 영어 트랙 우선 검색 (강제/forced 자막 제외 우선), 없으면 일반 첫 번째 트랙
                    best_stream = None
                    # 1순위: 'forced'가 아닌 영어 트랙
                    for s in streams:
                        s_tags = s.get("tags", {})
                        disp = s.get("disposition", {})
                        is_forced = disp.get("forced", 0) == 1 or "forced" in (s_tags.get("title", "") or "").lower()
                        s_lang = _normalize_lang_name(s_tags.get("language", "") or s_tags.get("title", ""))
                        if s_lang == "english" and not is_forced:
                            best_stream = s
                            break
                    # 2순위: 임의의 영어 트랙
                    if not best_stream:
                        for s in streams:
                            s_tags = s.get("tags", {})
                            s_lang = _normalize_lang_name(s_tags.get("language", "") or s_tags.get("title", ""))
                            if s_lang == "english":
                                best_stream = s
                                break
                    # 3순위: forced가 아닌 첫 번째 자막 트랙
                    if not best_stream:
                        for s in streams:
                            s_tags = s.get("tags", {})
                            disp = s.get("disposition", {})
                            is_forced = disp.get("forced", 0) == 1 or "forced" in (s_tags.get("title", "") or "").lower()
                            if not is_forced:
                                best_stream = s
                                break
                    # 4순위: 첫 번째 트랙
                    if not best_stream:
                        best_stream = streams[0]

                    stream_idx = best_stream.get("index", 0)
                    temp_srt_path = os.path.join(self.output_dir, f"{v_basename}_extracted.srt")
                    reuse_extracted = self.chk_reuse_extracted.isChecked()
                    if reuse_extracted and os.path.exists(temp_srt_path) and os.path.getsize(temp_srt_path) > 0:
                        self.append_log(f"\x1b[32m  ✔ [재사용] '{os.path.basename(temp_srt_path)}' 이미 존재 → 재추출 생략\x1b[0m")
                        extracted_sub_files.append((temp_srt_path, vpath))
                    else:
                        self.append_log(f"\x1b[36m  → 자막 트랙 #{stream_idx} 추출 중: '{os.path.basename(temp_srt_path)}'...\x1b[0m")
                        QApplication.processEvents()
                        cb = make_progress_cb(v_idx, os.path.basename(vpath))
                        if _extract_subtitle_track(vpath, stream_idx, temp_srt_path, progress_callback=cb):
                            extracted_sub_files.append((temp_srt_path, vpath))
                            self.append_log(
                                f"\x1b[32m  ✔ [추출 완료] '{os.path.basename(temp_srt_path)}' 추출 완료 → 번역 대상으로 등록됨\x1b[0m"
                            )
                        else:
                            videos_without_subs.append(vpath)

                    overall_pct = int(((v_idx + 1) / total_vids) * 100)
                    self.progress_bar.setValue(overall_pct)
                    self.progress_bar.setFormat(f"자막 트랙 검사/추출 완료 ({v_idx+1}/{total_vids}) ({overall_pct}%)")
                    QApplication.processEvents()

                if extracted_sub_files:
                    primary_input_source_for_jobs = [item[0] for item in extracted_sub_files]
                    valid_video_paths = [item[1] for item in extracted_sub_files]
                elif saved_direct_count > 0 and not videos_without_subs:
                    QMessageBox.information(
                        self, "완료",
                        f"선택한 영상의 내장 자막({saved_direct_count}개)이 목표 언어와 일치하여 번역 없이 바로 추출/저장되었습니다."
                    )
                    return
                else:
                    # 내장 자막이 없는 경우 -> 오디오 전사 여부 질의
                    ret = QMessageBox.question(
                        self,
                        "오디오 전사(Transcribe) 확인",
                        "선택한 비디오 파일에 추출 가능한 내장 자막 트랙이 없습니다.\n\n"
                        "비디오에서 오디오를 추출하여 [전사(Transcribe)] 방식으로 자막을 생성할까요?",
                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                        QMessageBox.StandardButton.Yes
                    )
                    if ret == QMessageBox.StandardButton.Yes:
                        self.cmb_task_mode.setCurrentIndex(1)
                        is_transcribe_mode = True
                        primary_input_source_for_jobs = videos_without_subs
                        valid_video_paths = videos_without_subs
                        source_is_media_only_for_jobs = True
                        media_type_for_jobs = 'video'
                    else:
                        return
            else:
                QMessageBox.warning(
                    self, "파일 필요", "번역할 SRT/ASS 자막 파일 또는 비디오 파일을 선택하세요."
                )
                return

        selected_model = self.cmb_model.currentText()
        if not selected_model:
            QMessageBox.warning(self, "모델 선택", "사용할 모델을 선택하세요.")
            return

        selected_languages = self.cmb_langs.checked_items()
        if not selected_languages:
            QMessageBox.warning(self, "언어 선택", "대상 언어를 하나 이상 선택하세요.")
            return

        if self.translation_worker and self.translation_worker.isRunning():
            QMessageBox.information(self, "작업 중", "이미 작업이 진행 중입니다.")
            return

        self.save_settings()
        jobs = self._create_translation_jobs(
            selected_languages, primary_input_source_for_jobs,
            source_is_media_only_for_jobs, is_transcribe_mode, media_type_for_jobs,
            video_context_paths=valid_video_paths
        )
        if not jobs:
            QMessageBox.warning(self, "작업 생성 실패", "생성된 작업이 없습니다.")
            return

        self.job_queue = queue.Queue()
        self.total_jobs = len(jobs)
        self.completed_jobs = 0
        for job in jobs:
            self.job_queue.put(job)

        self.progress_bar.setRange(0, self.total_jobs)
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat(self.tr_str("progress_format", current=0, total=self.total_jobs))

        service_tier = self.cmb_service_tier.currentText()
        if service_tier == "Default":
            service_tier = None

        request_type = self.cmb_request_type.currentText()
        if request_type == "Default":
            request_type = None

        temp_val = self.spin_temp.value()
        top_p_val = self.spin_top_p.value()
        top_k_val = self.spin_top_k.value()

        base_config = {
            'task_mode': 'transcribe' if is_transcribe_mode else 'translate',
            'gemini_api_key2': (
                self.api_key_inputs[1].text().strip()
                if len(self.api_key_inputs) > 1 else None
            ),
            'start_line': self.spin_start.value(),
            'description': self.txt_desc.toPlainText().strip() or None,
            'model_name': selected_model,
            'batch_size': self.spin_batch.value(),
            'free_quota': self.chk_free.isChecked(),
            'thoughts_log': self.chk_thoughts_log.isChecked(),
            'temperature': temp_val if temp_val > 0.0 else None,
            'top_p': top_p_val if top_p_val > 0.0 else None,
            'top_k': top_k_val if top_k_val > 0 else None,
            'streaming': self.chk_streaming.isChecked(),
            'thinking': self.chk_thinking.isChecked(),
            'thinking_budget': self.spin_thinking_budget.value(),
            'thinking_level': self.cmb_thinking_level.currentText(),
            'audio_chunk_size': self.spin_audio_chunk.value(),
            'isolate_voice': self.chk_isolate_voice.isChecked(),
            'progress_log': False,
            'video_file': (
                self.video_file_paths[0]
                if self.video_file_paths and os.path.exists(self.video_file_paths[0])
                else None
            ),
            'audio_file': (
                self.audio_file_path
                if self.audio_file_path and os.path.exists(self.audio_file_path)
                else None
            ),
            'extract_audio': self.chk_extract_audio.isChecked(),
            'token_stats': self.chk_token_stats.isChecked(),
            'preserve_context': self.chk_preserve_context.isChecked(),
            'token_report': self.chk_token_report.isChecked(),
            'context_size': self.spin_resume_context.value(),
            'resume_context_size': self.spin_resume_context.value(),
            'batch_size_error_step': self.spin_batch_error_step.value(),
            'audio_chunk_error_step': self.spin_audio_chunk_error_step.value(),
            'service_tier': service_tier,
            'use_enterprise': self.chk_use_enterprise.isChecked(),
            'cloud_project': self.cloud_project_input.text().strip() or None,
            'cloud_location': self.cloud_location_input.text().strip() or None,
            'cloud_api_key': self.cloud_api_key_input.text().strip() or None,
            'request_type': request_type,
        }

        reset_library_logger()
        self.log_output.clear_screen()
        logging.getLogger().handlers.clear()
        QApplication.processEvents()

        self.set_ui_enabled(False)
        self._stop_requested = False

        self.translation_worker = TranslationWorker(
            valid_api_keys_from_ui, self.job_queue, base_config
        )
        self.translation_worker.progress_update.connect(self.log_output.feed)
        self.translation_worker.raw_output_update.connect(self.log_output.feed)
        self.translation_worker.job_translated.connect(self._handle_job_translated)
        self.translation_worker.job_error.connect(self._handle_job_error)
        self.translation_worker.finished_signal.connect(self.translation_finished)
        self.translation_worker.start()

    def _handle_job_translated(self, output_path, language):
        with self.job_completion_lock:
            self.completed_jobs += 1
            current = self.completed_jobs
            total = self.total_jobs
        self.progress_bar.setValue(current)
        self.progress_bar.setFormat(self.tr_str("progress_format", current=current, total=total))
        self.append_log(
            f"\x1b[32m{self.tr_str('log_job_success', current=current, total=total, lang=language, file=os.path.basename(output_path))}\x1b[0m"
        )

    def _handle_job_error(self, error_message):
        with self.job_completion_lock:
            self.completed_jobs += 1
            current = self.completed_jobs
            total = self.total_jobs
        self.progress_bar.setValue(current)
        self.progress_bar.setFormat(self.tr_str("progress_format_err", current=current, total=total))
        self.append_log(
            f"\x1b[31m{self.tr_str('log_job_fail', current=current, total=total, err=error_message)}\x1b[0m"
        )

    def stop_translation(self):
        if not (self.translation_worker and self.translation_worker.isRunning()):
            return

        self.append_log(
            f"\x1b[33m{self.tr_str('log_user_stop')}\x1b[0m"
        )
        self._stop_requested = True

        if self.job_queue:
            while not self.job_queue.empty():
                try:
                    self.job_queue.get_nowait()
                    self.job_queue.task_done()
                except queue.Empty:
                    break
                except Exception:
                    pass

        if self.translation_worker:
            self.translation_worker.requestInterruption()

        self.btn_stop.setEnabled(False)

    def set_ui_enabled(self, enabled):
        widgets_to_toggle = [
            *self.api_key_inputs, *self.api_key_labels, self.btn_save_api,
            self.btn_manage_api_keys, self.btn_advanced,
            self.cmb_task_mode, self.btn_out, self.lbl_out,
            self.btn_clear_files,
            self.btn_video_file, self.lst_video_files, self.btn_clear_video_file,
            self.btn_audio_file, self.lbl_audio_file, self.btn_clear_audio_file,
            self.cmb_langs, self.btn_all_lang, self.btn_none_lang,
            self.cmb_model, self.spin_start, self.spin_batch, self.txt_desc,
            self.chk_extract_audio, self.chk_free,
            self.spin_temp, self.spin_top_p, self.spin_top_k,
            self.chk_streaming, self.chk_thinking, self.spin_thinking_budget,
            self.cmb_thinking_level, self.spin_audio_chunk, self.chk_isolate_voice,
            self.chk_append_lang, self.chk_reuse_extracted,
            self.chk_token_stats, self.chk_preserve_context,
            self.chk_token_report, self.spin_resume_context,
            self.spin_batch_error_step, self.spin_audio_chunk_error_step,
            self.cmb_service_tier, self.chk_use_enterprise,
            self.cloud_project_input, self.cloud_api_key_input,
            self.cloud_location_input, self.cmb_request_type,
        ]
        for widget in widgets_to_toggle:
            widget.setEnabled(enabled)

        if self.cmb_task_mode.currentIndex() == 0:
            self.btn_files.setEnabled(enabled)
            self.lst_files.setEnabled(enabled)
        else:
            self.btn_files.setEnabled(False)
            self.lst_files.setEnabled(False)

        self.btn_fetch.setEnabled(enabled if genai else False)
        self.btn_start.setEnabled(enabled if gst else False)
        self.btn_stop.setEnabled(not enabled)

    def translation_finished(self):
        if self.btn_start.isEnabled():
            return

        if self._stop_requested:
            remaining = self.total_jobs - self.completed_jobs
            self.append_log(
                f"\x1b[33m{self.tr_str('log_interrupted', count=remaining)}\x1b[0m"
            )
        elif self.completed_jobs < self.total_jobs:
            self.append_log(
                f"\x1b[31m{self.tr_str('log_skipped', completed=self.completed_jobs, total=self.total_jobs)}\x1b[0m"
            )
        else:
            self.append_log(f"\x1b[32m{self.tr_str('log_all_done')}\x1b[0m")

        self.progress_bar.setValue(self.completed_jobs)
        if self.completed_jobs >= self.total_jobs:
            self.progress_bar.setFormat(self.tr_str("progress_completed"))
        else:
            self.progress_bar.setFormat(
                self.tr_str("progress_interrupted", current=self.completed_jobs, total=self.total_jobs)
            )

        self.set_ui_enabled(True)

        if self.translation_worker:
            try:
                self.translation_worker.progress_update.disconnect(self.log_output.feed)
                self.translation_worker.raw_output_update.disconnect(self.log_output.feed)
                self.translation_worker.job_translated.disconnect(self._handle_job_translated)
                self.translation_worker.job_error.disconnect(self._handle_job_error)
                self.translation_worker.finished_signal.disconnect(self.translation_finished)
            except Exception:
                pass
            self.translation_worker.deleteLater()
            self.translation_worker = None

        self.job_queue = None
        self.total_jobs = 0
        self.completed_jobs = 0
        self._stop_requested = False


if __name__ == '__main__':
    app = QApplication(sys.argv)
    gui = TranslatorApp()
    gui.show()
    sys.exit(app.exec())
