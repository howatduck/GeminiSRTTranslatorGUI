# -*- coding: utf-8 -*-
"""커스텀 스타일 프리셋 편집 다이얼로그.

번역 스타일 프리셋 콤보박스의 사용자 슬롯(커스텀 1~3)의
이름과 지시문(프롬프트)을 편집한다.
"""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QTextEdit, QGroupBox,
)

from core.style_presets import (
    CUSTOM_PRESET_IDS,
    custom_slot_index,
    default_custom_name,
)


class CustomPresetDialog(QDialog):
    """커스텀 프리셋 3개의 이름/지시문을 편집. 저장 시 dict 반환."""

    def __init__(self, parent, custom_data=None, lang="ko"):
        super().__init__(parent)
        self._parent = parent
        self._lang = lang
        self._custom_data = dict(custom_data or {})
        self._result = None
        self.setWindowTitle(self._t("custom_preset_dialog_title"))
        self.resize(560, 520)

        layout = QVBoxLayout()

        self._name_edits = {}
        self._instr_edits = {}
        for pid in CUSTOM_PRESET_IDS:
            idx = custom_slot_index(pid)
            data = self._custom_data.get(pid, {})
            box = QGroupBox(self._t("custom_preset_group", n=idx + 1))
            box_layout = QVBoxLayout()

            name_row = QHBoxLayout()
            name_row.addWidget(QLabel(self._t("custom_preset_name_label")))
            name_edit = QLineEdit(
                (data.get("name") or "").strip()
                or default_custom_name(idx, lang)
            )
            name_row.addWidget(name_edit, 1)
            box_layout.addLayout(name_row)

            box_layout.addWidget(
                QLabel(self._t("custom_preset_instruction_label")))
            instr_edit = QTextEdit()
            instr_edit.setPlainText((data.get("instruction") or "").strip())
            instr_edit.setPlaceholderText(
                self._t("custom_preset_instruction_ph"))
            instr_edit.setMinimumHeight(80)
            box_layout.addWidget(instr_edit)

            box.setLayout(box_layout)
            layout.addWidget(box)
            self._name_edits[pid] = name_edit
            self._instr_edits[pid] = instr_edit

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self.btn_save = QPushButton(self._t("btn_save"))
        self.btn_save.clicked.connect(self._on_save)
        self.btn_cancel = QPushButton(self._t("btn_close"))
        self.btn_cancel.clicked.connect(self.reject)
        btn_row.addWidget(self.btn_save)
        btn_row.addWidget(self.btn_cancel)
        layout.addLayout(btn_row)

        self.setLayout(layout)

    def _t(self, key, **kwargs):
        try:
            return self._parent.tr_str(key, **kwargs)
        except Exception:
            return key

    def _on_save(self):
        result = {}
        for pid in CUSTOM_PRESET_IDS:
            result[pid] = {
                "name": self._name_edits[pid].text().strip(),
                "instruction": self._instr_edits[pid].toPlainText().strip(),
            }
        self._result = result
        self.accept()

    def get_data(self):
        """저장된 커스텀 프리셋 dict. 취소 시 None."""
        return self._result
