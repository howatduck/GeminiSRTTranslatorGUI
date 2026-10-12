# -*- coding: utf-8 -*-
"""gemini-srt-translator 라이브러리 호환 레이어.

라이브러리 임포트(실패 시 그레이스풀 디그레이드)와 GUI 안정성을 위한
몽키패치를 모듈 임포트 시점에 적용한다.
"""

import os

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
