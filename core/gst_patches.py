# -*- coding: utf-8 -*-
"""gemini-srt-translator 버전별 몽키패치 레지스트리.

Phase (a): core/gst_compat.py에 인라인으로 있던 몽키패치들을
버전별 패치셋으로 분리. 목표는 행위 100% 보존 — 패치 내용은 그대로 두고
적용 방식만 레지스트리를 경유하도록 정리한다.

버전별 패치셋 추가 방법:
    PATCH_REGISTRY["3.8.4"] = PATCH_SET_3_8  # 동일하면 재사용
    # 또는 새 버전용 패치셋을 별도 정의
"""

import inspect
import os
import threading

# 이 패치셋이 검증된 라이브러리 버전들
SUPPORTED_VERSIONS = ("3.8.0", "3.8.1", "3.8.2", "3.8.3")


# =====================================================================
# 취소 토큰 레지스트리 (Phase d)
#
# 몽키패치는 임포트 시점에 전역 적용되지만, 취소 토큰은 실행 시점·스레드별로
# 다르다. thread-local에 현재 스레드의 토큰을 등록하고 청크 가드에서 확인한다.
# =====================================================================
_cancel_state = threading.local()


def set_active_cancel_token(token):
    """현재 스레드의 취소 토큰 등록 (None이면 해제)."""
    _cancel_state.token = token


def _get_active_cancel_token():
    return getattr(_cancel_state, "token", None)


def _check_cancelled():
    """취소 요청 시 BackendCancelRequested 발생.

    순환 임포트를 피하기 위해 예외 클래스는 lazy import한다.
    (gst_patches는 core.backend.base보다 먼저 로드될 수 있음)
    """
    token = _get_active_cancel_token()
    if token is not None:
        try:
            cancelled = token()
        except Exception:
            cancelled = False
        if cancelled:
            from core.backend.base import BackendCancelRequested
            raise BackendCancelRequested()


def get_library_version():
    """설치된 gemini-srt-translator 버전 문자열 반환 (없으면 None).

    PyInstaller 번들 등 dist-info를 찾지 못하는 환경을 위해
    모듈의 __version__ 속성도 fallback으로 확인한다.
    """
    try:
        from importlib.metadata import version as _pkg_version
        return _pkg_version("gemini-srt-translator")
    except Exception:
        pass
    try:
        import gemini_srt_translator as _gst
        return getattr(_gst, "__version__", None)
    except Exception:
        return None


def _warn_mismatch(patch_name, detail):
    """시그니처 불일치 경고 — 패치는 그대로 적용 (행위 보존)."""
    print(f"[gst_patches] 경고: '{patch_name}' 시그니처 불일치 ({detail}). "
          f"패치는 적용되지만 새 버전에서는 확인이 필요합니다.")


def _check_signature(cls, method_name, expected_params):
    """메서드 시그니처가 예상과 다른지 확인. (True=일치, False=불일치/없음)"""
    try:
        meth = getattr(cls, method_name, None)
        if meth is None:
            return False
        sig_params = set(inspect.signature(meth).parameters.keys())
        sig_params.discard("self")
        return expected_params <= sig_params
    except (ValueError, TypeError):
        return False


# =====================================================================
# 패치 함수 정의 (기존 gst_compat.py에서 verbatim 이동)
# =====================================================================

def _patched_parse_subtitle_file(file_path: str, Subtitle=None) -> list:
    """(참고: 기존 코드에서도 등록되지 않은 dead code — 행위 보존을 위해 유지)"""
    import pysubs2
    from datetime import timedelta
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
        import pysubs2
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


def _patched_parse_response(self, response_text: str, batch: list, Subtitle=None) -> list:
    """LLM 응답을 안전하게 파싱하여 번역된 Subtitle 리스트 반환 (형변환 오류 완벽 방어)"""
    import json_repair
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


def _make_chunk_guard(original):
    """_process_batch용 빈 청크 가드 + 취소 체크 래퍼 생성.

    각 배치의 네트워크 호출 전후에 취소 토큰을 확인한다. 기존에는
    stdout write 시점에만 취소가 감지되어 네트워크 대기 중에는
    먹통처럼 보였으나, 이제 배치 경계에서 즉시 중단된다.
    """
    def _guarded(self, *args, **kwargs):
        _check_cancelled()
        try:
            result = original(self, *args, **kwargs)
        except (AttributeError, IndexError, TypeError) as _chunk_err:
            _err_msg = str(_chunk_err)
            if 'content' in _err_msg or 'candidates' in _err_msg or 'parts' in _err_msg:
                raise RuntimeError(
                    f"Gemini API 스트림 청크 오류 (빈 응답 청크): {_chunk_err}"
                ) from _chunk_err
            raise
        _check_cancelled()
        return result
    return _guarded


