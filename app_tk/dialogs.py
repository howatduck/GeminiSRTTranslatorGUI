# -*- coding: utf-8 -*-
"""Tkinter판 보조 다이얼로그 — 모델 폴백 우선순위 + 커스텀 프리셋 편집."""

import tkinter as tk
from tkinter import ttk

from app.i18n import I18N
from core.style_presets import (
    CUSTOM_PRESET_IDS, custom_slot_index, default_custom_name,
)


def _tr(lang, key, **kwargs):
    template = I18N.get(lang, I18N["ko"]).get(key, I18N["ko"].get(key, key))
    if kwargs:
        try:
            return template.format(**kwargs)
        except Exception:
            return template
    return template


class ModelPriorityDialog:
    """모델 폴백 우선순위를 드래그로 정하는 다이얼로그 (모달).

    결과: 확인 시 (order, disabled) 튜플, 취소 시 None.
    """

    def __init__(self, parent, ordered_models, disabled_models, lang="ko"):
        self.result = None
        self._models = list(ordered_models)
        self._disabled = set(disabled_models or [])
        self._lang = lang

        dlg = tk.Toplevel(parent)
        self._dlg = dlg
        dlg.title(_tr(lang, "mp_title"))
        dlg.transient(parent)
        dlg.grab_set()
        dlg.geometry("420x430")

        ttk.Label(
            dlg, text=_tr(lang, "mp_desc"),
            justify="left").pack(anchor="w", padx=10, pady=(10, 6))

        frame = ttk.Frame(dlg)
        frame.pack(fill="both", expand=True, padx=10)
        self._tree = ttk.Treeview(frame, show="tree", selectmode="browse")
        scroll = ttk.Scrollbar(frame, orient="vertical", command=self._tree.yview)
        self._tree.configure(yscrollcommand=scroll.set)
        self._tree.grid(row=0, column=0, sticky="nsew")
        scroll.grid(row=0, column=1, sticky="ns")
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)
        self._tree.tag_configure("off", foreground="gray")
        for m in self._models:
            self._insert(m)
        self._tree.bind("<ButtonPress-1>", self._on_press)
        self._tree.bind("<B1-Motion>", self._on_drag)

        btn_row = ttk.Frame(dlg)
        btn_row.pack(fill="x", padx=10, pady=8)
        ttk.Button(btn_row, text=_tr(lang, "btn_remove_selected"),
                   command=self._remove_selected).pack(side="left")
        ttk.Button(btn_row, text=_tr(lang, "btn_cancel"),
                   command=self._cancel).pack(side="right")
        ttk.Button(btn_row, text=_tr(lang, "btn_ok"),
                   command=self._ok).pack(side="right", padx=(0, 6))
        dlg.protocol("WM_DELETE_WINDOW", self._cancel)
        parent.wait_window(dlg)

    def _insert(self, model):
        off = model in self._disabled
        text = f"{'☐' if off else '☑'}  {model}"
        self._tree.insert("", "end", iid=f"i{abs(hash(model)) & 0xffffffff}_{len(self._tree.get_children())}",
                          text=text, tags=("off",) if off else ())

    def _model_of(self, iid):
        text = self._tree.item(iid, "text")
        return text[3:] if len(text) > 3 else text

    def _on_press(self, event):
        self._drag_iid = self._tree.identify_row(event.y)
        # 체크 글리프 영역(왼쪽) 클릭이면 토글
        if self._drag_iid and event.x < 28:
            model = self._model_of(self._drag_iid)
            if model in self._disabled:
                self._disabled.discard(model)
            else:
                self._disabled.add(model)
            off = model in self._disabled
            self._tree.item(
                self._drag_iid,
                text=f"{'☐' if off else '☑'}  {model}",
                tags=("off",) if off else ())
            self._drag_iid = None
            return "break"

    def _on_drag(self, event):
        iid = getattr(self, "_drag_iid", None)
        if not iid:
            return
        target = self._tree.identify_row(event.y)
        if target and target != iid:
            index = self._tree.index(target)
            self._tree.move(iid, "", index)

    def _remove_selected(self):
        sel = self._tree.selection()
        if sel and len(self._tree.get_children()) > 1:
            model = self._model_of(sel[0])
            self._disabled.discard(model)
            self._tree.delete(sel[0])

    def _ok(self):
        order = [self._model_of(iid) for iid in self._tree.get_children()]
        disabled = [m for m in order if m in self._disabled]
        self.result = (order, disabled)
        self._dlg.destroy()

    def _cancel(self):
        self.result = None
        self._dlg.destroy()


class CustomPresetDialog:
    """커스텀 프리셋 3개의 이름/지시문 편집. 결과: dict 또는 None."""

    def __init__(self, parent, custom_data=None, lang="ko"):
        self.result = None
        self._lang = lang
        data = dict(custom_data or {})

        dlg = tk.Toplevel(parent)
        self._dlg = dlg
        dlg.title(_tr(lang, "custom_preset_dialog_title"))
        dlg.transient(parent)
        dlg.grab_set()
        dlg.geometry("560x520")

        outer = ttk.Frame(dlg)
        outer.pack(fill="both", expand=True, padx=10, pady=10)
        self._name_vars = {}
        self._instr_texts = {}
        for pid in CUSTOM_PRESET_IDS:
            idx = custom_slot_index(pid)
            d = data.get(pid, {})
            box = ttk.LabelFrame(
                outer, text=_tr(lang, "custom_preset_group", n=idx + 1))
            box.pack(fill="x", pady=(0, 8))
            row = ttk.Frame(box)
            row.pack(fill="x", padx=6, pady=4)
            ttk.Label(row, text=_tr(lang, "custom_preset_name_label")).pack(side="left")
            var = tk.StringVar(
                value=(d.get("name") or "").strip() or default_custom_name(idx, lang))
            ttk.Entry(row, textvariable=var).pack(side="left", fill="x", expand=True)
            self._name_vars[pid] = var
            ttk.Label(box, text=_tr(lang, "custom_preset_instruction_label")).pack(
                anchor="w", padx=6)
            txt = tk.Text(box, height=4, wrap="word")
            txt.pack(fill="x", padx=6, pady=(0, 6))
            txt.insert("1.0", (d.get("instruction") or "").strip())
            self._instr_texts[pid] = txt

        btn_row = ttk.Frame(dlg)
        btn_row.pack(fill="x", padx=10, pady=(0, 10))
        ttk.Button(btn_row, text=_tr(lang, "btn_close"),
                   command=self._cancel).pack(side="right")
        ttk.Button(btn_row, text=_tr(lang, "btn_save"),
                   command=self._ok).pack(side="right", padx=(0, 6))
        dlg.protocol("WM_DELETE_WINDOW", self._cancel)
        parent.wait_window(dlg)

    def _ok(self):
        self.result = {
            pid: {
                "name": self._name_vars[pid].get().strip(),
                "instruction": self._instr_texts[pid].get("1.0", "end").strip(),
            }
            for pid in CUSTOM_PRESET_IDS
        }
        self._dlg.destroy()

    def _cancel(self):
        self.result = None
        self._dlg.destroy()
