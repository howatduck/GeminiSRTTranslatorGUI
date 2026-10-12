# -*- coding: utf-8 -*-
"""
Gemini SRT Translator GUI (v3.8.3 호환, Pyte VT100 터미널)
v3.8.0 ~ v3.8.3 최신 변경사항 반영 (SubtitleSession 엔진, 적응형 배치/오디오청크 감축, context_size 통일 등)

시작 순서:
  1. core.safety (가벼움) → 2. 스플래시 표시 → 3. 무거운 import (진행 메시지 표시)
  → 4. 메인 윈도우 생성 → 5. 스플래시 종료
"""

import os
import sys

# 프로세스 안전 패치(exit/signal 가드) 및 FFmpeg 경로 등록: 가장 먼저 적용
import core.safety  # noqa: F401


# --- 스플래시 화면: 무거운 import 전에 최대한 빨리 표시 ---
def _splash_image_path():
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, "assets", "splash.png")


try:
    from PyQt6.QtWidgets import QApplication, QSplashScreen
    from PyQt6.QtGui import QPixmap
    from PyQt6.QtCore import Qt
except ImportError:
    print("치명적 오류: 'PyQt6' 라이브러리를 찾을 수 없습니다. 'pip install PyQt6' 명령어로 설치하세요.")
    sys.exit(1)

_app = QApplication(sys.argv)

_splash = None
_splash_path = _splash_image_path()
if os.path.exists(_splash_path):
    _splash = QSplashScreen(QPixmap(_splash_path))
    # 작업표시줄에 아이콘이 안 잡히도록 SplashScreen 플래그 유지, 항상 위
    _splash.setWindowFlags(Qt.WindowType.SplashScreen | Qt.WindowType.WindowStaysOnTopHint)
    _splash.show()


def _splash_msg(text):
    if _splash is not None:
        _splash.showMessage(
            text,
            Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignHCenter,
            Qt.GlobalColor.white,
        )
        _app.processEvents()


_splash_msg("실행 준비 중...")


# --- 필수 라이브러리 임포트 및 확인 (스플래시 표시 중 진행) ---
try:
    from PyQt6.QtWidgets import (
        QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
        QPushButton, QFileDialog, QComboBox, QSpinBox, QCheckBox, QTextEdit,
        QMessageBox, QGroupBox, QFormLayout, QListWidget, QListWidgetItem,
        QSizePolicy, QFrame, QDoubleSpinBox, QProgressBar,
        QToolButton, QScrollArea, QLayout, QDialog
    )
    from PyQt6.QtCore import QSettings, QThread, pyqtSignal, QObject, QTimer
    from PyQt6.QtGui import QFont, QTextCursor, QTextCharFormat, QColor, QStandardItemModel, QStandardItem
except ImportError:
    print("치명적 오류: 'PyQt6' 라이브러리를 찾을 수 없습니다. 'pip install PyQt6' 명령어로 설치하세요.")
    sys.exit(1)

_splash_msg("터미널 모듈 로딩 중...")

try:
    import pyte
except ImportError:
    print("치명적 오류: 'pyte' 라이브러리를 찾을 수 없습니다.\n'pip install pyte' 명령어로 설치하세요.")
    sys.exit(1)

_splash_msg("번역 엔진 로딩 중...")

# gemini-srt-translator 임포트 + GUI 안전 몽키패치 적용
import core.gst_compat  # noqa: F401

_splash_msg("UI 구성 중...")

from app.main_window import TranslatorApp


if __name__ == '__main__':
    _splash_msg("실행 준비 중...")
    gui = TranslatorApp()
    gui.show()
    if _splash is not None:
        _splash.finish(gui)
    sys.exit(_app.exec())
