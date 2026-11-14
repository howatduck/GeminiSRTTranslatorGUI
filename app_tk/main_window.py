# -*- coding: utf-8 -*-
"""Tkinter판 메인 윈도우 — app/main_window.py(TranslatorApp)의 포팅.

위젯 구성·설정 키·작업 생성·실행 로직은 PyQt판과 동일하게 맞췄고,
프레임워크 결합부(QSettings→JsonSettings, QThread→threading,
pyqtSignal→Signal, 메시지박스→messagebox)만 교체했다.
"""

import hashlib
import json
import logging
import os
import queue
import re
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from app.i18n import I18N
from app_tk.dialogs import CustomPresetDialog, ModelPriorityDialog
from app_tk.settings import JsonSettings
from app_tk.theme import LISTBOX_STYLE, TEXT_STYLE, make_title_strip
from app_tk.widgets import (
    CheckableDropdown, TerminalLog, enable_file_drop, set_enabled,
    set_entry_placeholder,
)
from app_tk.workers import ModelFetcherThread, TranslationWorker, UpdateCheckThread
from core.config import (
    API_KEY_SETTINGS, APP_NAME, DEFAULT_BATCH_SIZE, DEFAULT_MODEL,
    NUM_API_KEYS, SETTINGS_APP, SETTINGS_ORG, is_text_model,
)
from core.gst_compat import (
    GENAI_IMPORT_ERROR, GST_IMPORT_ERROR, genai, gst, reset_library_logger,
)
from core.languages import (
    TARGET_LANGUAGES, _get_iso_lang_code, _normalize_lang_name,
    clean_custom_language_name, find_language_match,
)
from core.media import (
    _extract_subtitle_track, _get_media_duration, _get_video_subtitle_streams,
    _is_sdh_stream, _pick_same_language_stream, _pick_translation_stream,
)
from core.style_presets import compose_description, all_presets, CUSTOM_PRESET_IDS
from core.pricing import read_report_cost, token_report_path_for
from core.errors import failure_advice
from core.subtitle_io import (
    is_translation_complete, set_strip_final_periods, set_signature_config,
    DEFAULT_SIGNATURE_TEMPLATE)


def _unique_stem(src_path):
    """소스 경로 기반 고유 파일명 stem (PyQt판과 동일)."""
    base = os.path.splitext(os.path.basename(src_path))[0]
    digest = hashlib.sha1(os.path.abspath(src_path).encode("utf-8")).hexdigest()[:8]
    return f"{base}_{digest}"


_UNIQUE_SUFFIX_RE = re.compile(r"_[0-9a-f]{8}$")


def _output_base_name(src_path):
    """최종 출력 파일명에 쓸 stem (PyQt판과 동일)."""
    stem = os.path.splitext(os.path.basename(src_path))[0]
    if stem.endswith("_extracted"):
        stem = stem[:-len("_extracted")]
        stem = _UNIQUE_SUFFIX_RE.sub("", stem)
    return stem


def _skipped_videos_notice(videos_without_subs):
    """자막이 없어 건너뛴 영상을 알리는 로그 문구 (PyQt판과 동일)."""
    if not videos_without_subs:
        return None
    names = ", ".join(os.path.basename(v) for v in videos_without_subs)
    return (
        f"  → 내장 자막이 없어 건너뛴 영상 {len(videos_without_subs)}개: {names} "
        f"(전사 모드로 따로 실행하세요)"
    )


