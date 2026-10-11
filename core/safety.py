# -*- coding: utf-8 -*-
"""프로세스 수준 안전장치.

- 워커 스레드에서 발생하는 exit()/signal 호출이 GUI 전체를 종료하지 않도록 가드
- FFmpeg 번들 경로 자동 등록

모듈 임포트 시점에 패치가 적용되므로, 애플리케이션 진입점에서 가장 먼저
임포트되어야 한다.
"""

import builtins
import os
import signal
import sys
import threading
import sys
import builtins
# [패치] PyInstaller windowed 모드에서 exit()가 없는 문제 방지
try:
    exit
except NameError:
    builtins.exit = sys.exit

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
        # NOTE: 본 모듈은 core/ 패키지 안에 있으므로 프로젝트 루트로 한 단계 올라간다.
        _here = os.path.dirname(os.path.abspath(__file__)) if '__file__' in globals() else os.getcwd()
        app_dir = os.path.dirname(_here)
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
