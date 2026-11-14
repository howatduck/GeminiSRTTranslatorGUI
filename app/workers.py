# -*- coding: utf-8 -*-
"""백그라운드 작업 스레드: 번역 워커, 모델 목록 조회."""

import io
import os
import queue
import sys
import threading
import time
import traceback

from PyQt6.QtCore import QThread, pyqtSignal, QObject
from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QFileDialog, QComboBox, QSpinBox, QCheckBox, QTextEdit,
    QMessageBox, QGroupBox, QFormLayout, QListWidget, QListWidgetItem,
    QSizePolicy, QFrame, QDoubleSpinBox, QProgressBar,
    QToolButton, QScrollArea, QLayout, QDialog,
)

from app.i18n import I18N
from core.config import DEFAULT_BATCH_SIZE, DEFAULT_MODEL, is_text_model
from core.errors import (
    classify_worker_error, failure_kind, failure_kind_label, MODEL_SWITCH_KINDS)
from core.fallback import build_attempt_plan
from core.pricing import token_report_path_for
from core.gst_compat import (
    GENAI_IMPORT_ERROR, GST_IMPORT_ERROR, genai,
)
from core.backend import BackendCancelRequested, GstAdapter
from core.media import (
    _extract_subtitle_track, _get_media_duration, _get_video_subtitle_streams,
)


def _tr(ui_lang, tkey, **kwargs):
    # 주의: 템플릿 플레이스홀더 {lang}·{key}와 인자 이름이 겹치면 안 된다
    template = I18N.get(ui_lang, I18N["ko"]).get(
        tkey, I18N["ko"].get(tkey, tkey))
    if kwargs:
        try:
            return template.format(**kwargs)
        except Exception:
            return template
    return template


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
# [라이브러리 업데이트 확인 스레드]
# =====================================================================
class UpdateCheckThread(QThread):
    check_done = pyqtSignal(object, object)  # (installed_version, latest_version)
    error_occurred = pyqtSignal(str)

    def __init__(self, lang="ko"):
        super().__init__()
        self.lang = lang

    def run(self):
        try:
            from core.update_check import (
                fetch_latest_version, get_installed_version,
            )
        except Exception as e:
            self.error_occurred.emit(
                _tr(self.lang, "wrk_update_module_failed", error=e))
            return
        try:
            installed = get_installed_version()
            latest = fetch_latest_version()
            self.check_done.emit(installed, latest)
        except Exception as e:
            self.error_occurred.emit(
                _tr(self.lang, "wrk_update_check_failed", error=e))


# =====================================================================
# [모델 가져오기 스레드]
# =====================================================================
class ModelFetcherThread(QThread):
    models_fetched = pyqtSignal(list)
    error_occurred = pyqtSignal(str)

    def __init__(self, api_key, include_all=False, lang="ko"):
        super().__init__()
        self.lang = lang
        self.api_key = api_key
        # True면 텍스트 번역 불가 모델까지 포함한다 (고급 설정 옵션)
        self.include_all = include_all

    def run(self):
        if not genai:
            self.error_occurred.emit(_tr(self.lang, "wrk_no_genai"))
            return
        if not self.api_key:
            self.error_occurred.emit(_tr(self.lang, "wrk_need_primary_key"))
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

            # 임베딩·이미지·TTS 등 텍스트 번역에 못 쓰는 모델은 제외
            # (고급 설정에서 '모든 모델 표시'를 켠 경우에만 전부 포함)
            if self.include_all:
                available_models = sorted(set(available_models))
            else:
                available_models = sorted(
                    {m for m in available_models if is_text_model(m)})
            if available_models:
                self.models_fetched.emit(available_models)
            else:
                self.error_occurred.emit(_tr(self.lang, "wrk_no_models"))
        except Exception as e:
            self.error_occurred.emit(_tr(self.lang, "wrk_fetch_failed", error=e))