def _patched_get_translate_instruction(language, thinking, thinking_compatible,
                                        _orig, audio_file=None, description=None):
    """한국어 대상 시 한글 번역 강제 지침 주입."""
    prompt = _orig(language, thinking, thinking_compatible,
                   audio_file=audio_file, description=description)
    norm_l = (language or "").strip().lower()
    if norm_l in ("korean", "한국어", "ko", "kor"):
        korean_rule = (
            "\n---\n## 3.1. Language Requirement (STRICT)\n"
            "- **Target Language**: Every line of the `text` field MUST be translated into natural **Korean (한국어/한글)**.\n"
            "- **CRITICAL**: Do NOT leave the subtitle text in English or the original language. Translate the meaning faithfully into fluent Korean."
        )
        prompt += korean_rule
    return prompt


def _patched_run_command(cmd, capture_output=True, text=True):
    """ffmpeg_utils._run_command: sys.exit(1) 대신 예외 발생."""
    import subprocess
    try:
        return subprocess.run(cmd, capture_output=capture_output, text=text,
                              check=True, encoding="utf-8", errors="replace")
    except FileNotFoundError:
        raise RuntimeError(f"FFmpeg 실행 파일을 찾을 수 없습니다: '{cmd[0]}'. FFmpeg를 설치하고 PATH에 추가하세요.")
    except subprocess.CalledProcessError as e:
        err_detail = e.stderr.strip() if getattr(e, 'stderr', None) else str(e)
        raise RuntimeError(f"FFmpeg 실행 오류 ({' '.join(cmd[:2])}...): {err_detail}")


def _noop_reduce(self, *args, **kwargs):
    """배치 사이즈/오디오 청크 감소 방지 (no-op)."""
    pass


# =====================================================================
# 패치 적용 단위
# =====================================================================

def patch_save_subtitle_file(GeminiSRTTranslator, SubtitleSession):
    """_save_subtitle_file 싱크 보장 패치 (양 클래스)."""
    GeminiSRTTranslator._save_subtitle_file = _patched_save_subtitle_file
    if SubtitleSession is not None:
        SubtitleSession._save_subtitle_file = staticmethod(_patched_save_subtitle_file)


def patch_process_translated_lines(GeminiSRTTranslator):
    """_process_translated_lines 인덱스 매핑 패치."""
    if hasattr(GeminiSRTTranslator, '_process_translated_lines'):
        if not _check_signature(GeminiSRTTranslator, '_process_translated_lines',
                                {'translated_lines', 'translated_subtitle', 'batch', 'finished'}):
            _warn_mismatch('patch_process_translated_lines', '_process_translated_lines')
        GeminiSRTTranslator._process_translated_lines = _patched_process_translated_lines


def patch_parse_response(GeminiSRTTranslator, Subtitle):
    """_parse_response 형변환 방어 패치."""
    if Subtitle is None:
        raise ValueError("patch_parse_response: Subtitle 클래스가 필요합니다.")
    if hasattr(GeminiSRTTranslator, '_parse_response'):
        if not _check_signature(GeminiSRTTranslator, '_parse_response',
                                {'response_text', 'batch'}):
            _warn_mismatch('patch_parse_response', '_parse_response')
        # Subtitle 바인딩: 원본 코드는 모듈 스코프의 Subtitle을 클로저로 참조.
        # *args/**kwargs로 받아서 라이브러리 내부 호출 방식 변경에 대비.
        def _bound(self, response_text, batch, *args, **kwargs):
            return _patched_parse_response(self, response_text, batch, Subtitle=Subtitle)
        GeminiSRTTranslator._parse_response = _bound


def patch_process_batch(GeminiSRTTranslator, SubtitleSession):
    """_process_batch 빈 청크 가드 (양 클래스)."""
    if hasattr(GeminiSRTTranslator, '_process_batch'):
        _orig = GeminiSRTTranslator._process_batch
        GeminiSRTTranslator._process_batch = _make_chunk_guard(_orig)
    if SubtitleSession is not None and hasattr(SubtitleSession, '_process_batch'):
        _orig = SubtitleSession._process_batch
        SubtitleSession._process_batch = _make_chunk_guard(_orig)


