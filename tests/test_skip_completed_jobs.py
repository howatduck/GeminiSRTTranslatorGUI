# -*- coding: utf-8 -*-
"""완료된 번역 작업 스킵 판정 테스트 (이슈 #1).

완료 판정 규칙: 출력 파일이 있고 비어 있지 않으며, 입력 쪽 .progress
파일이 없을 때만 완료로 본다. 라이브러리는 부분 결과를 최종 출력
경로에 원자적으로 쓰므로 출력 존재만으로는 완료를 판정할 수 없다.
"""

import os
import queue

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PyQt6")

from core.subtitle_io import is_translation_complete, progress_file_for


def _write(path, text="x"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return str(path)


def test_no_output_is_not_complete(tmp_path):
    src = _write(tmp_path / "in.srt")
    out = str(tmp_path / "in.ko.srt")
    assert is_translation_complete(src, out) is False


def test_output_with_progress_is_partial(tmp_path):
    src = _write(tmp_path / "in.srt")
    out = _write(tmp_path / "in.ko.srt", "partial result")
    _write(tmp_path / "in.progress", '{"line": 42}')
    assert is_translation_complete(src, out) is False


def test_output_without_progress_is_complete(tmp_path):
    src = _write(tmp_path / "in.srt")
    out = _write(tmp_path / "in.ko.srt", "complete result")
    assert is_translation_complete(src, out) is True


def test_empty_output_is_not_complete(tmp_path):
    src = _write(tmp_path / "in.srt")
    out = _write(tmp_path / "in.ko.srt", "")
    assert is_translation_complete(src, out) is False


def test_progress_follows_input_folder_not_output(tmp_path):
    src = _write(tmp_path / "inputs" / "in.srt")
    out = _write(tmp_path / "outputs" / "in.ko.srt", "complete result")
    _write(tmp_path / "inputs" / "in.progress", '{"line": 3}')
    assert is_translation_complete(src, out) is False


def test_in_place_input_is_never_complete(tmp_path):
    src = _write(tmp_path / "in.srt", "original")
    assert is_translation_complete(src, src) is False


def test_progress_file_for_strips_extracted_suffix(tmp_path):
    src = str(tmp_path / "movie_extracted.srt")
    assert progress_file_for(src) == str(tmp_path / "movie.progress")


def test_progress_file_for_prefers_video_file(tmp_path):
    src = str(tmp_path / "out" / "movie_extracted.srt")
    video = str(tmp_path / "videos" / "movie.mp4")
    assert progress_file_for(src, video_file=video) == str(
        tmp_path / "videos" / "movie.progress"
    )


def test_video_context_completion_uses_video_progress(tmp_path):
    src = _write(tmp_path / "out" / "movie_extracted.srt")
    video = _write(tmp_path / "videos" / "movie.mp4")
    out = _write(tmp_path / "out" / "movie.ko.srt", "complete result")
    assert is_translation_complete(src, out, video_file=video) is True
    _write(tmp_path / "videos" / "movie.progress", '{"line": 7}')
    assert is_translation_complete(src, out, video_file=video) is False


@pytest.fixture(scope="module")
def qapp():
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app


def test_existing_output_survives_backend_failure(qapp, tmp_path):
    """워커가 작업을 실패해도 기존 출력 파일을 지우지 않아야 한다 (이슈 #1)."""
    from app.workers import TranslationWorker

    src = _write(tmp_path / "in.srt", "1\n00:00:01,000 --> 00:00:02,000\nhello\n")
    out = _write(tmp_path / "in.ko.srt", "PREVIOUS COMPLETE RESULT")

    job_queue = queue.Queue()
    job_queue.put((src, "Korean", out, False, None, None))
    worker = TranslationWorker(["dummy-key"], job_queue, {"task_mode": "translate"})

    class _FailBackend:
        def run(self, params, mode=None, cancel_token=None):
            raise RuntimeError("backend exploded")

    worker._backend = _FailBackend()
    worker._base_backoff_seconds = 0.01
    worker._max_backoff_seconds = 0.02

    errors = []
    worker.job_error.connect(errors.append)
    worker.run()

    assert errors, "백엔드 실패가 job_error로 보고되어야 한다"
    with open(out, encoding="utf-8") as f:
        assert f.read() == "PREVIOUS COMPLETE RESULT"