# =====================================================================
# [번역/전사 워커 스레드]
# =====================================================================
class TranslationWorker(QThread):
    progress_update = pyqtSignal(str)
    raw_output_update = pyqtSignal(str)
    job_translated = pyqtSignal(str, str)
    job_error = pyqtSignal(str)
    finished_signal = pyqtSignal()

    def __init__(self, valid_api_keys, job_queue, base_config, lang="ko"):
        super().__init__()
        self.lang = lang
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

        # 번역 백엔드 어댑터 (라이브러리 직접 의존 제거, Phase c)
        self._backend = GstAdapter()

    def run(self):
        task_mode = self.base_config.get('task_mode', 'translate')
        task_name = _tr(
            self.lang,
            "wrk_job_transcribe" if task_mode == 'transcribe'
            else "wrk_job_translate")

        key_count = len(self.api_keys) if self.api_keys else 0
        self.progress_update.emit(
            f"\x1b[36m{_tr(self.lang, 'wrk_start', task=task_name, count=key_count)}\x1b[0m\n"
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
                job_taken = False
                try:
                    job = self.job_queue.get_nowait()
                    job_taken = True
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

                    # 출력 파일을 미리 지우지 않는다: 완료된 출력은 작업 생성
                    # 단계에서 이미 제외되고, 라이브러리는 배치 결과를 최종
                    # 경로에 원자적으로 쓰므로 사전 삭제가 오히려 완료본을
                    # 날린다. 입력==출력(제자리)인 경우도 라이브러리가 입력을
                    # 전부 읽은 뒤 쓰므로 안전하다.

                    # 시도 계획: (모델, 배치) 프로필 × API 키 회전.
                    # 모델 폴백 체인·배치 래더는 base_config로 전달된다.
                    model_chain = self.base_config.get('model_chain') or [
                        self.base_config.get('model_name', DEFAULT_MODEL)]
                    plan = build_attempt_plan(
                        model_chain,
                        self.base_config.get('batch_size', DEFAULT_BATCH_SIZE),
                        self.base_config.get('batch_step_down', 0),
                        self.base_config.get('batch_floor', 0),
                    )
                    max_key_attempts = max(1, len(self.api_keys))
                    total_attempts = len(plan) * max_key_attempts
                    job_successful = False
                    last_error_msg = ""

                    attempt = 0
                    plan_idx = 0
                    while attempt < total_attempts and plan_idx < len(plan):
                        if self.isInterruptionRequested():
                            break

                        profile_model, profile_batch = plan[plan_idx]
                        current_primary_api_key = (
                            self.api_keys[self.current_key_index] if self.api_keys else None
                        )
                        key_display_index = self.current_key_index + 1 if self.api_keys else 0
                        msg_key = _tr(
                            self.lang, "wrk_key_label",
                            index=key_display_index, total=key_count)

                        if attempt > 0:
                            self.progress_update.emit(
                                f"\x1b[33m{_tr(self.lang, 'wrk_job_retry', attempt=attempt + 1, total=total_attempts, key=msg_key, lang=target_language, name=base_name, model=profile_model, batch=profile_batch)}\x1b[0m\n"
                            )
                        else:
                            self.progress_update.emit(
                                f"\x1b[33m{_tr(self.lang, 'wrk_job_start', key=msg_key, lang=target_language, name=base_name)}\x1b[0m\n"
                            )

                        # 라이브러리 로거 초기화는 GstAdapter.run() 내부에서 수행
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
                                # start_line이 None이면 어댑터가 걸러내 라이브러리
                                # 기본값(저장된 .progress 위치)이 적용된다.
                                'start_line': self.base_config.get('start_line'),
                                'description': self.base_config.get('description', '') or None,
                                'model_name': profile_model,
                                'batch_size': profile_batch,
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
                                'resume': self.base_config.get('resume', True),
                                # token_report: 체크박스(bool) → 작업별 리포트 경로로 변환.
                                # 라이브러리는 경로(str)를 기대하므로 bool을 그대로 넘기면
                                # os.path.dirname(True)에서 TypeError가 발생한다.
                                'token_report': (
                                    token_report_path_for(output_file_path)
                                    if self.base_config.get('token_report', False)
                                    else None
                                ),
                                'context_size': self.base_config.get('context_size', self.base_config.get('resume_context_size', 0)),
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

                            # Phase (c+d): 어댑터를 통한 백엔드 실행
                            # (파라미터 필터링·구버전 fallback·로거 초기화는 어댑터 내부에서 처리)
                            # cancel_token으로 청크 경계에서 즉시 중단 가능
                            mode = "transcribe" if is_transcribe_mode else "translate"
                            # 서명 {model}용: 이 시도를 실행하는 모델을 저장
                            # 패치에 알린다 (폴백 성공 시 그 모델이 기록됨)
                            try:
                                from core.subtitle_io import set_signature_model
                                set_signature_model(profile_model)
                            except Exception:
                                pass
                            self._backend.run(
                                translator_args, mode=mode,
                                cancel_token=self.isInterruptionRequested,
                            )

                            job_successful = True

                        except (ForceAbortException, BackendCancelRequested):
                            break

                        except Exception as e:
                            if self.isInterruptionRequested():
                                break

                            err_msg = classify_worker_error(
                                e, msg_key=msg_key, base_name=base_name,
                                lang=self.lang
                            )
                            err_tb = traceback.format_exc()

                            last_error_msg = err_msg
                            err_logs = captured_stderr_io_for_lib.getvalue()
                            if err_logs.strip():
                                self.progress_update.emit(f"\x1b[33m{_tr(self.lang, 'wrk_library_log', logs=err_logs)}\x1b[0m\n")
                            self.progress_update.emit(f"\x1b[31m{_tr(self.lang, 'wrk_error_line', msg=err_msg)}\x1b[0m\n")
                            # Traceback 상세 로그 (디버그용)
                            self.progress_update.emit(f"\x1b[33m{_tr(self.lang, 'wrk_traceback', tb=err_tb)}\x1b[0m\n")

                        finally:
                            sys.stderr = original_thread_stderr
                            captured_stderr_io_for_lib.close()


                        if job_successful:
                            break
                        else:
                            if self.api_keys:
                                self.current_key_index = (self.current_key_index + 1) % len(self.api_keys)

                        attempt += 1
                        # 다음 프로필 결정: 과부하·할당량·안전차단은 배치
                        # 축소가 아니라 모델 전환이 답이라 같은 모델의 남은
                        # 프로필을 건너뛰고, 그 외에는 키를 한 바퀴 다 쓴
                        # 시점에 다음 프로필(다음 모델/작은 배치)로 넘어간다.
                        kind = failure_kind(last_error_msg)
                        if kind in MODEL_SWITCH_KINDS:
                            nxt = plan_idx + 1
                            while nxt < len(plan) and plan[nxt][0] == profile_model:
                                nxt += 1
                            if nxt < len(plan):
                                self.progress_update.emit(
                                    f"\x1b[33m{_tr(self.lang, 'wrk_fallback_switch', model=profile_model, kind=failure_kind_label(kind, self.lang), next=plan[nxt][0])}\x1b[0m\n"
                                )
                            plan_idx = nxt
                        elif attempt % max_key_attempts == 0:
                            plan_idx += 1
                            if plan_idx < len(plan):
                                self.progress_update.emit(
                                    f"\x1b[33m{_tr(self.lang, 'wrk_fallback_change', model=plan[plan_idx][0], batch=plan[plan_idx][1])}\x1b[0m\n"
                                )

                    if self.isInterruptionRequested():
                        break

                    if job_successful:
                        self.job_translated.emit(output_file_path, target_language)
                        self._consecutive_failures = 0
                        if self.api_keys:
                            self.current_key_index = (self.current_key_index + 1) % len(self.api_keys)
                    else:
                        self.job_error.emit(
                            last_error_msg or _tr(self.lang, "wrk_all_keys_failed"))
                        self._consecutive_failures += 1

                        if self._consecutive_failures >= self._max_consecutive_failures:
                            self.progress_update.emit(
                                f"\x1b[31m{_tr(self.lang, 'wrk_consecutive_stop', count=self._consecutive_failures)}\x1b[0m\n"
                            )
                            break

                        backoff = min(
                            self._base_backoff_seconds * (2 ** (self._consecutive_failures - 1)),
                            self._max_backoff_seconds,
                        )
                        self.progress_update.emit(
                            f"\x1b[33m{_tr(self.lang, 'wrk_wait_retry', count=self._consecutive_failures, seconds=f'{backoff:.0f}')}\x1b[0m\n"
                        )
                        try:
                            time.sleep(backoff)
                        except ForceAbortException:
                            break

                except queue.Empty:
                    if not self.isInterruptionRequested():
                        self.progress_update.emit(
                            f"\x1b[32m{_tr(self.lang, 'wrk_queue_empty')}\x1b[0m\n"
                        )
                    break
                except Exception as e:
                    if not self.isInterruptionRequested():
                        self.progress_update.emit(
                            f"\x1b[31m{_tr(self.lang, 'wrk_loop_error', error=e)}\x1b[0m\n"
                        )
                        self.job_error.emit(_tr(self.lang, "wrk_loop_error_msg", error=e))
                    break
                finally:
                    # 작업 1건당 task_done() 정확히 1회: get_nowait() 성공
                    # 이후의 모든 탈출 경로(정상·실패·중단·예외)를 여기서
                    # 한 번에 확인한다. 분산 호출은 누락·이중 호출의 원인.
                    if job_taken:
                        self.job_queue.task_done()
        finally:
            sys.stdout = original_stdout
            sys.stderr = original_stderr
            time.sleep = original_sleep

            msg = f"\x1b[36m{_tr(self.lang, 'wrk_end', task=task_name)}\x1b[0m\n"
            if self.isInterruptionRequested():
                msg += f"\x1b[33m{_tr(self.lang, 'wrk_stopped_by_user')}\x1b[0m\n"
            self.progress_update.emit(msg)
            self.finished_signal.emit()