class TranslatorAppTk:
    """Tkinter판 메인 창. root는 tk.Tk 인스턴스."""

    def __init__(self, root, settings_path=None):
        self.root = root
        self.settings = JsonSettings(SETTINGS_ORG, SETTINGS_APP, path=settings_path)
        self.custom_presets = {}
        self.input_files = []
        out_dir = self.settings.value("output_dir", os.path.expanduser("~"))
        self.output_dir = out_dir if isinstance(out_dir, str) and os.path.isdir(out_dir) else os.path.expanduser("~")
        self.model_fetcher_thread = None
        self.update_check_thread = None
        self.translation_worker = None
        self.job_queue = None
        self.total_jobs = 0
        self.completed_jobs = 0
        self.failed_jobs = 0
        self.last_job_errors = []
        self.model_fallback_order = []
        self.model_fallback_disabled = []
        self.show_all_models = False
        self.job_completion_lock = threading.Lock()
        self.jobs = []
        self.recent_outputs = []
        self.extracted_temp_files = []
        self._stop_requested = False
        self.video_file_paths = []
        self.audio_file_path = ""
        self.app_lang = "ko"
        self.skipped_completed_jobs = 0
        self._failure_help_pending = 0

        self._ui_queue = queue.Queue()
        self._toggle_widgets = []
        self._i18n_texts = []

        self._init_vars()
        self._build_ui()
        self.custom_presets = self._load_custom_presets()
        self._refresh_style_combo()
        self.load_settings()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.after(50, self._poll_ui_queue)

        if GST_IMPORT_ERROR or GENAI_IMPORT_ERROR:
            msg = ""
            if GST_IMPORT_ERROR:
                msg += (
                    "gemini-srt-translator 로드 실패 → '작업 시작' 버튼이 비활성화됩니다.\n"
                    f"오류 내용: {GST_IMPORT_ERROR}\n\n"
                )
            if GENAI_IMPORT_ERROR:
                msg += (
                    "google-genai 로드 실패 → '모델 가져오기' 버튼이 비활성화됩니다.\n"
                    f"오류 내용: {GENAI_IMPORT_ERROR}\n"
                )
            messagebox.showwarning("라이브러리 로드 경고", msg, parent=self.root)

    # ------------------------------------------------------------------
    # UI 스레드 디스패치 (워커 시그널 → Tk 메인 루프)
    # ------------------------------------------------------------------
    def _dispatch(self, fn):
        self._ui_queue.put(fn)

    def _poll_ui_queue(self):
        while True:
            try:
                fn = self._ui_queue.get_nowait()
            except queue.Empty:
                break
            try:
                fn()
            except Exception:
                pass
        try:
            self.root.after(50, self._poll_ui_queue)
        except Exception:
            pass

    def _pump(self):
        """QApplication.processEvents() 대체 (추출 진행 표시용)."""
        try:
            self.root.update_idletasks()
            self.root.update()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # 변수 (PyQt 위젯 값 접근의 대체)
    # ------------------------------------------------------------------
    def _init_vars(self):
        v = {}
        self.api_key_vars = [tk.StringVar() for _ in range(NUM_API_KEYS)]
        for var in self.api_key_vars:
            var.trace_add("write", lambda *a: self._update_api_keys_summary())
        v["app_lang"] = tk.StringVar(value="한국어")
        v["task_mode"] = tk.StringVar()
        v["model"] = tk.StringVar(value=DEFAULT_MODEL)
        v["style"] = tk.StringVar()
        v["out_label"] = tk.StringVar(value=self.output_dir)
        v["audio_label"] = tk.StringVar()
        v["custom_lang"] = tk.StringVar()
        v["api_summary"] = tk.StringVar()
        v["progress"] = tk.DoubleVar(value=0)
        v["progress_text"] = tk.StringVar()
        v["signature_template"] = tk.StringVar()
        v["signature_pos"] = tk.StringVar()
        v["service_tier"] = tk.StringVar(value="Default")
        v["thinking_level"] = tk.StringVar(value="Default")
        v["request_type"] = tk.StringVar(value="Default")
        v["cloud_project"] = tk.StringVar()
        v["cloud_api_key"] = tk.StringVar()
        v["cloud_location"] = tk.StringVar()
        # 숫자
        v["batch"] = tk.IntVar(value=DEFAULT_BATCH_SIZE)
        v["start_line"] = tk.IntVar(value=1)
        v["temp"] = tk.DoubleVar(value=0.9)
        v["top_p"] = tk.DoubleVar(value=1.0)
        v["top_k"] = tk.IntVar(value=0)
        v["thinking_budget"] = tk.IntVar(value=2048)
        v["audio_chunk"] = tk.IntVar(value=300)
        v["resume_context"] = tk.IntVar(value=0)
        v["batch_error_step"] = tk.IntVar(value=100)
        v["audio_chunk_error_step"] = tk.IntVar(value=60)
        v["batch_step_down"] = tk.IntVar(value=0)
        v["batch_floor"] = tk.IntVar(value=100)
        # 체크박스
        for name, default in (
            ("use_enterprise", False), ("model_fallback", True),
            ("append_lang", True), ("reuse_extracted", True),
            ("keep_extracted", False), ("extract_audio", False),
            ("free", True), ("isolate_voice", True),
            ("streaming", True), ("thinking", True), ("resume", True),
            ("force_retranslate", False), ("prefer_sdh", False),
            ("show_failure_help", True),
            ("strip_periods", True), ("thoughts_log", False),
            ("progress_log", False), ("token_stats", True),
            ("token_report", False), ("show_all_models", False),
            ("signature", False), ("show_api_keys", False),
        ):
            v[name] = tk.BooleanVar(value=default)
        self.vars = v

    def _get(self, name, fallback):
        """IntVar/DoubleVar 안전 읽기 (빈 입력·잘못된 값이면 fallback)."""
        try:
            return self.vars[name].get()
        except Exception:
            return fallback

    def _trw(self, widget, key, **kwargs):
        # 위젯 문구를 i18n 키로 설정하고 언어 전환 시 재적용 목록에 등록
        try:
            widget.configure(text=self.tr_str(key, **kwargs))
        except Exception:
            pass
        self._i18n_texts.append((widget, key, kwargs))
        return widget

    def _update_ui_language(self):
        # 언어 전환 시 등록 문구 전체를 현재 언어로 재적용 (Qt판 패리티)
        for widget, key, kwargs in list(self._i18n_texts):
            try:
                widget.configure(text=self.tr_str(key, **kwargs))
            except Exception:
                pass
        for dlg, key in ((getattr(self, "api_keys_dialog", None), "dialog_api_title"),
                         (getattr(self, "advanced_dialog", None), "advanced_dialog_title")):
            if dlg is not None:
                try:
                    dlg.title(self.tr_str(key))
                except Exception:
                    pass
        # 서명 위치 콤보: 데이터(start/end) 기준으로 표시 문구만 교체
        try:
            data = self._signature_pos_data()
            self.cmb_signature_pos.configure(
                values=[self.tr_str("sig_pos_start"), self.tr_str("sig_pos_end")])
            self.vars["signature_pos"].set(
                self.tr_str("sig_pos_end") if data == "end"
                else self.tr_str("sig_pos_start"))
        except Exception:
            pass
        self._set_audio_label(getattr(self, "audio_file_path", ""))

    def tr_str(self, key, **kwargs):
        lang = getattr(self, "app_lang", "ko")
        template = I18N.get(lang, I18N["ko"]).get(key, I18N["ko"].get(key, key))
        if kwargs:
            try:
                return template.format(**kwargs)
            except Exception:
                return template
        return template

    # ------------------------------------------------------------------
    # UI 구축
    # ------------------------------------------------------------------
    def _build_ui(self):
        self.root.title(APP_NAME)
        self.root.geometry("1080x820")
        _base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        _icon_path = os.path.join(_base, "assets", "app.ico")
        if os.path.exists(_icon_path):
            try:
                self.root.iconbitmap(_icon_path)
            except Exception:
                pass

        make_title_strip(self.root, "GEMINI SRT TRANSLATOR",
                         "Tkinter · Retro Edition")
        _icon_png = os.path.join(_base, "assets", "app_tk.png")
        if os.path.exists(_icon_png):
            try:
                _img = tk.PhotoImage(file=_icon_png)
                self.root.iconphoto(True, _img)
                self.root._tk_icon_image = _img  # GC 방지 참조 유지
            except Exception:
                pass
        main = ttk.Frame(self.root)
        main.pack(fill="both", expand=True)
        top = ttk.Frame(main)
        top.pack(fill="both", expand=True)
        left = ttk.Frame(top)
        left.pack(side="left", fill="both", expand=True)
        right = ttk.Frame(top)
        right.pack(side="left", fill="both", expand=True)

        self._build_api_keys_dialog()
        self._create_api_group(left)
        self._create_main_options_group(left)
        self._create_options_group(left)
        self._create_file_lang_group(right)
        self._create_action_log_group(main)

    def _track(self, widget):
        self._toggle_widgets.append(widget)
        return widget

    def _create_api_group(self, parent):
        group = ttk.LabelFrame(parent)
        group.pack(fill="x", padx=4, pady=4)
        self.api_group = group
        self._trw(group, "api_group_title")

        row = ttk.Frame(group)
        row.pack(fill="x", padx=6, pady=4)
        self.btn_manage_api_keys = self._track(ttk.Button(
            row, command=self._open_api_keys_dialog))
        self._trw(self.btn_manage_api_keys, "btn_manage_api_keys")
        self.btn_manage_api_keys.pack(side="left")
        ttk.Label(row, textvariable=self.vars["api_summary"]).pack(side="left", padx=6)
        self.lbl_app_lang = ttk.Label(row)
        self._trw(self.lbl_app_lang, "lbl_app_lang")
        self.lbl_app_lang.pack(side="left", padx=(16, 2))
        self.cmb_app_lang = ttk.Combobox(
            row, values=["한국어", "English"], state="readonly", width=9,
            textvariable=self.vars["app_lang"])
        self.cmb_app_lang.pack(side="left")
        self.cmb_app_lang.bind("<<ComboboxSelected>>", self._on_app_lang_changed)
        self._update_api_keys_summary()

        ent_row = ttk.Frame(group)
        ent_row.pack(fill="x", padx=6, pady=2)
        self.chk_use_enterprise = ttk.Checkbutton(
            ent_row, variable=self.vars["use_enterprise"],
            command=self._on_enterprise_changed)
        self._trw(self.chk_use_enterprise, "chk_use_enterprise")
        self.chk_use_enterprise.pack(side="left")
        self._track(self.chk_use_enterprise)

        self.enterprise_frame = ttk.Frame(group)
        erows = (
            ("Cloud Project:", "cloud_project", "Google Cloud Project ID (ADC)", False),
            ("Cloud API Key:", "cloud_api_key", "Google Cloud API Key (Express)", True),
            ("Cloud Location:", "cloud_location", "Region (기본: global)", False),
        )
        self.cloud_inputs = {}
        for label, key, _ph, secret in erows:
            r = ttk.Frame(self.enterprise_frame)
            r.pack(fill="x", padx=6, pady=2)
            _clbl = ttk.Label(r, text=label, width=16)
            _clbl.pack(side="left")
            self._trw(_clbl, key + "_label")
            entry = ttk.Entry(r, textvariable=self.vars[key],
                              show="•" if secret else "")
            entry.pack(side="left", fill="x", expand=True)
            self.cloud_inputs[key] = self._track(entry)
        r = ttk.Frame(self.enterprise_frame)
        r.pack(fill="x", padx=6, pady=2)
        _rtlbl = ttk.Label(r, width=16)
        self._trw(_rtlbl, "request_type_label")
        _rtlbl.pack(side="left")
        cmb_rt = ttk.Combobox(
            r, values=["Default", "shared", "dedicated"], state="readonly",
            textvariable=self.vars["request_type"], width=14)
        cmb_rt.pack(side="left")
        self.cmb_request_type = self._track(cmb_rt)
        # 기업용 필드는 기본 숨김 (PyQt판과 동일)
        # (enterprise_frame은 체크 시에만 pack한다)

        self.btn_save_api = self._track(ttk.Button(
            group, command=self.save_settings))
        self._trw(self.btn_save_api, "btn_save_api")
        self.btn_save_api.pack(anchor="w", padx=6, pady=4)

    def _on_enterprise_changed(self):
        if self.vars["use_enterprise"].get():
            # 기업용 필드를 저장 버튼 위에 오도록 pack 순서를 맞춘다
            self.btn_save_api.pack_forget()
            self.enterprise_frame.pack(fill="x")
            self.btn_save_api.pack(anchor="w", padx=6, pady=4)
        else:
            self.enterprise_frame.pack_forget()

    def _build_api_keys_dialog(self):
        dlg = tk.Toplevel(self.root)
        dlg.title(self.tr_str("dialog_api_title"))
        dlg.geometry("480x500")
        dlg.transient(self.root)
        dlg.withdraw()
        self.api_keys_dialog = dlg
        dlg.protocol("WM_DELETE_WINDOW", self._close_api_keys_dialog)

        self.dialog_info_label = ttk.Label(dlg, justify="left", wraplength=440)
        self._trw(self.dialog_info_label, "dialog_api_info")
        self.dialog_info_label.pack(anchor="w", padx=10, pady=8)

        canvas_frame = ttk.Frame(dlg)
        canvas_frame.pack(fill="both", expand=True, padx=10)
        canvas = tk.Canvas(canvas_frame, highlightthickness=0)
        scroll = ttk.Scrollbar(canvas_frame, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scroll.set)
        canvas.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        inner = ttk.Frame(canvas)
        canvas.create_window((0, 0), window=inner, anchor="nw")
        inner.bind("<Configure>",
                   lambda e: canvas.configure(scrollregion=canvas.bbox("all")))

        self.api_key_entries = []
        self.api_key_labels = []
        for i in range(NUM_API_KEYS):
            r = ttk.Frame(inner)
            r.pack(fill="x", pady=2)
            _klbl = ttk.Label(r, width=10)
            self._trw(_klbl, "api_key_label", index=i + 1)
            _klbl.pack(side="left")
            self.api_key_labels.append(_klbl)
            entry = ttk.Entry(r, textvariable=self.api_key_vars[i], show="•", width=44)
            entry.pack(side="left", fill="x", expand=True)
            self.api_key_entries.append(entry)
            self._track(entry)

        chk = ttk.Checkbutton(
            dlg, variable=self.vars["show_api_keys"],
            command=self._toggle_api_keys_visibility)
        self._trw(chk, "chk_show_api_keys")
        chk.pack(anchor="w", padx=10, pady=4)
        self._track(chk)

        btn_row = ttk.Frame(dlg)
        btn_row.pack(fill="x", padx=10, pady=8)
        self.btn_dialog_close = ttk.Button(
            btn_row, command=self._close_api_keys_dialog)
        self._trw(self.btn_dialog_close, "btn_close")
        self.btn_dialog_close.pack(side="right")
        self.btn_dialog_save = ttk.Button(
            btn_row, command=self._save_api_keys_and_close)
        self._trw(self.btn_dialog_save, "btn_save")
        self.btn_dialog_save.pack(side="right", padx=(0, 6))

    def _toggle_api_keys_visibility(self):
        show = "" if self.vars["show_api_keys"].get() else "•"
        for entry in self.api_key_entries:
            entry.configure(show=show)

    def _open_api_keys_dialog(self):
        self._update_api_keys_summary()
        self.api_keys_dialog.deiconify()
        self.api_keys_dialog.grab_set()

    def _close_api_keys_dialog(self):
        try:
            self.api_keys_dialog.grab_release()
        except Exception:
            pass
        self.api_keys_dialog.withdraw()
        self._update_api_keys_summary()

    def _save_api_keys_and_close(self):
        self.save_settings()
        self._close_api_keys_dialog()

    def _update_api_keys_summary(self):
        if not hasattr(self, "vars"):
            return
        filled = sum(1 for var in self.api_key_vars if var.get().strip())
        self.vars["api_summary"].set(
            self.tr_str("lbl_api_keys_summary", filled=filled, total=NUM_API_KEYS))

    # (파일/언어 그룹, 기본 설정 그룹, 고급 설정, 실행/로그 그룹은 아래 계속)

    # ------------------------------------------------------------------
    # 파일 및 언어 그룹
    # ------------------------------------------------------------------
    def _create_file_lang_group(self, parent):
        group = ttk.LabelFrame(parent)
        group.pack(fill="both", expand=True, padx=4, pady=4)
        self.file_lang_group = group
        self._trw(group, "file_lang_group_title")

        row = ttk.Frame(group)
        row.pack(fill="x", padx=6, pady=4)
        _tmlbl = ttk.Label(row)
        self._trw(_tmlbl, "lbl_task_mode")
        _tmlbl.pack(side="left")
        self.cmb_task_mode = ttk.Combobox(
            row, state="readonly", textvariable=self.vars["task_mode"], width=36)
        self.cmb_task_mode.pack(side="left", fill="x", expand=True, padx=4)
        self.cmb_task_mode.bind("<<ComboboxSelected>>", self._on_task_mode_changed)
        self._track(self.cmb_task_mode)
        self._set_task_mode_items()

        row = ttk.Frame(group)
        row.pack(fill="x", padx=6, pady=2)
        self.btn_files = ttk.Button(row, command=self.select_input_files)
        self._trw(self.btn_files, "btn_files")
        self.btn_files.pack(side="left", fill="x", expand=True)
        self.btn_clear_files = self._track(ttk.Button(
            row, text="X", width=3, style="Small.TButton", command=self.clear_input_files))
        self.btn_clear_files.pack(side="left", padx=(4, 0))
        self._track(self.btn_files)

        self.lst_files = tk.Listbox(group, height=3, **LISTBOX_STYLE)
        self.lst_files.pack(fill="x", padx=6, pady=2)
        self._track(self.lst_files)

        row = ttk.Frame(group)
        row.pack(fill="x", padx=6, pady=2)
        self.btn_out = self._track(ttk.Button(
            row, command=self.select_output_directory))
        self._trw(self.btn_out, "btn_out")
        self.btn_out.pack(side="left")
        out_entry = ttk.Entry(row, textvariable=self.vars["out_label"], state="readonly", width=8)
        out_entry.pack(side="left", fill="x", expand=True, padx=4)
        self.btn_preview = self._track(ttk.Button(
            row, command=self.open_preview_editor))
        self._trw(self.btn_preview, "btn_preview")
        self.btn_preview.pack(side="left")

        row = ttk.Frame(group)
        row.pack(fill="x", padx=6, pady=2)
        self.btn_video_file = ttk.Button(row, command=self.select_video_file)
        self._trw(self.btn_video_file, "btn_video_file")
        self.btn_video_file.pack(side="left", fill="x", expand=True)
        self.btn_clear_video_file = self._track(ttk.Button(
            row, text="X", width=3, style="Small.TButton", command=self.clear_video_file))
        self.btn_clear_video_file.pack(side="left", padx=(4, 0))
        self._track(self.btn_video_file)

        self.lst_video_files = tk.Listbox(group, height=3, **LISTBOX_STYLE)
        self.lst_video_files.pack(fill="x", padx=6, pady=2)
        self._track(self.lst_video_files)
        # OS 파일 드래그&드롭 (tkinterdnd2 있을 때만 활성)
        enable_file_drop(self.lst_files, self._on_drop_input_files)
        enable_file_drop(self.lst_video_files, self._on_drop_video_files)

        row = ttk.Frame(group)
        row.pack(fill="x", padx=6, pady=2)
        self.btn_audio_file = ttk.Button(row, command=self.select_audio_file)
        self._trw(self.btn_audio_file, "btn_audio_file")
        self.btn_audio_file.pack(side="left")
        self.audio_entry = ttk.Entry(row, textvariable=self.vars["audio_label"],
                                     state="readonly")
        self.audio_entry.pack(side="left", fill="x", expand=True, padx=4)
        self.btn_clear_audio_file = self._track(ttk.Button(
            row, text="X", width=3, style="Small.TButton", command=self.clear_audio_file))
        self.btn_clear_audio_file.pack(side="left")
        self._track(self.btn_audio_file)
        self._set_audio_label("")

        ttk.Separator(group, orient="horizontal").pack(fill="x", padx=6, pady=6)

        row = ttk.Frame(group)
        row.pack(fill="x", padx=6, pady=2)
        _tllbl = ttk.Label(row)
        self._trw(_tllbl, "lbl_target_lang")
        _tllbl.pack(side="left")
        self.btn_none_lang = self._track(ttk.Button(
            row, style="Small.TButton",
            command=self.deselect_all_languages))
        self._trw(self.btn_none_lang, "btn_none_lang")
        self.btn_none_lang.pack(side="right")
        self.btn_all_lang = self._track(ttk.Button(
            row, style="Small.TButton",
            command=self.select_all_languages))
        self._trw(self.btn_all_lang, "btn_all_lang")
        self.btn_all_lang.pack(side="right", padx=(0, 4))

        self.cmb_langs = CheckableDropdown(group)
        self.cmb_langs.pack(fill="x", padx=6, pady=2)
        for lang in TARGET_LANGUAGES:
            self.cmb_langs.addItem(lang)
        self.cmb_langs.set_placeholder_text(self.tr_str("cmb_langs_ph"))
        self._track(self.cmb_langs._button)

        row = ttk.Frame(group)
        row.pack(fill="x", padx=6, pady=2)
        lang_entry = ttk.Entry(row, textvariable=self.vars["custom_lang"])
        lang_entry.pack(side="left", fill="x", expand=True)
        lang_entry.bind("<Return>", lambda e: self.add_custom_language())
        self.txt_custom_lang = lang_entry
        # Qt판 플레이스홀더 안내문구 패리티 (Tk Entry에는 기본 기능이 없음)
        self._custom_lang_ph = set_entry_placeholder(
            lang_entry, self.vars["custom_lang"], self.tr_str("custom_lang_ph"))
        self.btn_add_lang = self._track(ttk.Button(
            row, command=self.add_custom_language))
        self._trw(self.btn_add_lang, "btn_add_lang")
        self.btn_add_lang.pack(side="left", padx=(4, 0))
        self._track(lang_entry)

    def _set_task_mode_items(self):
        current = 1 if self.vars["task_mode"].get() == self.tr_str("task_mode_transcribe") else 0
        items = [self.tr_str("task_mode_translate"), self.tr_str("task_mode_transcribe")]
        self.cmb_task_mode.configure(values=items)
        self.vars["task_mode"].set(items[current])

    def _task_mode_index(self):
        return 1 if self.vars["task_mode"].get() == self.tr_str("task_mode_transcribe") else 0

    def _on_task_mode_changed(self, event=None):
        is_transcribe = self._task_mode_index() == 1
        for w in (self.btn_files, self.lst_files, self.btn_clear_files):
            set_enabled(w, not is_transcribe)

    def _set_audio_label(self, path):
        if path:
            self.vars["audio_label"].set(os.path.basename(path))
        else:
            self.vars["audio_label"].set(self.tr_str("lbl_audio_file_ph"))

    # ------------------------------------------------------------------
    # 기본 설정 그룹
    # ------------------------------------------------------------------
    def _create_main_options_group(self, parent):
        group = ttk.LabelFrame(parent)
        group.pack(fill="x", padx=4, pady=4)
        self.main_options_group = group
        self._trw(group, "main_options_group_title")

        row = ttk.Frame(group)
        row.pack(fill="x", padx=6, pady=4)
        _mlbl = ttk.Label(row)
        self._trw(_mlbl, "lbl_model")
        _mlbl.pack(side="left")
        self.btn_fetch = ttk.Button(row, command=self.fetch_models)
        self._trw(self.btn_fetch, "btn_fetch")
        self.btn_fetch.pack(side="left", padx=(6, 4))
        if not genai:
            set_enabled(self.btn_fetch, False)
        self.cmb_model = ttk.Combobox(
            row, textvariable=self.vars["model"], values=[DEFAULT_MODEL])
        self.cmb_model.pack(side="left", fill="x", expand=True)
        self._track(self.cmb_model)
        self.chk_model_fallback = ttk.Checkbutton(
            row, variable=self.vars["model_fallback"])
        self._trw(self.chk_model_fallback, "chk_model_fallback")
        self.chk_model_fallback.pack(side="left", padx=(6, 2))
        self._track(self.chk_model_fallback)
        self.btn_model_order = self._track(ttk.Button(
            row, command=self.open_model_priority_dialog))
        self._trw(self.btn_model_order, "btn_model_order")
        self.btn_model_order.pack(side="left")

        row = ttk.Frame(group)
        row.pack(fill="x", padx=6, pady=2)
        self.chk_append_lang = ttk.Checkbutton(row, variable=self.vars["append_lang"])
        self._trw(self.chk_append_lang, "chk_append_lang")
        self.chk_append_lang.pack(side="left", padx=(0, 14))
        self._track(self.chk_append_lang)
        self.chk_reuse_extracted = ttk.Checkbutton(
            row, variable=self.vars["reuse_extracted"])
        self._trw(self.chk_reuse_extracted, "chk_reuse_extracted")
        self.chk_reuse_extracted.pack(side="left", padx=(0, 14))
        self._track(self.chk_reuse_extracted)
        row = ttk.Frame(group)
        row.pack(fill="x", padx=6, pady=2)
        self.chk_keep_extracted = ttk.Checkbutton(
            row, variable=self.vars["keep_extracted"])
        self._trw(self.chk_keep_extracted, "chk_keep_extracted")
        self.chk_keep_extracted.pack(side="left")
        self._track(self.chk_keep_extracted)

        row = ttk.Frame(group)
        row.pack(fill="x", padx=6, pady=2)
        _blbl = ttk.Label(row)
        self._trw(_blbl, "lbl_batch")
        _blbl.pack(side="left")
        spin = ttk.Spinbox(row, from_=1, to=5000, textvariable=self.vars["batch"], width=8)
        spin.pack(side="left", padx=4)
        self._track(spin)

        _plbl = ttk.Label(group)
        self._trw(_plbl, "lbl_prompt")
        _plbl.pack(anchor="w", padx=6, pady=(4, 0))
        self.txt_desc = tk.Text(group, height=3, wrap="word", **TEXT_STYLE)
        self.txt_desc.pack(fill="x", padx=6, pady=2)
        self._track(self.txt_desc)

        row = ttk.Frame(group)
        row.pack(fill="x", padx=6, pady=2)
        _slbl = ttk.Label(row)
        self._trw(_slbl, "lbl_style")
        _slbl.pack(side="left")
        self.cmb_style = ttk.Combobox(row, state="readonly", width=34,
                                      textvariable=self.vars["style"])
        self.cmb_style.pack(side="left", padx=4)
        self._track(self.cmb_style)
        self.btn_edit_custom = self._track(ttk.Button(
            row, command=self.open_custom_preset_editor))
        self._trw(self.btn_edit_custom, "btn_edit_custom_preset")
        self.btn_edit_custom.pack(side="left")

        row = ttk.Frame(group)
        row.pack(fill="x", padx=6, pady=4)
        self.btn_skill_install = self._track(ttk.Button(
            row, command=self.open_skill_installer))
        self._trw(self.btn_skill_install, "btn_skill_install")
        self.btn_skill_install.pack(side="left")
        self.btn_update_check = self._track(ttk.Button(
            row, command=self.check_library_update))
        self._trw(self.btn_update_check, "btn_update_check")
        self.btn_update_check.pack(side="left", padx=4)
        self.btn_subtitle_tools = self._track(ttk.Button(
            row, command=self.open_subtitle_tools))
        self._trw(self.btn_subtitle_tools, "btn_subtitle_tools")
        self.btn_subtitle_tools.pack(side="left")
        self.btn_agent_exchange = self._track(ttk.Button(
            row, command=self.open_agent_exchange))
        self._trw(self.btn_agent_exchange, "btn_agent_exchange")
        self.btn_agent_exchange.pack(side="left", padx=4)

    def _refresh_style_combo(self):
        current_id = self._current_style_id()
        lang = getattr(self, 'app_lang', 'ko')
        custom_data = getattr(self, 'custom_presets', {})
        labels = []
        self._style_ids = []
        for p in all_presets(custom_data, lang):
            name_key = "name_ko" if lang == "ko" else "name_en"
            labels.append(p.get(name_key) or p.get("name"))
            self._style_ids.append(p["id"])
        self.cmb_style.configure(values=labels)
        if current_id in self._style_ids:
            self.vars["style"].set(labels[self._style_ids.index(current_id)])
        elif labels:
            self.vars["style"].set(labels[0])

    def _current_style_id(self):
        label = self.vars["style"].get()
        values = list(self.cmb_style.cget("values")) if hasattr(self, "cmb_style") else []
        if label in values and hasattr(self, "_style_ids"):
            return self._style_ids[values.index(label)]
        return "default"

    # ------------------------------------------------------------------
    # 고급 설정 (버튼 + 다이얼로그)
    # ------------------------------------------------------------------
    def _create_options_group(self, parent):
        row = ttk.Frame(parent)
        row.pack(fill="x", padx=4, pady=2)
        self.btn_advanced = self._track(ttk.Button(
            row, command=self.open_advanced_settings))
        self._trw(self.btn_advanced, "btn_advanced")
        self.btn_advanced.pack(side="left")
        self._build_advanced_dialog()

    def _build_advanced_dialog(self):
        dlg = tk.Toplevel(self.root)
        dlg.title(self.tr_str("advanced_dialog_title"))
        dlg.geometry("760x430")
        dlg.transient(self.root)
        dlg.withdraw()
        self.advanced_dialog = dlg
        dlg.protocol("WM_DELETE_WINDOW", self._close_advanced_dialog)

        body = ttk.Frame(dlg)
        body.pack(fill="both", expand=True, padx=10, pady=8)

        def spin(parent, var_name, from_, to, step=1, fmt=None, width=8):
            w = ttk.Spinbox(parent, from_=from_, to=to, increment=step,
                            textvariable=self.vars[var_name], width=width,
                            format=fmt or "%d")
            self._track(w)
            return w

        def row(label, key=None):
            r = ttk.Frame(body)
            r.pack(fill="x", pady=2)
            lbl = ttk.Label(r, text=label, width=14)
            lbl.pack(side="left")
            if key:
                self._trw(lbl, key)
            return r

        r = row("서비스 티어:", "lbl_service_tier")
        cmb = ttk.Combobox(r, values=["Default", "standard", "flex", "priority"],
                           state="readonly", textvariable=self.vars["service_tier"], width=16)
        cmb.pack(side="left")
        self._track(cmb)

        r = row("시작 라인:", "lbl_start_line")
        spin(r, "start_line", 1, 99999).pack(side="left")

        r = row("Temp:")
        spin(r, "temp", 0.0, 2.0, 0.1, "%.1f").pack(side="left")
        ttk.Label(r, text="Top_p:", width=10).pack(side="left", padx=(12, 0))
        spin(r, "top_p", 0.0, 1.0, 0.1, "%.1f").pack(side="left")

        r = row("Top_k:")
        spin(r, "top_k", 0, 100).pack(side="left")
        _tblbl = ttk.Label(r, width=10)
        self._trw(_tblbl, "lbl_thinking_budget")
        _tblbl.pack(side="left", padx=(12, 0))
        spin(r, "thinking_budget", 0, 32768).pack(side="left")

        r = row("사고 수준:", "lbl_thinking_level")
        cmb = ttk.Combobox(r, values=["Default", "Minimal", "Low", "Medium", "High"],
                           state="readonly", textvariable=self.vars["thinking_level"], width=16)
        cmb.pack(side="left")
        self._track(cmb)
        _aclbl = ttk.Label(r, width=10)
        self._trw(_aclbl, "lbl_audio_chunk")
        _aclbl.pack(side="left", padx=(12, 0))
        spin(r, "audio_chunk", 60, 3600).pack(side="left")

        r = row("Context Size:")
        spin(r, "resume_context", 0, 10000).pack(side="left")
        _rhlbl = ttk.Label(r)
        self._trw(_rhlbl, "lbl_resume_help")
        _rhlbl.pack(side="left", padx=6)

        r = row("적응형 복구:")
        _bslbl = ttk.Label(r, width=14)
        self._trw(_bslbl, "lbl_batch_step")
        _bslbl.pack(side="left")
        spin(r, "batch_error_step", 10, 1000, 50).pack(side="left")
        _aslbl = ttk.Label(r, width=14)
        self._trw(_aslbl, "lbl_audio_step")
        _aslbl.pack(side="left", padx=(12, 0))
        spin(r, "audio_chunk_error_step", 10, 600, 30).pack(side="left")
        _ahlbl = ttk.Label(r)
        self._trw(_ahlbl, "lbl_adaptive_help")
        _ahlbl.pack(side="left", padx=6)

        r = row("작업 폴백:")
        ttk.Label(r, text="배치 감소폭:", width=14).pack(side="left")
        spin(r, "batch_step_down", 0, 2000, 50).pack(side="left")
        ttk.Label(r, text="배치 하한:", width=14).pack(side="left", padx=(12, 0))
        spin(r, "batch_floor", 10, 5000, 50).pack(side="left")
        ttk.Label(r, text="(작업 실패 시 재시도 조건)").pack(side="left", padx=6)

        r = row("모델 목록:")
        chk = ttk.Checkbutton(
            r, text="모든 모델 표시 (번역 불가 모델 포함)",
            variable=self.vars["show_all_models"], command=self._sync_show_all_models)
        chk.pack(side="left")
        self._track(chk)

        r = row("자막 서명:")
        chk = ttk.Checkbutton(
            r, variable=self.vars["signature"],
            command=self._sync_signature_config)
        self._trw(chk, "chk_signature")
        chk.pack(side="left")
        self._track(chk)
        self.cmb_signature_pos = ttk.Combobox(
            r, values=[self.tr_str("sig_pos_start"), self.tr_str("sig_pos_end")],
            state="readonly", width=10,
            textvariable=self.vars["signature_pos"])
        self.cmb_signature_pos.pack(side="left", padx=4)
        self.cmb_signature_pos.bind("<<ComboboxSelected>>",
                                    lambda e: self._sync_signature_config())
        self._track(self.cmb_signature_pos)
        sig_entry = ttk.Entry(r, textvariable=self.vars["signature_template"])
        sig_entry.pack(side="left", fill="x", expand=True)
        sig_entry.bind("<FocusIn>", lambda e: self._fill_default_signature())
        sig_entry.bind("<KeyRelease>", lambda e: self._sync_signature_config())
        self._track(sig_entry)

        checks1 = (
            ("chk_streaming", "streaming"), ("chk_thinking", "thinking"),
            ("chk_resume", "resume"),
            ("chk_force_retranslate", "force_retranslate"),
        )
        checks2 = (
            ("chk_prefer_sdh", "prefer_sdh"),
            ("chk_strip_periods", "strip_periods"),
            ("chk_isolate_voice", "isolate_voice"),
            ("chk_extract_audio", "extract_audio"),
            ("chk_free", "free"), ("chk_token_stats", "token_stats"),
            ("chk_token_report", "token_report"),
            ("chk_thoughts_log", "thoughts_log"),
            ("chk_progress_log", "progress_log"),
        )
        for group in (checks1, checks2):
            r = ttk.Frame(body)
            r.pack(fill="x", pady=2)
            ttk.Label(r, text="", width=14).pack(side="left")
            for text_key, key in group:
                chk = ttk.Checkbutton(r, variable=self.vars[key])
                self._trw(chk, text_key)
                chk.pack(side="left", padx=(0, 10))
                self._track(chk)
                if key == "strip_periods":
                    chk.configure(command=lambda: set_strip_final_periods(
                        self.vars["strip_periods"].get()))

        r = ttk.Frame(body)
        r.pack(fill="x", pady=2)
        _fhlbl = ttk.Label(r, width=14)
        self._trw(_fhlbl, "lbl_failure_help")
        _fhlbl.pack(side="left")
        chk = ttk.Checkbutton(
            r, variable=self.vars["show_failure_help"],
            command=self._sync_failure_help)
        self._trw(chk, "chk_show_failure_help")
        chk.pack(side="left")
        self._track(chk)

        btn_row = ttk.Frame(dlg)
        btn_row.pack(fill="x", padx=10, pady=8)
        self.btn_adv_close = ttk.Button(
            btn_row, command=self._close_advanced_dialog)
        self._trw(self.btn_adv_close, "btn_close")
        self.btn_adv_close.pack(side="right")

    def open_advanced_settings(self):
        self.advanced_dialog.deiconify()
        self.advanced_dialog.grab_set()

    def _close_advanced_dialog(self):
        try:
            self.advanced_dialog.grab_release()
        except Exception:
            pass
        self.advanced_dialog.withdraw()

    def _sync_show_all_models(self):
        try:
            self.show_all_models = bool(self.vars["show_all_models"].get())
            self.settings.setValue("show_all_models", self.show_all_models)
        except Exception:
            pass

    def _sync_failure_help(self):
        try:
            self.settings.setValue(
                "show_failure_help",
                bool(self.vars["show_failure_help"].get()))
        except Exception:
            pass

    def _failure_help_enabled(self):
        try:
            return bool(self.vars["show_failure_help"].get())
        except Exception:
            return True

    def _all_models_allowed(self):
        try:
            return bool(getattr(self, "show_all_models", False))
        except Exception:
            return False

    def _signature_pos_data(self):
        # 표시 문구는 언어별로 다르므로 양쪽 언어의 '끝' 문구를 모두 인식
        current = self.vars["signature_pos"].get()
        ends = {I18N["ko"]["sig_pos_end"], I18N["en"]["sig_pos_end"]}
        return "end" if current in ends else "start"

    def _sync_signature_config(self):
        try:
            set_signature_config(
                bool(self.vars["signature"].get()),
                self._signature_pos_data(),
                self.vars["signature_template"].get(),
            )
        except Exception:
            pass

    def _fill_default_signature(self):
        if not self.vars["signature_template"].get().strip():
            self.vars["signature_template"].set(DEFAULT_SIGNATURE_TEMPLATE)

    # ------------------------------------------------------------------
    # 실행/로그 그룹
    # ------------------------------------------------------------------
    def _create_action_log_group(self, parent):
        group = ttk.LabelFrame(parent)
        group.pack(fill="both", expand=True, padx=4, pady=4)
        self.action_log_group = group
        self._trw(group, "action_log_group_title")

        row = ttk.Frame(group)
        row.pack(fill="x", padx=6, pady=4)
        self.btn_start = ttk.Button(row, command=self.start_translation)
        self._trw(self.btn_start, "btn_start")
        self.btn_start.pack(side="left")
        if not gst:
            set_enabled(self.btn_start, False)
        self.btn_stop = ttk.Button(row, command=self.stop_translation)
        self._trw(self.btn_stop, "btn_stop")
        self.btn_stop.pack(side="left", padx=4)
        set_enabled(self.btn_stop, False)
        self.progress_bar = ttk.Progressbar(
            row, variable=self.vars["progress"], maximum=100)
        self.progress_bar.pack(side="left", fill="x", expand=True, padx=6)
        ttk.Label(row, textvariable=self.vars["progress_text"]).pack(side="left")

        self.log_output = TerminalLog(group)
        self.log_output.pack(fill="both", expand=True, padx=6, pady=(0, 6))

    def append_log(self, text: str):
        self.log_output.feed_line(text)

    # ------------------------------------------------------------------
    # 언어 전환 (PyQt판 update_ui_language의 주요 항목)
    # ------------------------------------------------------------------
    def _on_app_lang_changed(self, event=None):
        self.app_lang = "ko" if self.vars["app_lang"].get() == "한국어" else "en"
        self.root.title(self.tr_str("app_title"))
        self._set_task_mode_items()
        self._refresh_style_combo()
        self._update_api_keys_summary()
        self._update_ui_language()
        self.cmb_langs.set_placeholder_text(self.tr_str("cmb_langs_ph"))
        if getattr(self, "_custom_lang_ph", None) is not None:
            self._custom_lang_ph.configure(text=self.tr_str("custom_lang_ph"))
        self.save_settings()

    # ------------------------------------------------------------------
    # 모델 체인/우선순위/프리셋
    # ------------------------------------------------------------------
    def _model_chain(self, primary):
        chain = []
        if primary:
            chain.append(primary)
        if not self.vars["model_fallback"].get():
            return chain
        disabled = set(getattr(self, 'model_fallback_disabled', []) or [])
        for m in getattr(self, 'model_fallback_order', []) or []:
            if (m and m not in chain and m not in disabled
                    and (is_text_model(m) or self._all_models_allowed())):
                chain.append(m)
        return chain[:4]

    def _combo_models(self):
        return list(self.cmb_model.cget("values"))

    def open_model_priority_dialog(self):
        ordered = []
        for m in ([self.vars["model"].get()]
                  + list(getattr(self, 'model_fallback_order', []) or [])
                  + self._combo_models()):
            if (m and m not in ordered
                    and (is_text_model(m) or self._all_models_allowed())):
                ordered.append(m)
        dlg = ModelPriorityDialog(
            self.root, ordered, getattr(self, 'model_fallback_disabled', []))
        if dlg.result:
            order, disabled = dlg.result
            if order:
                self.model_fallback_order = order
                self.settings.setValue("model_fallback_order", json.dumps(order))
                self.model_fallback_disabled = disabled
                self.settings.setValue(
                    "model_fallback_disabled", json.dumps(disabled))
                first_enabled = next(
                    (m for m in order if m not in disabled), order[0])
                if first_enabled in self._combo_models():
                    self.vars["model"].set(first_enabled)

    def _load_custom_presets(self):
        data = {}
        for i, pid in enumerate(CUSTOM_PRESET_IDS, 1):
            data[pid] = {
                "name": str(self.settings.value(f"custom_preset_{i}_name", "") or ""),
                "instruction": str(
                    self.settings.value(f"custom_preset_{i}_instruction", "") or ""),
            }
        return data

    def _save_custom_presets(self):
        for i, pid in enumerate(CUSTOM_PRESET_IDS, 1):
            d = (self.custom_presets or {}).get(pid, {})
            self.settings.setValue(f"custom_preset_{i}_name", d.get("name", ""))
            self.settings.setValue(
                f"custom_preset_{i}_instruction", d.get("instruction", ""))

    def open_custom_preset_editor(self):
        dlg = CustomPresetDialog(
            self.root, self.custom_presets, getattr(self, 'app_lang', 'ko'))
        if dlg.result:
            self.custom_presets = dlg.result
            self._save_custom_presets()
            self._refresh_style_combo()

    # ------------------------------------------------------------------
    # 파일 선택/지우기
    # ------------------------------------------------------------------
    def clear_input_files(self):
        self.input_files = []
        self.lst_files.delete(0, "end")

    def clear_video_file(self):
        self.video_file_paths = []
        self.lst_video_files.delete(0, "end")

    def clear_audio_file(self):
        self.audio_file_path = ""
        self._set_audio_label("")

    def select_video_file(self):
        files = filedialog.askopenfilenames(
            parent=self.root, title=self.tr_str("fd_select_video"),
            initialdir=self.settings.value("last_media_dir", self.output_dir),
            filetypes=[("Video Files", "*.mp4 *.mkv *.avi *.mov *.webm *.flv *.wmv"),
                       ("All Files", "*")])
        if files:
            self.video_file_paths = list(files)
            self.lst_video_files.delete(0, "end")
            for f in files:
                self.lst_video_files.insert("end", os.path.basename(f))
            self.settings.setValue("last_media_dir", os.path.dirname(files[0]))

    def select_audio_file(self):
        file_path = filedialog.askopenfilename(
            parent=self.root, title=self.tr_str("fd_select_audio"),
            initialdir=self.settings.value("last_media_dir", self.output_dir),
            filetypes=[("Audio Files", "*.mp3 *.wav *.aac *.m4a *.ogg *.flac *.wma"),
                       ("All Files", "*")])
        if file_path:
            self.audio_file_path = file_path
            self._set_audio_label(file_path)
            self.settings.setValue("last_media_dir", os.path.dirname(file_path))

    def select_input_files(self):
        last_input_dir = self.settings.value("last_input_dir", self.output_dir)
        files = filedialog.askopenfilenames(
            parent=self.root, title=self.tr_str("fd_select_srt"), initialdir=last_input_dir,
            filetypes=[("Subtitle Files", "*.srt *.ass"), ("All Files", "*")])
        if files:
            self.input_files = list(files)
            self.lst_files.delete(0, "end")
            for f in files:
                self.lst_files.insert("end", os.path.basename(f))
            self.settings.setValue("last_input_dir", os.path.dirname(files[0]))

    def select_output_directory(self):
        directory = filedialog.askdirectory(
            parent=self.root, title=self.tr_str("fd_select_out"), initialdir=self.output_dir)
        if directory:
            self.output_dir = directory
            self.vars["out_label"].set(directory)
            self.save_settings()

    def add_custom_language(self):
        name = clean_custom_language_name(self.vars["custom_lang"].get())
        if not name:
            return
        existing = find_language_match(name, self.cmb_langs.all_items())
        if not existing:
            self.cmb_langs.addItem(name)
            existing = name
        checked = self.cmb_langs.checked_items()
        if existing not in checked:
            self.cmb_langs.set_checked_items(checked + [existing])
        self.vars["custom_lang"].set("")
        self.save_settings()

    def select_all_languages(self):
        self.cmb_langs.set_checked_items(self.cmb_langs.all_items())

    def deselect_all_languages(self):
        self.cmb_langs.set_checked_items([])

    # ------------------------------------------------------------------
    # 설정 로드/저장 (키는 PyQt판 QSettings와 동일)
    # ------------------------------------------------------------------
    def load_settings(self):
        try:
            for i in range(NUM_API_KEYS):
                self.api_key_vars[i].set(
                    str(self.settings.value(API_KEY_SETTINGS[i], "") or ""))

            saved_lang = self.settings.value("app_lang", "ko", type=str)
            self.app_lang = saved_lang if saved_lang in I18N else "ko"
            self.vars["app_lang"].set("한국어" if self.app_lang == "ko" else "English")

            last_model = self.settings.value("last_model", DEFAULT_MODEL)
            self.vars["model"].set(str(last_model or DEFAULT_MODEL))

            self.vars["batch"].set(self.settings.value("batch_size", DEFAULT_BATCH_SIZE, type=int))
            self.vars["out_label"].set(self.output_dir)
            task_idx = self.settings.value("task_mode_index", 0, type=int)
            items = [self.tr_str("task_mode_translate"), self.tr_str("task_mode_transcribe")]
            self.vars["task_mode"].set(items[1 if task_idx == 1 else 0])
            self._on_task_mode_changed()
            self.vars["append_lang"].set(self.settings.value("append_lang", True, type=bool))
            self.vars["reuse_extracted"].set(self.settings.value("reuse_extracted", True, type=bool))
            self.vars["keep_extracted"].set(self.settings.value("keep_extracted", False, type=bool))
            self.vars["audio_chunk"].set(self.settings.value("audio_chunk_size", 300, type=int))
            self.vars["isolate_voice"].set(self.settings.value("isolate_voice", True, type=bool))
            self.vars["thinking_level"].set(self.settings.value("thinking_level", "Default", type=str))
            self.txt_desc.insert("1.0", str(self.settings.value("prompt_desc", "", type=str) or ""))

            saved_style = str(self.settings.value("style_preset", "default") or "default")
            if saved_style in getattr(self, "_style_ids", []):
                labels = list(self.cmb_style.cget("values"))
                self.vars["style"].set(labels[self._style_ids.index(saved_style)])

            saved_video_paths_str = str(self.settings.value("video_file_paths", "") or "")
            saved_video_paths = saved_video_paths_str.split('\n') if saved_video_paths_str else []
            self.video_file_paths = [p for p in saved_video_paths if p and os.path.exists(p)]
            self.lst_video_files.delete(0, "end")
            for f in self.video_file_paths:
                self.lst_video_files.insert("end", os.path.basename(f))

            self.audio_file_path = str(self.settings.value("audio_file_path", "") or "")
            if self.audio_file_path and os.path.exists(self.audio_file_path):
                self._set_audio_label(self.audio_file_path)
            else:
                self.audio_file_path = ""
                self._set_audio_label("")

            self.vars["extract_audio"].set(self.settings.value("extract_audio", False, type=bool))
            self.vars["resume"].set(self.settings.value("resume", True, type=bool))
            self.vars["force_retranslate"].set(self.settings.value("force_retranslate", False, type=bool))
            self.vars["prefer_sdh"].set(self.settings.value("prefer_sdh", False, type=bool))
            self.vars["strip_periods"].set(self.settings.value("strip_final_periods", True, type=bool))
            set_strip_final_periods(self.vars["strip_periods"].get())
            self.vars["batch_step_down"].set(self.settings.value("batch_step_down", 0, type=int))
            self.vars["batch_floor"].set(self.settings.value("batch_floor", 100, type=int))
            try:
                saved_order = json.loads(str(self.settings.value("model_fallback_order", "") or ""))
                self.model_fallback_order = (
                    [str(m) for m in saved_order] if isinstance(saved_order, list) else [])
            except (ValueError, TypeError):
                self.model_fallback_order = []
            try:
                saved_disabled = json.loads(str(self.settings.value("model_fallback_disabled", "") or ""))
                self.model_fallback_disabled = (
                    [str(m) for m in saved_disabled] if isinstance(saved_disabled, list) else [])
            except (ValueError, TypeError):
                self.model_fallback_disabled = []
            self.vars["model_fallback"].set(self.settings.value("model_fallback_enabled", True, type=bool))
            self.show_all_models = self.settings.value("show_all_models", False, type=bool)
            self.vars["show_all_models"].set(self.show_all_models)
            self.vars["signature"].set(self.settings.value("signature_enabled", False, type=bool))
            sig_pos = str(self.settings.value("signature_position", "start") or "start")
            self.vars["signature_pos"].set(
                self.tr_str("sig_pos_end") if sig_pos == "end"
                else self.tr_str("sig_pos_start"))
            self.vars["signature_template"].set(str(self.settings.value(
                "signature_template", DEFAULT_SIGNATURE_TEMPLATE) or ""))
            self._sync_signature_config()
            self.vars["token_stats"].set(self.settings.value("token_stats", True, type=bool))
            self.vars["token_report"].set(self.settings.value("token_report", False, type=bool))
            self.vars["show_failure_help"].set(
                self.settings.value("show_failure_help", True, type=bool))

            saved_languages_str = str(self.settings.value("selected_languages", "") or "")
            saved_languages = saved_languages_str.split(',') if saved_languages_str else []
            existing_langs = set(self.cmb_langs.all_items())
            saved_custom_str = str(self.settings.value("custom_languages", "") or "")
            restore_candidates = (
                saved_custom_str.split(',') if saved_custom_str else []
            ) + saved_languages
            for lang in restore_candidates:
                if lang and lang not in existing_langs:
                    self.cmb_langs.addItem(lang)
                    existing_langs.add(lang)
            self.cmb_langs.set_checked_items(saved_languages)

            self.vars["temp"].set(self.settings.value("temperature", 0.9, type=float))
            self.vars["top_p"].set(self.settings.value("top_p", 1.0, type=float))
            self.vars["top_k"].set(self.settings.value("top_k", 0, type=int))
            self.vars["streaming"].set(self.settings.value("streaming", True, type=bool))
            self.vars["thinking"].set(self.settings.value("thinking", True, type=bool))
            self.vars["thinking_budget"].set(self.settings.value("thinking_budget", 2048, type=int))
            self.vars["thoughts_log"].set(self.settings.value("thoughts_log", False, type=bool))
            self.vars["progress_log"].set(self.settings.value("progress_log", False, type=bool))
            self.vars["free"].set(self.settings.value("free_quota", True, type=bool))
            self.vars["resume_context"].set(self.settings.value("resume_context_size", 0, type=int))
            self.vars["batch_error_step"].set(self.settings.value("batch_size_error_step", 100, type=int))
            self.vars["audio_chunk_error_step"].set(self.settings.value("audio_chunk_error_step", 60, type=int))
            self.vars["service_tier"].set(self.settings.value("service_tier", "Default", type=str))
            self.vars["use_enterprise"].set(self.settings.value("use_enterprise", False, type=bool))
            self.vars["cloud_project"].set(self.settings.value("cloud_project", "", type=str))
            self.vars["cloud_api_key"].set(self.settings.value("cloud_api_key", "", type=str))
            self.vars["cloud_location"].set(self.settings.value("cloud_location", "", type=str))
            self.vars["request_type"].set(self.settings.value("request_type", "Default", type=str))
            self._on_enterprise_changed()

            self.root.title(self.tr_str("app_title"))
            self.append_log(f"\x1b[32m{self.tr_str('log_settings_loaded')}\x1b[0m")
        except Exception as e:
            self.append_log(f"\x1b[33m[Warning] Settings load error: {e}\x1b[0m")

    def save_settings(self):
        try:
            for i in range(NUM_API_KEYS):
                self.settings.setValue(API_KEY_SETTINGS[i], self.api_key_vars[i].get())
            if self.vars["model"].get():
                self.settings.setValue("last_model", self.vars["model"].get())
            self.settings.setValue("batch_size", self._get("batch", DEFAULT_BATCH_SIZE))
            self.settings.setValue("output_dir", self.output_dir)
            self.settings.setValue("task_mode_index", self._task_mode_index())
            self.settings.setValue("append_lang", self.vars["append_lang"].get())
            self.settings.setValue("reuse_extracted", self.vars["reuse_extracted"].get())
            self.settings.setValue("keep_extracted", self.vars["keep_extracted"].get())
            self.settings.setValue("audio_chunk_size", self._get("audio_chunk", 300))
            self.settings.setValue("isolate_voice", self.vars["isolate_voice"].get())
            self.settings.setValue("thinking_level", self.vars["thinking_level"].get())
            self.settings.setValue("prompt_desc", self.txt_desc.get("1.0", "end-1c"))
            self.settings.setValue("style_preset", self._current_style_id())
            self._save_custom_presets()

            valid_video_paths = [p for p in self.video_file_paths if p and os.path.exists(p)]
            self.settings.setValue("video_file_paths", '\n'.join(valid_video_paths))
            self.settings.setValue(
                "audio_file_path",
                self.audio_file_path if self.audio_file_path and os.path.exists(self.audio_file_path) else "")
            self.settings.setValue("extract_audio", self.vars["extract_audio"].get())
            self.settings.setValue("resume", self.vars["resume"].get())
            self.settings.setValue("force_retranslate", self.vars["force_retranslate"].get())
            self.settings.setValue("prefer_sdh", self.vars["prefer_sdh"].get())
            self.settings.setValue("strip_final_periods", self.vars["strip_periods"].get())
            self.settings.setValue("batch_step_down", self._get("batch_step_down", 0))
            self.settings.setValue("batch_floor", self._get("batch_floor", 100))
            self.settings.setValue(
                "model_fallback_order", json.dumps(getattr(self, 'model_fallback_order', []) or []))
            self.settings.setValue(
                "model_fallback_disabled", json.dumps(getattr(self, 'model_fallback_disabled', []) or []))
            self.settings.setValue("model_fallback_enabled", self.vars["model_fallback"].get())
            self.settings.setValue("show_all_models", self.vars["show_all_models"].get())
            self.settings.setValue("signature_enabled", self.vars["signature"].get())
            self.settings.setValue("signature_position", self._signature_pos_data())
            self.settings.setValue("signature_template", self.vars["signature_template"].get())
            self.settings.setValue("token_stats", self.vars["token_stats"].get())
            self.settings.setValue("token_report", self.vars["token_report"].get())

            selected_languages = self.cmb_langs.checked_items()
            self.settings.setValue("selected_languages", ','.join(selected_languages))
            custom_languages = [
                lang for lang in self.cmb_langs.all_items()
                if lang not in TARGET_LANGUAGES
            ]
            self.settings.setValue("custom_languages", ','.join(custom_languages))
            self.settings.setValue("temperature", self._get("temp", 0.9))
            self.settings.setValue("top_p", self._get("top_p", 1.0))
            self.settings.setValue("top_k", self._get("top_k", 0))
            self.settings.setValue("streaming", self.vars["streaming"].get())
            self.settings.setValue("thinking", self.vars["thinking"].get())
            self.settings.setValue("thinking_budget", self._get("thinking_budget", 2048))
            self.settings.setValue("thoughts_log", self.vars["thoughts_log"].get())
            self.settings.setValue("progress_log", self.vars["progress_log"].get())
            self.settings.setValue("free_quota", self.vars["free"].get())
            self.settings.setValue("resume_context_size", self._get("resume_context", 0))
            self.settings.setValue("batch_size_error_step", self._get("batch_error_step", 100))
            self.settings.setValue("audio_chunk_error_step", self._get("audio_chunk_error_step", 60))
            self.settings.setValue("service_tier", self.vars["service_tier"].get())
            self.settings.setValue("use_enterprise", self.vars["use_enterprise"].get())
            self.settings.setValue("cloud_project", self.vars["cloud_project"].get())
            self.settings.setValue("cloud_api_key", self.vars["cloud_api_key"].get())
            self.settings.setValue("cloud_location", self.vars["cloud_location"].get())
            self.settings.setValue("app_lang", self.app_lang)
            self.settings.setValue("request_type", self.vars["request_type"].get())
        except Exception:
            pass

    def _on_close(self):
        if self.translation_worker and self.translation_worker.isRunning():
            if not messagebox.askyesno(
                    "종료 확인",
                    "작업이 진행 중입니다. 프로그램을 종료하시겠습니까?\n\n"
                    "(현재 작업은 중단되며, 재개 기능으로 나중에 이어서 할 수 있습니다.)",
                    parent=self.root):
                return
            self.stop_translation()
            self.translation_worker.wait(5000)
        self.save_settings()
        self.root.destroy()

    # ------------------------------------------------------------------
    # 모델 가져오기
    # ------------------------------------------------------------------
    def fetch_models(self):
        if not genai:
            messagebox.showerror("오류", "'google-genai' 필요", parent=self.root)
            return
        api_key = self.api_key_vars[0].get().strip()
        if not api_key:
            messagebox.showwarning("API 키 필요", "기본 API 키(1)가 필요합니다.", parent=self.root)
            return
        if self.model_fetcher_thread and self.model_fetcher_thread.isRunning():
            return

        self.log_output.clear_screen()
        self.append_log("모델 목록 가져오는 중...")
        set_enabled(self.btn_fetch, False)

        self.model_fetcher_thread = ModelFetcherThread(
            api_key=api_key, include_all=self._all_models_allowed())
        self.model_fetcher_thread.bind_dispatch(self._dispatch)
        self.model_fetcher_thread.models_fetched.connect(self.update_model_list)
        self.model_fetcher_thread.error_occurred.connect(self.handle_fetch_error)
        self.model_fetcher_thread.finished.connect(self._on_fetch_finished)
        self.model_fetcher_thread.start()

    def _on_fetch_finished(self):
        set_enabled(self.btn_fetch, True)
        self.model_fetcher_thread = None

    def update_model_list(self, models):
        self.append_log(f"\x1b[32m{self.tr_str('log_models_fetched', count=len(models))}\x1b[0m")
        current_selection = self.vars["model"].get()
        last_saved_model = self.settings.value("last_model", DEFAULT_MODEL)
        self.cmb_model.configure(values=list(models))

        selected_model = DEFAULT_MODEL
        if current_selection in models:
            selected_model = current_selection
        elif last_saved_model in models:
            selected_model = last_saved_model
        elif DEFAULT_MODEL in models:
            selected_model = DEFAULT_MODEL
        elif models:
            selected_model = models[0]

        if selected_model in models:
            self.vars["model"].set(selected_model)
        elif models:
            self.vars["model"].set(models[0])
        else:
            self.cmb_model.configure(values=[DEFAULT_MODEL])
            self.vars["model"].set(DEFAULT_MODEL)
        self.save_settings()

    def handle_fetch_error(self, error_message):
        self.append_log(f"\x1b[31m{self.tr_str('log_models_fetch_err', err=error_message)}\x1b[0m")
        if DEFAULT_MODEL not in self._combo_models():
            self.cmb_model.configure(values=[DEFAULT_MODEL])
        self.vars["model"].set(DEFAULT_MODEL)

    # ------------------------------------------------------------------
    # 작업 생성 (PyQt판과 동일 로직)
    # ------------------------------------------------------------------
    def _create_translation_jobs(self, target_languages, primary_input_source,
                                 is_media_source_only, is_transcribe_mode, media_type=None,
                                 video_context_paths=None):
        jobs = []
        force_retranslate = self.vars["force_retranslate"].get()
        self.skipped_completed_jobs = 0
        if not primary_input_source or not target_languages or not self.output_dir:
            return jobs

        if isinstance(primary_input_source, list):
            source_files_to_process = list(primary_input_source)
        elif isinstance(primary_input_source, str):
            source_files_to_process = [primary_input_source]
        else:
            source_files_to_process = []

        if is_media_source_only:
            source_files_to_process = [
                p for p in source_files_to_process if os.path.exists(p)
            ]
        if not source_files_to_process:
            return jobs

        append_lang = self.vars["append_lang"].get()
        valid_video_contexts = [v for v in (video_context_paths or []) if os.path.exists(v)]

        def _out_stem(p):
            return _output_base_name(p).lower()
        stem_counts = {}
        for p in source_files_to_process:
            stem_counts[_out_stem(p)] = stem_counts.get(_out_stem(p), 0) + 1

        for lang in target_languages:
            for idx, src_file_path in enumerate(source_files_to_process):
                try:
                    base_name = _output_base_name(src_file_path)
                    out_base = base_name
                    if stem_counts.get(base_name.lower(), 0) > 1:
                        out_base = (
                            f"{base_name}_"
                            f"{hashlib.sha1(os.path.abspath(src_file_path).encode('utf-8')).hexdigest()[:8]}"
                        )
                        self.append_log(
                            f"\x1b[33m  ⚠ 동일 파일명 충돌: '{os.path.basename(src_file_path)}' → "
                            f"출력 파일명을 '{out_base}'로 구분합니다\x1b[0m"
                        )
                    tag = "_transcribed" if is_transcribe_mode else ""
                    if append_lang or len(target_languages) > 1:
                        iso_code = _get_iso_lang_code(lang)
                        output_filename = f"{out_base}{tag}.{iso_code}.srt"
                    else:
                        output_filename = f"{out_base}{tag}.srt"
                    output_filepath = os.path.join(self.output_dir, output_filename)

                    job_video_file = None
                    if is_media_source_only and media_type == 'video':
                        job_video_file = src_file_path
                    elif valid_video_contexts:
                        stem = base_name.lower()
                        match = next((v for v in valid_video_contexts if os.path.splitext(os.path.basename(v))[0].lower() == stem), None)
                        if match:
                            job_video_file = match
                        elif len(valid_video_contexts) == len(source_files_to_process):
                            job_video_file = valid_video_contexts[idx]
                        else:
                            job_video_file = valid_video_contexts[0]

                    if not force_retranslate and is_translation_complete(
                        src_file_path, output_filepath, video_file=job_video_file
                    ):
                        self.skipped_completed_jobs += 1
                        self.append_log(
                            f"\x1b[32m  ✔ [스킵] '{os.path.basename(output_filepath)}' "
                            f"이미 번역 완료 → 생략\x1b[0m"
                        )
                        continue

                    jobs.append((src_file_path, lang, output_filepath, is_media_source_only, media_type, job_video_file))
                except Exception:
                    pass
        return jobs

    # ------------------------------------------------------------------
    # 번역 시작 (PyQt판과 동일 흐름)
    # ------------------------------------------------------------------
    def start_translation(self):
        if not gst:
            messagebox.showerror(
                "오류",
                "'gemini-srt-translator' 라이브러리를 불러올 수 없습니다.\n"
                f"{GST_IMPORT_ERROR or ''}", parent=self.root)
            return

        valid_api_keys_from_ui = [
            var.get().strip() for var in self.api_key_vars if var.get().strip()
        ]
        if not valid_api_keys_from_ui:
            messagebox.showwarning("API 키", "API 키를 하나 이상 입력해야 합니다.", parent=self.root)
            return

        reset_library_logger()
        self.log_output.clear_screen()
        logging.getLogger().handlers.clear()
        self._pump()

        set_strip_final_periods(self.vars["strip_periods"].get())
        self._sync_signature_config()

        is_transcribe_mode = self._task_mode_index() == 1
        primary_input_source_for_jobs = None
        source_is_media_only_for_jobs = False
        media_type_for_jobs = None
        self.extracted_temp_files = []

        valid_video_paths = [p for p in self.video_file_paths if os.path.exists(p)]

        selected_languages = self.cmb_langs.checked_items()
        if not selected_languages:
            messagebox.showwarning("언어 선택", "대상 언어를 하나 이상 선택하세요.", parent=self.root)
            return

        if not self.output_dir or not os.path.isdir(self.output_dir):
            try:
                os.makedirs(self.output_dir, exist_ok=True)
            except OSError as e:
                messagebox.showerror(
                    "출력 폴더 오류", f"출력 폴더를 생성할 수 없습니다:\n{e}", parent=self.root)
                return

        if is_transcribe_mode:
            if valid_video_paths:
                primary_input_source_for_jobs = valid_video_paths
                source_is_media_only_for_jobs = True
                media_type_for_jobs = 'video'
            elif self.audio_file_path and os.path.exists(self.audio_file_path):
                primary_input_source_for_jobs = [self.audio_file_path]
                source_is_media_only_for_jobs = True
                media_type_for_jobs = 'audio'
            else:
                messagebox.showwarning(
                    "미디어 필요", "전사(Transcribe)할 대상 비디오/오디오 파일을 선택하세요.",
                    parent=self.root)
                return
        else:
            if self.input_files:
                primary_input_source_for_jobs = self.input_files
            elif valid_video_paths:
                # 영상만 선택된 경우: 내장 자막 트랙 검사/추출 (PyQt판과 동일)
                extracted_sub_files = []
                videos_without_subs = []
                saved_direct_count = 0

                norm_target_langs = {l: _normalize_lang_name(l) for l in selected_languages}
                prefer_sdh = self.vars["prefer_sdh"].get()
                total_vids = len(valid_video_paths)
                _plain_stem_counts = {}
                for _vp in valid_video_paths:
                    _ps = os.path.splitext(os.path.basename(_vp))[0].lower()
                    _plain_stem_counts[_ps] = _plain_stem_counts.get(_ps, 0) + 1

                self.progress_bar.configure(maximum=100)
                self.vars["progress"].set(0)
                self.vars["progress_text"].set("자막 트랙 검사 중... (0%)")
                self._pump()

                for v_idx, vpath in enumerate(valid_video_paths):
                    v_basename = _unique_stem(vpath)
                    plain_stem = os.path.splitext(os.path.basename(vpath))[0]
                    save_stem = (v_basename if _plain_stem_counts.get(
                        plain_stem.lower(), 0) > 1 else plain_stem)
                    self.append_log(f"\x1b[34m[자막 트랙 검사 ({v_idx+1}/{total_vids})] '{os.path.basename(vpath)}' 분석 중...\x1b[0m")
                    self._pump()
                    streams = _get_video_subtitle_streams(vpath)

                    if not streams:
                        self.append_log("\x1b[33m  → 내장 자막 트랙 없음\x1b[0m")
                        videos_without_subs.append(vpath)
                        overall_pct = int(((v_idx + 1) / total_vids) * 100)
                        self.vars["progress"].set(overall_pct)
                        self.vars["progress_text"].set(f"자막 트랙 검사 중... ({v_idx+1}/{total_vids}) ({overall_pct}%)")
                        self._pump()
                        continue

                    def make_progress_cb(video_index, filename):
                        last_update = [0.0]
                        def _cb(pct, curr_sec, total_sec):
                            if pct - last_update[0] >= 1.0 or pct >= 100.0:
                                last_update[0] = pct
                                vid_prog = (video_index + (pct / 100.0)) / total_vids
                                overall_pct = int(min(100.0, max(0.0, vid_prog * 100.0)))
                                self.vars["progress"].set(overall_pct)
                                self.vars["progress_text"].set(f"[{video_index+1}/{total_vids}] 자막 추출 중: {pct:.1f}% ({overall_pct}%)")
                                self._pump()
                        return _cb

                    same_lang_stream, target_matched_lang = \
                        _pick_same_language_stream(streams, norm_target_langs, prefer_sdh)

                    if same_lang_stream:
                        stream_idx = same_lang_stream.get("index", 0)
                        iso_code = _get_iso_lang_code(target_matched_lang)
                        out_direct = os.path.join(self.output_dir, f"{save_stem}.{iso_code}.srt")
                        reuse_extracted = self.vars["reuse_extracted"].get()
                        if reuse_extracted and os.path.exists(out_direct) and os.path.getsize(out_direct) > 0:
                            saved_direct_count += 1
                            self.append_log(
                                f"\x1b[32m  ✔ [재사용] 목표 언어({target_matched_lang}) 자막 '{os.path.basename(out_direct)}' 이미 존재 → 추출 생략\x1b[0m"
                            )
                        else:
                            self.append_log(f"\x1b[36m  → 목표 언어({target_matched_lang}) 트랙 #{stream_idx} 발견!{' [SDH]' if _is_sdh_stream(same_lang_stream) else ''} 추출 중...\x1b[0m")
                            self._pump()
                            cb = make_progress_cb(v_idx, os.path.basename(vpath))
                            if _extract_subtitle_track(vpath, stream_idx, out_direct, progress_callback=cb):
                                saved_direct_count += 1
                                self.append_log(
                                    f"\x1b[32m  ✔ [추출 완료] 번역 불필요: '{os.path.basename(out_direct)}' 저장됨\x1b[0m"
                                )
                            else:
                                self.append_log(
                                    f"\x1b[31m  ✘ [추출 실패] 목표 언어({target_matched_lang}) 자막 추출 실패 → 전사 질의 대상으로 이동\x1b[0m"
                                )
                                videos_without_subs.append(vpath)
                        overall_pct = int(((v_idx + 1) / total_vids) * 100)
                        self.vars["progress"].set(overall_pct)
                        self.vars["progress_text"].set(f"자막 트랙 검사/추출 완료 ({v_idx+1}/{total_vids}) ({overall_pct}%)")
                        self._pump()
                        continue

                    best_stream = _pick_translation_stream(streams, prefer_sdh)
                    stream_idx = best_stream.get("index", 0)
                    temp_srt_path = os.path.join(self.output_dir, f"{v_basename}_extracted.srt")
                    reuse_extracted = self.vars["reuse_extracted"].get()
                    if reuse_extracted and os.path.exists(temp_srt_path) and os.path.getsize(temp_srt_path) > 0:
                        self.append_log(f"\x1b[32m  ✔ [재사용] '{os.path.basename(temp_srt_path)}' 이미 존재 → 재추출 생략\x1b[0m")
                        extracted_sub_files.append((temp_srt_path, vpath))
                    else:
                        self.append_log(f"\x1b[36m  → 자막 트랙 #{stream_idx} 추출 중: '{os.path.basename(temp_srt_path)}'{' [SDH]' if _is_sdh_stream(best_stream) else ''}...\x1b[0m")
                        self._pump()
                        cb = make_progress_cb(v_idx, os.path.basename(vpath))
                        if _extract_subtitle_track(vpath, stream_idx, temp_srt_path, progress_callback=cb):
                            extracted_sub_files.append((temp_srt_path, vpath))
                            self.append_log(
                                f"\x1b[32m  ✔ [추출 완료] '{os.path.basename(temp_srt_path)}' 추출 완료 → 번역 대상으로 등록됨\x1b[0m"
                            )
                        else:
                            videos_without_subs.append(vpath)

                    overall_pct = int(((v_idx + 1) / total_vids) * 100)
                    self.vars["progress"].set(overall_pct)
                    self.vars["progress_text"].set(f"자막 트랙 검사/추출 완료 ({v_idx+1}/{total_vids}) ({overall_pct}%)")
                    self._pump()

                if extracted_sub_files:
                    primary_input_source_for_jobs = [item[0] for item in extracted_sub_files]
                    valid_video_paths = [item[1] for item in extracted_sub_files]
                    self.extracted_temp_files = [item[0] for item in extracted_sub_files]
                    notice = _skipped_videos_notice(videos_without_subs)
                    if notice:
                        self.append_log(f"\x1b[33m{notice}\x1b[0m")
                elif saved_direct_count > 0 and not videos_without_subs:
                    messagebox.showinfo(
                        "완료",
                        f"선택한 영상의 내장 자막({saved_direct_count}개)이 목표 언어와 일치하여 번역 없이 바로 추출/저장되었습니다.",
                        parent=self.root)
                    return
                else:
                    ret = messagebox.askyesno(
                        "오디오 전사(Transcribe) 확인",
                        "선택한 비디오 파일에 추출 가능한 내장 자막 트랙이 없습니다.\n\n"
                        "비디오에서 오디오를 추출하여 [전사(Transcribe)] 방식으로 자막을 생성할까요?",
                        parent=self.root)
                    if ret:
                        items = [self.tr_str("task_mode_translate"), self.tr_str("task_mode_transcribe")]
                        self.vars["task_mode"].set(items[1])
                        is_transcribe_mode = True
                        primary_input_source_for_jobs = videos_without_subs
                        valid_video_paths = videos_without_subs
                        source_is_media_only_for_jobs = True
                        media_type_for_jobs = 'video'
                    else:
                        return
            else:
                messagebox.showwarning(
                    "파일 필요", "번역할 SRT/ASS 자막 파일 또는 비디오 파일을 선택하세요.",
                    parent=self.root)
                return

        selected_model = self.vars["model"].get()
        if not selected_model:
            messagebox.showwarning("모델 선택", "사용할 모델을 선택하세요.", parent=self.root)
            return

        selected_languages = self.cmb_langs.checked_items()
        if not selected_languages:
            messagebox.showwarning("언어 선택", "대상 언어를 하나 이상 선택하세요.", parent=self.root)
            return

        if self.translation_worker and self.translation_worker.isRunning():
            messagebox.showinfo("작업 중", "이미 작업이 진행 중입니다.", parent=self.root)
            return

        self.save_settings()
        jobs = self._create_translation_jobs(
            selected_languages, primary_input_source_for_jobs,
            source_is_media_only_for_jobs, is_transcribe_mode, media_type_for_jobs,
            video_context_paths=valid_video_paths
        )
        skipped_count = getattr(self, 'skipped_completed_jobs', 0)
        if not jobs:
            if skipped_count:
                messagebox.showinfo(
                    "완료",
                    f"선택한 작업 {skipped_count}개가 모두 이미 번역 완료 상태입니다.\n"
                    "새로 실행할 작업이 없습니다.", parent=self.root)
            else:
                messagebox.showwarning("작업 생성 실패", "생성된 작업이 없습니다.", parent=self.root)
            return

        self.job_queue = queue.Queue()
        self.jobs = list(jobs)
        self.total_jobs = len(jobs) + skipped_count
        self.completed_jobs = skipped_count
        self.failed_jobs = 0
        self.last_job_errors = []
        self.recent_outputs = []
        for job in jobs:
            self.job_queue.put(job)

        self.progress_bar.configure(maximum=self.total_jobs)
        self.vars["progress"].set(skipped_count)
        self.vars["progress_text"].set(
            self.tr_str("progress_format", current=skipped_count, total=self.total_jobs))

        service_tier = self.vars["service_tier"].get()
        if service_tier == "Default":
            service_tier = None
        request_type = self.vars["request_type"].get()
        if request_type == "Default":
            request_type = None

        temp_val = self._get("temp", 0.9)
        top_p_val = self._get("top_p", 1.0)
        top_k_val = self._get("top_k", 0)
        start_line_val = self._get("start_line", 1)

        base_config = {
            'task_mode': 'transcribe' if is_transcribe_mode else 'translate',
            'gemini_api_key2': (
                self.api_key_vars[1].get().strip() if len(self.api_key_vars) > 1 else None),
            'start_line': start_line_val if start_line_val > 1 else None,
            'description': compose_description(
                self.txt_desc.get("1.0", "end-1c"),
                self._current_style_id(),
                getattr(self, 'custom_presets', None),
            ),
            'model_name': selected_model,
            'model_chain': self._model_chain(selected_model),
            'batch_size': self._get("batch", DEFAULT_BATCH_SIZE),
            'batch_step_down': self._get("batch_step_down", 0),
            'batch_floor': self._get("batch_floor", 100),
            'free_quota': self.vars["free"].get(),
            'thoughts_log': self.vars["thoughts_log"].get(),
            'temperature': temp_val if temp_val > 0.0 else None,
            'top_p': top_p_val if top_p_val > 0.0 else None,
            'top_k': top_k_val if top_k_val > 0 else None,
            'streaming': self.vars["streaming"].get(),
            'thinking': self.vars["thinking"].get(),
            'thinking_budget': self._get("thinking_budget", 2048),
            'thinking_level': self.vars["thinking_level"].get(),
            'audio_chunk_size': self._get("audio_chunk", 300),
            'isolate_voice': self.vars["isolate_voice"].get(),
            'progress_log': self.vars["progress_log"].get(),
            'video_file': (
                self.video_file_paths[0]
                if self.video_file_paths and os.path.exists(self.video_file_paths[0])
                else None),
            'audio_file': (
                self.audio_file_path
                if self.audio_file_path and os.path.exists(self.audio_file_path)
                else None),
            'extract_audio': self.vars["extract_audio"].get(),
            'token_stats': self.vars["token_stats"].get(),
            'resume': self.vars["resume"].get(),
            'token_report': self.vars["token_report"].get(),
            'context_size': self._get("resume_context", 0),
            'batch_size_error_step': self._get("batch_error_step", 100),
            'audio_chunk_error_step': self._get("audio_chunk_error_step", 60),
            'service_tier': service_tier,
            'use_enterprise': self.vars["use_enterprise"].get(),
            'cloud_project': self.vars["cloud_project"].get().strip() or None,
            'cloud_location': self.vars["cloud_location"].get().strip() or None,
            'cloud_api_key': self.vars["cloud_api_key"].get().strip() or None,
            'request_type': request_type,
        }

        reset_library_logger()
        self.log_output.clear_screen()
        logging.getLogger().handlers.clear()
        self._pump()

        self.set_ui_enabled(False)
        self._stop_requested = False

        self.translation_worker = TranslationWorker(
            valid_api_keys_from_ui, self.job_queue, base_config)
        self.translation_worker.bind_dispatch(self._dispatch)
        self.translation_worker.progress_update.connect(self.log_output.feed)
        self.translation_worker.raw_output_update.connect(self.log_output.feed)
        self.translation_worker.job_translated.connect(self._handle_job_translated)
        self.translation_worker.job_error.connect(self._handle_job_error)
        self.translation_worker.finished_signal.connect(self.translation_finished)
        self.translation_worker.start()

    # ------------------------------------------------------------------
    # 워커 이벤트 핸들러
    # ------------------------------------------------------------------
    def _handle_job_translated(self, output_path, language):
        with self.job_completion_lock:
            self.completed_jobs += 1
            current = self.completed_jobs
            total = self.total_jobs
        src_path = None
        for job in self.jobs:
            if len(job) >= 3 and job[2] == output_path:
                src_path = job[0]
                break
        with self.job_completion_lock:
            self.recent_outputs.append((output_path, src_path))
        self.vars["progress"].set(current)
        self.vars["progress_text"].set(
            self.tr_str("progress_format", current=current, total=total))
        self.append_log(
            f"\x1b[32m{self.tr_str('log_job_success', current=current, total=total, lang=language, file=os.path.basename(output_path))}\x1b[0m")
        cost = read_report_cost(token_report_path_for(output_path))
        if cost:
            total_s = "${:.4f}".format(cost.get('total', 0))
            input_s = "${:.4f}".format(cost.get('input', 0))
            output_s = "${:.4f}".format(cost.get('output', 0))
            self.append_log(
                "\x1b[33m" + self.tr_str(
                    'log_job_cost', total=total_s, input=input_s, output=output_s) + "\x1b[0m")

    def _handle_job_error(self, error_message):
        with self.job_completion_lock:
            self.completed_jobs += 1
            self.failed_jobs = getattr(self, 'failed_jobs', 0) + 1
            self.last_job_errors.append(str(error_message))
            del self.last_job_errors[:-20]
            current = self.completed_jobs
            total = self.total_jobs
        self.vars["progress"].set(current)
        self.vars["progress_text"].set(
            self.tr_str("progress_format_err", current=current, total=total))
        self.append_log(
            f"\x1b[31m{self.tr_str('log_job_fail', current=current, total=total, err=error_message)}\x1b[0m")

    def stop_translation(self):
        if not (self.translation_worker and self.translation_worker.isRunning()):
            return
        self.append_log(f"\x1b[33m{self.tr_str('log_user_stop')}\x1b[0m")
        self._stop_requested = True

        if self.job_queue:
            while not self.job_queue.empty():
                try:
                    self.job_queue.get_nowait()
                    self.job_queue.task_done()
                except queue.Empty:
                    break
                except Exception:
                    pass

        if self.translation_worker:
            self.translation_worker.requestInterruption()

        try:
            from core.gst_patches import force_close_active_client
            force_close_active_client()
        except Exception:
            pass

        set_enabled(self.btn_stop, False)

    def set_ui_enabled(self, enabled):
        for widget in self._toggle_widgets:
            set_enabled(widget, enabled)
        if self._task_mode_index() == 0:
            set_enabled(self.btn_files, enabled)
            set_enabled(self.lst_files, enabled)
        else:
            set_enabled(self.btn_files, False)
            set_enabled(self.lst_files, False)
        set_enabled(self.btn_fetch, enabled if genai else False)
        set_enabled(self.btn_start, enabled if gst else False)
        set_enabled(self.btn_stop, not enabled)

    def translation_finished(self):
        # 이미 정리된 뒤의 중복 호출 방지 (PyQt판의 btn_start 활성 체크와 동일)
        if "disabled" not in self.btn_start.state():
            return

        if self._stop_requested:
            remaining = self.total_jobs - self.completed_jobs
            self.append_log(f"\x1b[33m{self.tr_str('log_interrupted', count=remaining)}\x1b[0m")
        elif self.completed_jobs < self.total_jobs:
            self.append_log(
                f"\x1b[31m{self.tr_str('log_skipped', completed=self.completed_jobs, total=self.total_jobs)}\x1b[0m")
        else:
            self.append_log(f"\x1b[32m{self.tr_str('log_all_done')}\x1b[0m")

        skipped_count = getattr(self, 'skipped_completed_jobs', 0)
        failed_count = getattr(self, 'failed_jobs', 0)
        translated_count = max(0, self.completed_jobs - skipped_count - failed_count)
        summary = f"  요약: 번역 {translated_count}개 · 스킵 {skipped_count}개"
        if failed_count:
            summary += f" · 실패 {failed_count}개"
        self.append_log(summary)

        self._failure_help_pending = 0
        if failed_count and not self._stop_requested:
            try:
                label, advice = failure_advice(getattr(self, 'last_job_errors', []))
                self.append_log(f"\x1b[33m  실패 {failed_count}개 — 원인 추정: {label}\x1b[0m")
                for line in advice:
                    self.append_log(f"\x1b[33m  · {line}\x1b[0m")
                self._failure_help_pending = failed_count
            except Exception:
                pass

        self.vars["progress"].set(self.completed_jobs)
        if self.completed_jobs >= self.total_jobs:
            self.vars["progress_text"].set(self.tr_str("progress_completed"))
        else:
            self.vars["progress_text"].set(self.tr_str(
                "progress_interrupted", current=self.completed_jobs, total=self.total_jobs))

        if (not self.vars["keep_extracted"].get()
                and not self.vars["reuse_extracted"].get()):
            removed = 0
            for p in getattr(self, 'extracted_temp_files', []) or []:
                try:
                    if p and os.path.isfile(p):
                        os.remove(p)
                        removed += 1
                except OSError:
                    pass
            if removed:
                self.append_log(
                    f"\x1b[33m{self.tr_str('log_extracted_cleaned', count=removed)}\x1b[0m")
        self.extracted_temp_files = []

        self.set_ui_enabled(True)

        if self.translation_worker:
            try:
                self.translation_worker.progress_update.disconnect(self.log_output.feed)
                self.translation_worker.raw_output_update.disconnect(self.log_output.feed)
                self.translation_worker.job_translated.disconnect(self._handle_job_translated)
                self.translation_worker.job_error.disconnect(self._handle_job_error)
                self.translation_worker.finished_signal.disconnect(self.translation_finished)
            except Exception:
                pass
            self.translation_worker = None

        self.job_queue = None
        self.total_jobs = 0
        self.completed_jobs = 0
        self.failed_jobs = 0
        self._stop_requested = False

        self._maybe_show_failure_dialog()

    def _maybe_show_failure_dialog(self):
        """종료 정리 뒤 실패 안내창 표시 (고급 설정에서 끌 수 있다).

        안내창은 모달이라 무인 자동화를 막을 수 있다 — 꺼져 있으면
        로그에 남은 원인 추정·조언만으로 충분하므로 건너뛴다.
        """
        pending = getattr(self, '_failure_help_pending', 0)
        self._failure_help_pending = 0
        if pending and self._failure_help_enabled():
            try:
                self._show_failure_dialog(pending)
            except Exception:
                pass

    def _show_failure_dialog(self, failed_count):
        label, advice = failure_advice(getattr(self, 'last_job_errors', []))
        dlg = tk.Toplevel(self.root)
        dlg.title("작업 실패 안내")
        dlg.transient(self.root)
        dlg.grab_set()
        ttk.Label(dlg, text=f"{failed_count}개 작업이 실패했습니다. (원인 추정: {label})",
                  font=("", 10, "bold")).pack(anchor="w", padx=12, pady=(12, 4))
        body = "\n".join(f"• {line}" for line in advice)
        body += "\n\n다시 시도하면 완료된 작업은 건너뛰고 실패한 작업만 이어서 진행됩니다."
        ttk.Label(dlg, text=body, justify="left", wraplength=460).pack(
            anchor="w", padx=12, pady=4)

        models = self._combo_models()
        current = self.vars["model"].get()
        model_candidate = None
        fallback_candidate = None
        for text in models:
            if not text or text == current:
                continue
            if "lite" not in text.lower():
                model_candidate = text
                break
            if fallback_candidate is None:
                fallback_candidate = text
        if model_candidate is None:
            model_candidate = fallback_candidate

        batch_val = self._get("batch", DEFAULT_BATCH_SIZE)

        def close():
            try:
                dlg.grab_release()
            except Exception:
                pass
            dlg.destroy()

        row = ttk.Frame(dlg)
        row.pack(fill="x", padx=12, pady=10)

        def do_retry():
            close()
            self.start_translation()

        def do_model():
            close()
            self.vars["model"].set(model_candidate)
            self.append_log(
                f"\x1b[33m모델을 {model_candidate}로 변경해 다시 시작합니다.\x1b[0m")
            self.start_translation()

        def do_batch():
            close()
            new_size = max(10, batch_val // 2)
            self.vars["batch"].set(new_size)
            self.append_log(
                f"\x1b[33m배치 크기를 {new_size}으로 줄여 다시 시작합니다.\x1b[0m")
            self.start_translation()

        ttk.Button(row, text="닫기", command=close).pack(side="right")
        if batch_val > 10:
            ttk.Button(row, text="배치 크기 절반으로 재시도",
                       command=do_batch).pack(side="right", padx=4)
        if model_candidate:
            ttk.Button(row, text="모델 변경 후 재시도",
                       command=do_model).pack(side="right", padx=4)
        ttk.Button(row, text="다시 시도", command=do_retry).pack(side="right", padx=4)
        dlg.protocol("WM_DELETE_WINDOW", close)

    # ------------------------------------------------------------------
    # 라이브러리 업데이트 확인
    # ------------------------------------------------------------------
    def check_library_update(self):
        if self.update_check_thread and self.update_check_thread.isRunning():
            return
        set_enabled(self.btn_update_check, False)
        self.btn_update_check.configure(text=self.tr_str("btn_update_checking"))
        self.update_check_thread = UpdateCheckThread()
        self.update_check_thread.bind_dispatch(self._dispatch)
        self.update_check_thread.check_done.connect(self._on_update_check_done)
        self.update_check_thread.error_occurred.connect(self._on_update_check_error)
        self.update_check_thread.finished.connect(self._on_update_check_finished)
        self.update_check_thread.start()

    def _on_update_check_done(self, installed, latest):
        from core.update_check import is_newer, PACKAGE_NAME
        if not latest:
            messagebox.showwarning(self.tr_str("update_title"),
                                   self.tr_str("update_check_failed"), parent=self.root)
        elif is_newer(latest, installed):
            messagebox.showinfo(
                self.tr_str("update_title"),
                self.tr_str("update_available", installed=installed or "?",
                            latest=latest, package=PACKAGE_NAME), parent=self.root)
        else:
            messagebox.showinfo(self.tr_str("update_title"),
                                self.tr_str("update_latest", installed=installed or "?"),
                                parent=self.root)

    def _on_update_check_error(self, msg):
        messagebox.showwarning(self.tr_str("update_title"), msg, parent=self.root)

    def _on_update_check_finished(self):
        set_enabled(self.btn_update_check, True)
        self.btn_update_check.configure(text=self.tr_str("btn_update_check"))
        self.update_check_thread = None

    # ------------------------------------------------------------------
    # 드래그&드롭 수신
    # ------------------------------------------------------------------
    def _on_drop_input_files(self, paths):
        added = []
        for p in paths:
            if (os.path.isfile(p) and p.lower().endswith((".srt", ".ass"))
                    and p not in self.input_files):
                self.input_files.append(p)
                self.lst_files.insert("end", os.path.basename(p))
                added.append(p)
        if added:
            self.settings.setValue("last_input_dir", os.path.dirname(added[0]))

    def _on_drop_video_files(self, paths):
        video_exts = (".mp4", ".mkv", ".avi", ".mov", ".webm", ".flv", ".wmv")
        added = []
        for p in paths:
            if (os.path.isfile(p) and p.lower().endswith(video_exts)
                    and p not in self.video_file_paths):
                self.video_file_paths.append(p)
                self.lst_video_files.insert("end", os.path.basename(p))
                added.append(p)
        if added:
            self.settings.setValue("last_media_dir", os.path.dirname(added[0]))

    # ------------------------------------------------------------------
    # 2단계 다이얼로그 (미리보기/자막 도구/스킬 설치/에이전트 교환)
    # ------------------------------------------------------------------
    def _pick_from_list(self, title, label, items):
        """단일 선택 목록 다이얼로그 (QInputDialog.getItem 대체)."""
        dlg = tk.Toplevel(self.root)
        dlg.title(title)
        dlg.transient(self.root)
        dlg.grab_set()
        ttk.Label(dlg, text=label).pack(anchor="w", padx=10, pady=(10, 4))
        lb = tk.Listbox(dlg, width=56, height=min(12, len(items)),
                        **LISTBOX_STYLE)
        lb.pack(fill="both", expand=True, padx=10)
        for item in items:
            lb.insert("end", item)
        lb.selection_set(0)
        result = {"index": None}

        def ok():
            sel = lb.curselection()
            result["index"] = sel[0] if sel else None
            dlg.destroy()

        row = ttk.Frame(dlg)
        row.pack(fill="x", padx=10, pady=8)
        ttk.Button(row, text="취소", command=dlg.destroy).pack(side="right")
        ttk.Button(row, text="확인", command=ok).pack(side="right", padx=(0, 6))
        lb.bind("<Double-Button-1>", lambda e: ok())
        dlg.wait_window()
        return result["index"]

    def open_preview_editor(self):
        from app_tk.dialogs2 import SubtitlePreviewDialogTk

        translated, original = None, None
        if self.recent_outputs:
            if len(self.recent_outputs) == 1:
                translated, original = self.recent_outputs[0]
            else:
                items = [os.path.basename(p) for p, _ in self.recent_outputs]
                idx = self._pick_from_list(
                    self.tr_str("preview_title"),
                    self.tr_str("preview_choose_file"), items)
                if idx is None:
                    return
                translated, original = self.recent_outputs[idx]
        else:
            path = filedialog.askopenfilename(
                parent=self.root, title=self.tr_str("preview_open_translated"),
                initialdir=self.output_dir,
                filetypes=[("Subtitles", "*.srt"), ("All Files", "*")])
            if not path:
                return
            translated = path
        # 원본이 자막 파일이 아니면 대조 표시 안 함 (PyQt판과 동일)
        if original and not original.lower().endswith((".srt", ".ass")):
            original = None
        SubtitlePreviewDialogTk(self.root, self, translated, original)

    def open_subtitle_tools(self):
        from app_tk.dialogs2 import SubtitleToolsDialogTk
        SubtitleToolsDialogTk(self.root, self)

    def open_skill_installer(self):
        from app_tk.dialogs2 import SkillInstallDialogTk
        SkillInstallDialogTk(self.root, self)

    def open_agent_exchange(self):
        from app_tk.dialogs2 import AgentExchangeDialogTk
        AgentExchangeDialogTk(self.root, self)