def patch_translate_instruction():
    """get_translate_instruction 한국어 강제 지침 주입."""
    import gemini_srt_translator.helpers as gst_helpers
    if hasattr(gst_helpers, 'get_translate_instruction'):
        _orig = gst_helpers.get_translate_instruction

        def _wrapper(language, thinking, thinking_compatible, audio_file=None, description=None):
            return _patched_get_translate_instruction(
                language, thinking, thinking_compatible, _orig,
                audio_file=audio_file, description=description)

        gst_helpers.get_translate_instruction = _wrapper

        # 이미 임포트된 모듈 참조도 업데이트
        try:
            import gemini_srt_translator.session as gst_session
            gst_session.get_translate_instruction = _wrapper
        except Exception:
            pass
        try:
            import gemini_srt_translator.main as gst_main
            gst_main.get_translate_instruction = _wrapper
        except Exception:
            pass


def patch_ffmpeg_run_command():
    """ffmpeg_utils._run_command sys.exit 방지."""
    try:
        import gemini_srt_translator.ffmpeg_utils as ff_utils
        ff_utils._run_command = _patched_run_command
    except Exception:
        pass


def patch_noop_reduce(GeminiSRTTranslator):
    """_reduce_batch_size/_reduce_transcribe_chunk_size no-op화."""
    GeminiSRTTranslator._reduce_batch_size = _noop_reduce
    if hasattr(GeminiSRTTranslator, '_reduce_transcribe_chunk_size'):
        GeminiSRTTranslator._reduce_transcribe_chunk_size = _noop_reduce


# =====================================================================
# 버전별 패치셋 레지스트리
# =====================================================================

# v3.8.x 검증 패치셋 (현재 3.8.0~3.8.3 동일)
PATCH_SET_3_8 = (
    "patch_save_subtitle_file",
    "patch_process_translated_lines",
    "patch_parse_response",
    "patch_process_batch",
    "patch_translate_instruction",
    "patch_ffmpeg_run_command",
    "patch_noop_reduce",
)

PATCH_REGISTRY = {
    "3.8.0": PATCH_SET_3_8,
    "3.8.1": PATCH_SET_3_8,
    "3.8.2": PATCH_SET_3_8,
    "3.8.3": PATCH_SET_3_8,
}

_PATCH_FUNCS = {
    "patch_save_subtitle_file": patch_save_subtitle_file,
    "patch_process_translated_lines": patch_process_translated_lines,
    "patch_parse_response": patch_parse_response,
    "patch_process_batch": patch_process_batch,
    "patch_translate_instruction": patch_translate_instruction,
    "patch_ffmpeg_run_command": patch_ffmpeg_run_command,
    "patch_noop_reduce": patch_noop_reduce,
}


def resolve_patch_set(version):
    """버전에 맞는 패치셋 이름 목록 반환.

    미지원/미확인 버전은 가장 마지막 검증 패치셋을 사용하고 경고를 출력
    (기존 동작 보존: 버전과 무관하게 패치가 적용됐었음).
    """
    if version in PATCH_REGISTRY:
        return PATCH_REGISTRY[version]
    print(f"[gst_patches] 경고: gemini-srt-translator {version}은(는) 검증되지 않은 버전입니다. "
          f"최신 검증 패치셋({SUPPORTED_VERSIONS[-1]})을 적용합니다.")
    return PATCH_REGISTRY[SUPPORTED_VERSIONS[-1]]


def apply_patches(GeminiSRTTranslator, Subtitle, SubtitleSession, version=None):
    """패치셋 적용. version 생략 시 설치된 버전 자동 감지."""
    ver = version or get_library_version()
    for name in resolve_patch_set(ver):
        func = _PATCH_FUNCS[name]
        try:
            if name == "patch_save_subtitle_file":
                func(GeminiSRTTranslator, SubtitleSession)
            elif name in ("patch_process_translated_lines", "patch_noop_reduce"):
                func(GeminiSRTTranslator)
            elif name == "patch_parse_response":
                func(GeminiSRTTranslator, Subtitle)
            elif name == "patch_process_batch":
                func(GeminiSRTTranslator, SubtitleSession)
            else:
                func()
        except Exception as e:
            # 기존 동작 보존: 개별 패치 실패는 전체를 막지 않음
            print(f"[gst_patches] 경고: '{name}' 적용 중 오류 (무시됨): {e}")
    return ver
