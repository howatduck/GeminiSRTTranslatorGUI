# -*- coding: utf-8 -*-
"""Tkinter판 백그라운드 작업 스레드 — app/workers.py의 threading 포팅.

로직은 PyQt판과 동일하고, QThread/pyqtSignal만 표준 threading과
아래 Signal shim으로 교체했다. 시그널 핸들러는 창이 bind_dispatch로
등록한 디스패처(UI 스레드 스케줄러)를 통해 실행된다.
"""

import io
import os
import queue
import sys
import threading
import time
import traceback

from core.config import DEFAULT_BATCH_SIZE, DEFAULT_MODEL, is_text_model
from core.errors import (
    classify_worker_error, failure_kind, failure_kind_label, MODEL_SWITCH_KINDS)
from core.fallback import build_attempt_plan
from core.pricing import token_report_path_for
from core.gst_compat import genai
from core.backend import BackendCancelRequested, GstAdapter


class Signal:
    """pyqtSignal의 최소 대체 (connect/disconnect/emit)."""

    def __init__(self):
        self._handlers = []
        self.dispatch = None

    def connect(self, fn):
        if fn not in self._handlers:
            self._handlers.append(fn)

    def disconnect(self, fn=None):
        if fn is None:
            self._handlers.clear()
        elif fn in self._handlers:
            self._handlers.remove(fn)

    def emit(self, *args):
        for fn in list(self._handlers):
            if self.dispatch is not None:
                self.dispatch(lambda f=fn, a=args: f(*a))
            else:
                fn(*args)


class _WorkerBase(threading.Thread):
    """QThread 인터페이스(isRunning/requestInterruption/wait) 대체."""

    def __init__(self):
        super().__init__(daemon=True)
        self._stop_event = threading.Event()

    def isInterruptionRequested(self):
        return self._stop_event.is_set()

    def requestInterruption(self):
        self._stop_event.set()

    def isRunning(self):
        return self.is_alive()

    def wait(self, timeout_ms=None):
        self.join(None if timeout_ms is None else timeout_ms / 1000.0)
        return not self.is_alive()

    def bind_dispatch(self, dispatch):
        for value in vars(self).values():
            if isinstance(value, Signal):
                value.dispatch = dispatch


# =====================================================================
# [스트림 캡처] 예외를 던져 강제 탈출 + 터미널 위젯으로 텍스트 전달
# =====================================================================
class ForceAbortException(BaseException):
    """사용자 중단을 위한 특수 예외 (Exception이 아닌 BaseException 상속)"""
    pass


class WorkerStream:
    def __init__(self, worker_thread):
        self.worker_thread = worker_thread

    def write(self, text):
        if self.worker_thread.isInterruptionRequested():
            raise ForceAbortException("사용자 중단 요청")
        if text is not None:
            self.worker_thread.raw_output_update.emit(str(text))

    def flush(self):
        pass

    def isatty(self):
        return False


# =====================================================================
# [라이브러리 업데이트 확인 스레드]
# =====================================================================
class UpdateCheckThread(_WorkerBase):
    def __init__(self):
        super().__init__()
        self.check_done = Signal()       # (installed_version, latest_version)
        self.error_occurred = Signal()   # (message)
        self.finished = Signal()

    def run(self):
        try:
            try:
                from core.update_check import (
                    fetch_latest_version, get_installed_version,
                )
            except Exception as e:
                self.error_occurred.emit(f"업데이트 확인 모듈 로드 실패: {e}")
                return
            try:
                installed = get_installed_version()
                latest = fetch_latest_version()
                self.check_done.emit(installed, latest)
            except Exception as e:
                self.error_occurred.emit(f"업데이트 확인 실패: {e}")
        finally:
            self.finished.emit()


# =====================================================================
# [모델 가져오기 스레드]
# =====================================================================
class ModelFetcherThread(_WorkerBase):
    def __init__(self, api_key, include_all=False):
        super().__init__()
        self.api_key = api_key
        # True면 텍스트 번역 불가 모델까지 포함한다 (고급 설정 옵션)
        self.include_all = include_all
        self.models_fetched = Signal()
        self.error_occurred = Signal()
        self.finished = Signal()

    def run(self):
        try:
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
                    self.error_occurred.emit("사용 가능한 생성 모델을 찾을 수 없습니다.")
            except Exception as e:
                self.error_occurred.emit(f"모델 가져오기 실패: {e}")
        finally:
            self.finished.emit()


