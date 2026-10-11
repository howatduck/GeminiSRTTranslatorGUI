# -*- coding: utf-8 -*-
"""
Gemini SRT Translator GUI (v3.8.3 호환, Pyte VT100 터미널)
v3.8.0 ~ v3.8.3 최신 변경사항 반영 (SubtitleSession 엔진, 적응형 배치/오디오청크 감축, context_size 통일 등)
"""

import sys

# 프로세스 안전 패치(exit/signal 가드) 및 FFmpeg 경로 등록: 가장 먼저 적용
import core.safety  # noqa: F401



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

# gemini-srt-translator 임포트 + GUI 안전 몽키패치 적용
import core.gst_compat  # noqa: F401

from app.main_window import TranslatorApp




if __name__ == '__main__':
    app = QApplication(sys.argv)
    gui = TranslatorApp()
    gui.show()
    sys.exit(app.exec())
