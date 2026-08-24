# -*- mode: python ; coding: utf-8 -*-
import sys
from PyInstaller.building.build_main import Analysis, PYZ, EXE
from PyInstaller.utils.hooks import collect_all, collect_submodules, collect_data_files

block_cipher = None

datas = []
binaries = []
hiddenimports = [
    'google.genai',
    'google.genai.types',
    'gemini_srt_translator',
    'pyte',
    'pysubs2',
    'json_repair',
    'PyQt6.sip',
    'PyQt6.QtCore',
    'PyQt6.QtGui',
    'PyQt6.QtWidgets',
    'email',
    'email.mime',
    'email.mime.text',
    'http.client',
    'xml.etree',
    'certifi',
]

# collect submodules, data & binaries for key packages
for pkg in ['google.genai', 'gemini_srt_translator', 'pyte', 'pysubs2',
            'json_repair', 'pydantic', 'httpx', 'certifi']:
    try:
        tmp_datas, tmp_hidden, tmp_binaries = collect_all(pkg)
        datas.extend(tmp_datas)
        hiddenimports.extend(tmp_hidden)
        binaries.extend(tmp_binaries)
    except Exception:
        pass

hiddenimports = list(set(hiddenimports))

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'matplotlib',
        'numpy',
        'pandas',
        'scipy',
        'tkinter',
        'unittest',
        'pydoc',
        'html',
        'lib2to3',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='GeminiSRTTranslator',
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
    icon=None,
)

