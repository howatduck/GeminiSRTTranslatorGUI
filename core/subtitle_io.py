# -*- coding: utf-8 -*-
"""자막 파일 입출력 (미리보기 에디터용 순수 함수).

SRT 파싱/생성을 담당한다. GUI 의존성 없음.
"""

import os
import re

# 시 단위는 1자리(0:01:23,456)나 100시간 이상(100:00:00,000) 변종도
# 받아들인다. 분·초는 2자리 고수. ms_to_timestamp는 이미 {h:02d}로
# 100시간 이상을 최소 너비로 출력하므로 왕복이 깨지지 않는다.
TIMESTAMP_RE = re.compile(
    r"(\d+):(\d{2}):(\d{2})[,.](\d{3})\s*-->\s*"
    r"(\d+):(\d{2}):(\d{2})[,.](\d{3})"
)


def timestamp_to_ms(ts):
    """'00:00:01,000' -> 밀리초(int). 실패 시 None."""
    m = re.match(r"(\d+):(\d{2}):(\d{2})[,.](\d{3})", (ts or "").strip())
    if not m:
        return None
    h, mi, s, ms = (int(g) for g in m.groups())
    return ((h * 60 + mi) * 60 + s) * 1000 + ms


def ms_to_timestamp(ms):
    """밀리초(int) -> '00:00:01,000'."""
    ms = max(0, int(ms))
    h, rem = divmod(ms, 3600000)
    mi, rem = divmod(rem, 60000)
    s, ms = divmod(rem, 1000)
    return f"{h:02d}:{mi:02d}:{s:02d},{ms:03d}"


def parse_srt(text):
    """SRT 텍스트 -> 자막 entry 리스트.

    entry: {"index": int, "start": str, "end": str,
            "start_ms": int|None, "end_ms": int|None, "text": str}
    깨진 블록은 건너뛴다.
    """
    entries = []
    if not text:
        return entries
    # \r\n, \r 정규화 후 빈 줄 기준 블록 분리
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    blocks = re.split(r"\n\s*\n", normalized.strip())
    for block in blocks:
        lines = block.strip().split("\n")
        if len(lines) < 2:
            continue
        # 첫 줄이 숫자 인덱스면 제거
        if lines[0].strip().isdigit():
            lines = lines[1:]
            if not lines:
                continue
        m = TIMESTAMP_RE.search(lines[0])
        if not m:
            continue
        start = f"{m.group(1)}:{m.group(2)}:{m.group(3)},{m.group(4)}"
        end = f"{m.group(5)}:{m.group(6)}:{m.group(7)},{m.group(8)}"
        entries.append({
            "index": len(entries) + 1,
            "start": start,
            "end": end,
            "start_ms": timestamp_to_ms(start),
            "end_ms": timestamp_to_ms(end),
            "text": "\n".join(lines[1:]).strip(),
        })
    return entries


def format_srt(entries):
    """자막 entry 리스트 -> SRT 텍스트."""
    blocks = []
    for i, e in enumerate(entries, 1):
        start = e.get("start") or ms_to_timestamp(e.get("start_ms") or 0)
        end = e.get("end") or ms_to_timestamp(e.get("end_ms") or 0)
        blocks.append(f"{i}\n{start} --> {end}\n{e.get('text', '').strip()}")
    return "\n\n".join(blocks) + ("\n" if blocks else "")


def entry_cps(entry):
    """초당 글자수 (공백 제외). duration이 없으면 None."""
    s, e = entry.get("start_ms"), entry.get("end_ms")
    if s is None or e is None or e <= s:
        return None
    chars = len(re.sub(r"\s", "", entry.get("text", "")))
    return chars / ((e - s) / 1000.0)


def progress_file_for(input_file, video_file=None):
    """라이브러리(gemini-srt-translator)가 쓰는 .progress 파일 경로.

    라이브러리와 동일 규칙으로 도출한다: 기준 파일은 video_file 우선
    (없으면 input_file), stem 끝의 '_extracted'는 제거하고, 위치는
    기준 파일이 있는 폴더. 기준 파일이 없으면 None.
    """
    base_file = video_file or input_file
    if not base_file:
        return None
    base_name = os.path.splitext(os.path.basename(base_file))[0]
    if base_name.endswith("_extracted"):
        base_name = base_name[:-len("_extracted")]
    dir_path = os.path.dirname(base_file)
    if dir_path:
        return os.path.join(dir_path, f"{base_name}.progress")
    return f"{base_name}.progress"


def is_translation_complete(input_file, output_file, video_file=None):
    """번역 완료 판정: 출력 파일이 있고 비어 있지 않으며 .progress가 없고,
    출력이 SRT로 파싱되어 큐가 1개 이상일 때만 True.

    주의: 라이브러리는 배치마다 최종 출력 경로에 부분 결과를 원자적으로
    쓰므로(미번역 줄은 원문으로 채워짐) 출력 파일의 존재만으로는 완료를
    판정할 수 없다. 중단된 작업은 입력 쪽 .progress 파일이 남아 있는
    것으로 구분한다. 입력과 출력이 같은 파일(제자리 번역)이면 완료로
    보지 않는다.
    """
    if not input_file or not output_file:
        return False
    if os.path.abspath(input_file) == os.path.abspath(output_file):
        return False
    try:
        if not os.path.isfile(output_file) or os.path.getsize(output_file) <= 0:
            return False
    except OSError:
        return False
    progress = progress_file_for(input_file, video_file)
    if progress is None:
        return False
    if os.path.exists(progress):
        return False
    # 패치 이전에 만들어진 출력(에러 페이지 저장 등)까지 걸러내기 위해
    # 출력이 실제로 SRT로 파싱되어 큐가 1개 이상인지 확인한다.
    try:
        with open(output_file, "rb") as f:
            text = f.read().decode("utf-8-sig", errors="replace")
    except OSError:
        return False
    return len(parse_srt(text)) > 0
