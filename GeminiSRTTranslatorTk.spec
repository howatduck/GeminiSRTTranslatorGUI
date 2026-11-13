# -*- coding: utf-8 -*-
"""Tkinter판 PyInstaller 스펙 (GeminiSRTTranslator.spec의 미러).

진입점 main_tk.py, 산출물 GeminiSRTTranslatorTk.exe (onefile).
PyQt6를 제외해 가볍게 만들고, 레트로 아이콘(app_tk.ico)을 쓴다.
공유 에셋·FFmpeg·ilass 번들 방식은 Qt판 스펙과 동일하다.
"""

import os
import sys
from PyInstaller.building.build_main import Analysis, PYZ, EXE
from PyInstaller.utils.hooks import collect_all, collect_submodules, collect_data_files

block_cipher = None

datas = []
binaries = []

# 앱 에셋 (아이콘 등) 번들 포함
if os.path.isdir('assets'):
    datas.append(('assets', 'assets'))

# FFmpeg 바이너리 번들 포함 (ffmpeg.exe, ffprobe.exe)
for f_exe in ['ffmpeg.exe', 'ffprobe.exe']:
    if os.path.exists(f_exe):
        binaries.append((f_exe, '.'))

# ilass 바이너리 번들 포함 (자막 싱크용, get_ilass.py로 다운로드)
if os.path.exists('ilass.exe'):
    binaries.append(('ilass.exe', '.'))

hiddenimports = [
    'google.genai',
    'google.genai.types',
    'gemini_srt_translator',
    'pyte',
    'pysubs2',
    'json_repair',
    'tkinter',
    'tkinter.ttk',
    'tkinter.filedialog',
    'tkinter.messagebox',
    'tkinter.font',
    'email',
    'email.mime',
    'email.mime.text',
    'http.client',
    'xml.etree',
    'certifi',
    'html',
    'html.parser',
    'html.entities',
]

# collect submodules, data & binaries for key packages
# collect_all() returns 3-tuples (src, dest, typecode) internally;
# Analysis expects 2-tuples (src, dest), so we strip the typecode.
def _to_2tuple(items):
    result = []
    for item in items:
        if isinstance(item, (list, tuple)) and len(item) >= 2:
            result.append((item[0], item[1]))
    return result

for pkg in ['google.genai', 'gemini_srt_translator', 'pyte', 'pysubs2',
            'json_repair', 'pydantic', 'httpx', 'certifi', 'tkinterdnd2']:
    try:
        tmp_datas, tmp_hidden, tmp_binaries = collect_all(pkg)
        datas.extend(_to_2tuple(tmp_datas))
        hiddenimports.extend(tmp_hidden)
        binaries.extend(_to_2tuple(tmp_binaries))
    except Exception:
        pass

hiddenimports = list(set(hiddenimports))

a = Analysis(
    ['main_tk.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'PyQt6',
        'matplotlib',
        'numpy',
        'pandas',
        'scipy',
        'unittest',
        'pydoc',
        'lib2to3',
    ],

    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# Windows 파일 버전 리소스: Qt판과 같은 version_info.txt 공유
_version_file = 'version_info.txt' if os.path.exists('version_info.txt') else None

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='GeminiSRTTranslatorTk',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='assets/app_tk.ico',
    version=_version_file,
)
