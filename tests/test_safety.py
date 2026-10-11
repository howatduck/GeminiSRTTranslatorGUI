# -*- coding: utf-8 -*-
"""core.safety 테스트: 스레드별 exit/signal 가드 동작."""

import builtins
import signal
import sys
import threading

import pytest

from core import safety
from core.safety import WorkerLibraryExit, _safe_app_exit


def test_exit_patched():
    # 모듈 임포트 시점에 전역 exit이 패치되어야 한다
    assert builtins.exit is _safe_app_exit
    assert sys.exit is _safe_app_exit


def test_worker_thread_exit_raises():
    # 워커 스레드에서 exit() 호출 시 프로세스 종료 대신 예외 발생
    codes = []

    def target():
        try:
            _safe_app_exit(3)
        except WorkerLibraryExit as e:
            codes.append(e.code)

    t = threading.Thread(target=target)
    t.start()
    t.join(timeout=5)
    assert codes == [3]


def test_builtins_exit_raises_in_worker_thread():
    codes = []

    def target():
        try:
            builtins.exit(7)
        except WorkerLibraryExit as e:
            codes.append(e.code)

    t = threading.Thread(target=target)
    t.start()
    t.join(timeout=5)
    assert codes == [7]


def test_main_thread_exit_raises_systemexit():
    # 메인 스레드에서는 정상 종료(SystemExit) 동작 유지
    with pytest.raises(SystemExit):
        _safe_app_exit(0)


def test_signal_patched():
    assert signal.signal is safety._safe_signal


def test_signal_in_worker_thread_is_noop():
    results = []

    def target():
        results.append(signal.signal(signal.SIGINT, signal.SIG_DFL))

    t = threading.Thread(target=target)
    t.start()
    t.join(timeout=5)
    assert results == [None]


def test_worker_library_exit_message():
    e = WorkerLibraryExit(130)
    assert e.code == 130
    assert "130" in str(e)
