# -*- coding: utf-8 -*-
"""백그라운드 작업 스레드: 번역 워커, 모델 목록 조회."""

import io
import os
import queue
import re
import sys
import threading
import time
import traceback

from PyQt6.QtCore import Qt, QSettings, QThread, pyqtSignal, QObject, QTimer
from PyQt6.QtGui import QFont, QTextCursor, QTextCharFormat, QColor, QStandardItemModel, QStandardItem
from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QFileDialog, QComboBox, QSpinBox, QCheckBox, QTextEdit,
    QMessageBox, QGroupBox, QFormLayout, QListWidget, QListWidgetItem,
    QSizePolicy, QFrame, QDoubleSpinBox, QProgressBar,
    QToolButton, QScrollArea, QLayout, QDialog,
)

from core.config import DEFAULT_BATCH_SIZE, DEFAULT_MODEL, NUM_API_KEYS
from core.errors import classify_worker_error
from core.pricing import token_report_path_for
from core.gst_compat import (
    GENAI_IMPORT_ERROR, GST_IMPORT_ERROR, genai,
)
from core.backend import GstAdapter
from core.languages import TARGET_LANGUAGES, _get_iso_lang_code, _normalize_lang_name
from core.media import (
    _extract_subtitle_track, _get_media_duration, _get_video_subtitle_streams,
)


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

    def run(self):
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

                            # Phase (c): 어댑터를 통한 백엔드 실행
                            # (파라미터 필터링·구버전 fallback·로거 초기화는 어댑터 내부에서 처리)
                            mode = "transcribe" if is_transcribe_mode else "translate"
                            self._backend.run(translator_args, mode=mode)

                            job_successful = True

                        except ForceAbortException:
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
