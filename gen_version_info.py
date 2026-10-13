# -*- coding: utf-8 -*-
"""PyInstaller용 Windows 버전 리소스(version_info.txt) 생성기.

사용법:
    python gen_version_info.py [버전] [-o 출력경로]

    버전 예: v1.2, 1.2.3 (앞의 'v'는 무시, 숫자 4자리로 패딩)
    버전을 생략하면 `git describe --tags`에서 가져오고,
    그것도 없으면 0.0.0.0 (개발 빌드 표시)으로 생성한다.
"""

import re
import subprocess
import sys


def parse_version(raw):
    """'v1.2' -> (1, 2, 0, 0). 파싱 실패 시 (0, 0, 0, 0)."""
    s = (raw or "").strip()
    if s.lower().startswith("v"):
        s = s[1:]
    parts = []
    for p in s.split("."):
        m = re.match(r"(\d+)", p)
        if not m:
            return (0, 0, 0, 0)
        parts.append(int(m.group(1)))
    while len(parts) < 4:
        parts.append(0)
    return tuple(parts[:4])


def version_from_git():
    try:
        out = subprocess.run(
            ["git", "describe", "--tags", "--abbrev=0"],
            capture_output=True, text=True, timeout=10,
        )
        if out.returncode == 0:
            return out.stdout.strip()
    except Exception:
        pass
    return None


def render(ver_tuple, display):
    major, minor, patch, build = ver_tuple
    dotted = f"{major}.{minor}.{patch}.{build}"
    return f"""# UTF-8
#
# PyInstaller 버전 리소스 (gen_version_info.py 자동 생성)
#
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=({major}, {minor}, {patch}, {build}),
    prodvers=({major}, {minor}, {patch}, {build}),
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo(
      [
        StringTable(
          '040904B0',
          [StringStruct('CompanyName', 'howatduck'),
           StringStruct('FileDescription', 'Gemini SRT Translator GUI'),
           StringStruct('FileVersion', '{dotted}'),
           StringStruct('InternalName', 'GeminiSRTTranslator'),
           StringStruct('LegalCopyright', 'Copyright (c) howatduck'),
           StringStruct('OriginalFilename', 'GeminiSRTTranslator.exe'),
           StringStruct('ProductName', 'Gemini SRT Translator GUI'),
           StringStruct('ProductVersion', '{dotted}')])
      ]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"""


def main(argv):
    out_path = "version_info.txt"
    ver_arg = None
    args = list(argv)
    if "-o" in args:
        i = args.index("-o")
        out_path = args[i + 1]
        del args[i:i + 2]
    if args:
        ver_arg = args[0]
    if not ver_arg:
        ver_arg = version_from_git() or "0.0.0.0"

    ver_tuple = parse_version(ver_arg)
    display = ver_arg.strip()
    if display.lower().startswith("v"):
        display = display[1:]

    with open(out_path, "w", encoding="utf-8") as f:
        f.write(render(ver_tuple, display))
    print(f"version_info.txt 생성: {display} -> "
          f"{'.'.join(map(str, ver_tuple))}")


if __name__ == "__main__":
    main(sys.argv[1:])