# =====================================================================
# [번역/전사 워커 스레드] — 본문 로직은 PyQt판과 동일
# =====================================================================
class TranslationWorker(_WorkerBase):
    def __init__(self, valid_api_keys, job_queue, base_config):
        super().__init__()
        self.api_keys = list(valid_api_keys)
        self.job_queue = job_queue
        self.base_config = base_config

        self.progress_update = Signal()
        self.raw_output_update = Signal()
        self.job_translated = Signal()
        self.job_error = Signal()
        self.finished_signal = Signal()
        self.finished = Signal()

        self.current_key_index = 0
        self.gui_stream_out = WorkerStream(self)

        self._consecutive_failures = 0
        self._max_consecutive_failures = 5
        self._base_backoff_seconds = 3.0
        self._max_backoff_seconds = 60.0

        # 번역 백엔드 어댑터 (라이브러리 직접 의존 제거, Phase c)
        self._backend = GstAdapter()

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
                        msg_key = f"키 {key_display_index}/{key_count}"

                        if attempt > 0:
                            self.progress_update.emit(
                                f"\x1b[33m\n[작업 재시도 ({attempt+1}/{total_attempts}) ({msg_key})] [{target_language}] {base_name} (모델 {profile_model} · 배치 {profile_batch})\x1b[0m\n"
                            )
                        else:
                            self.progress_update.emit(
                                f"\x1b[33m\n[작업 시작 ({msg_key})] [{target_language}] {base_name}\x1b[0m\n"
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
                                e, msg_key=msg_key, base_name=base_name
                            )
                            err_tb = traceback.format_exc()

                            last_error_msg = err_msg
                            err_logs = captured_stderr_io_for_lib.getvalue()
                            if err_logs.strip():
                                self.progress_update.emit(f"\x1b[33m[라이브러리 로그]\n{err_logs}\x1b[0m\n")
                            self.progress_update.emit(f"\n\x1b[31m[오류] {err_msg}\x1b[0m\n")
                            self.progress_update.emit(f"\x1b[33m[디버그 Traceback]\n{err_tb}\x1b[0m\n")

                        finally:
                            sys.stderr = original_thread_stderr
                            captured_stderr_io_for_lib.close()

                        if job_successful:
                            break
                        else:
                            if self.api_keys:
                                self.current_key_index = (self.current_key_index + 1) % len(self.api_keys)

                        attempt += 1
                        # 다음 프로필 결정: 과부하·할당량·안전차단은 모델
                        # 전환이 답이라 같은 모델의 남은 프로필을 건너뛴다.
                        kind = failure_kind(last_error_msg)
                        if kind in MODEL_SWITCH_KINDS:
                            nxt = plan_idx + 1
                            while nxt < len(plan) and plan[nxt][0] == profile_model:
                                nxt += 1
                            if nxt < len(plan):
                                self.progress_update.emit(
                                    f"\x1b[33m[폴백] {profile_model} 실패({failure_kind_label(kind)}) → {plan[nxt][0]} 모델로 전환합니다.\x1b[0m\n"
                                )
                            plan_idx = nxt
                        elif attempt % max_key_attempts == 0:
                            plan_idx += 1
                            if plan_idx < len(plan):
                                self.progress_update.emit(
                                    f"\x1b[33m[폴백] 재시도 조건 변경 → 모델 {plan[plan_idx][0]} · 배치 {plan[plan_idx][1]}\x1b[0m\n"
                                )

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
                            break

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
                    # 작업 1건당 task_done() 정확히 1회 (PyQt판과 동일 규칙)
                    if job_taken:
                        self.job_queue.task_done()
        finally:
            sys.stdout = original_stdout
            sys.stderr = original_stderr
            time.sleep = original_sleep

            msg = f"\n\x1b[36m==== {task_name} 워커 스레드 종료 ====\x1b[0m\n"
            if self.isInterruptionRequested():
                msg += "\x1b[33m(사용자 수동 중단 요청에 의해 멈춤)\x1b[0m\n"
            self.progress_update.emit(msg)
            self.finished_signal.emit()
            self.finished.emit()
