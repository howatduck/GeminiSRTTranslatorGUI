# -*- coding: utf-8 -*-
"""자막 파일 입출력 (미리보기 에디터용 순수 함수).

SRT 파싱/생성을 담당한다. GUI 의존성 없음.
"""

import re

TIMESTAMP_RE = re.compile(
    r"(\d{2}):(\d{2}):(\d{2})[,.](\d{3})\s*-->\s*"
    r"(\d{2}):(\d{2}):(\d{2})[,.](\d{3})"
)


def timestamp_to_ms(ts):
    """'00:00:01,000' -> 밀리초(int). 실패 시 None."""
    m = re.match(r"(\d{2}):(\d{2}):(\d{2})[,.](\d{3})", (ts or "").strip())
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
