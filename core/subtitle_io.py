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


# =====================================================================
# 줄 끝 마침표 제거 (자막 문장부호 정책)
#
# 번역 모델은 원문 문장의 마침표를 그대로 복사해 오는 경향이 있는데,
# 한국어 자막 관행상 대사 줄 끝 마침표는 번역체로 읽힌다. 저장 시점에
# 결정적으로 제거해 모델·모드와 무관하게 일관된 결과를 만든다.
# =====================================================================
_strip_final_periods = True


def set_strip_final_periods(enabled):
    """줄 끝 마침표 제거 정책 on/off (앱 설정이 동기화한다)."""
    global _strip_final_periods
    _strip_final_periods = bool(enabled)


def strip_final_periods_enabled():
    return _strip_final_periods


# 마침표 뒤에 올 수 있는 닫는 기호들 (따옴표·괄호 등)
_CLOSING_SUFFIX_CHARS = "\"'”’」』)]}"
_TRAILING_CLOSING_TAG_RE = re.compile(r"((?:</[^>]+>)+)$")
_DOTTED_ABBREV_RE = re.compile(r"(?:[A-Za-z]\.)*[A-Za-z]")


def _strip_line_final_period(line):
    s = line.rstrip()
    if not s:
        return s
    tags = ""
    m = _TRAILING_CLOSING_TAG_RE.search(s)
    if m:
        tags = m.group(1)
        s = s[:m.start()]
    suffix = ""
    while s and s[-1] in _CLOSING_SUFFIX_CHARS:
        suffix = s[-1] + suffix
        s = s[:-1]
    if not s or s[-1] not in ".。":
        return s + suffix + tags
    if s.endswith(".."):
        # 말줄임표(.., ...)는 의도된 표기라 유지
        return s + suffix + tags
    core = s[:-1]
    if not core:
        return s + suffix + tags
    if core[-1].isdigit():
        # "3." "2.5."처럼 숫자의 일부일 수 있어 유지
        return s + suffix + tags
    token = core.rsplit(None, 1)[-1]
    if "." in token and _DOTTED_ABBREV_RE.fullmatch(token):
        # "U.S" 같은 약어의 마지막 마침표는 약어의 일부라 유지
        return s + suffix + tags
    return core + suffix + tags


def strip_final_periods(text):
    """자막 텍스트의 각 줄 끝 마침표(.·。)를 제거한다.

    물음표·느낌표·말줄임표, 줄 내부 마침표, 숫자 뒤 마침표, 약어의
    마침표는 유지한다.
    """
    if not text:
        return text
    return "\n".join(_strip_line_final_period(l) for l in text.split("\n"))


# =====================================================================
# 번역자 서명 삽입
#
# 저장 시점에 자막 첫머리/꼬리에 서명 큐를 넣는다. 사용자는 템플릿에
# 자기 서명을 직접 쓰고, {model}(실제로 번역한 모델)·{date}(번역 날짜)
# 자리표시자만 앱이 채운다. 모델명은 워커가 시도마다 알려준다 —
# 폴백으로 모델이 바뀌어도 성공한 모델이 기록된다.
# =====================================================================
_signature_config = {"enabled": False, "position": "start", "template": ""}
_signature_model = ""

# 서명 칸의 기본 문구 — 처음 쓰는 사용자가 고쳐 쓰기 쉽도록 미리 채워 둔다
DEFAULT_SIGNATURE_TEMPLATE = "번역 : GeminiSRTTranslator GUI · {model} · {date}"


def set_signature_config(enabled, position, template):
    """서명 정책 동기화 (앱 설정이 호출)."""
    _signature_config["enabled"] = bool(enabled)
    _signature_config["position"] = "end" if position == "end" else "start"
    _signature_config["template"] = str(template or "")


def signature_config():
    return dict(_signature_config)


def set_signature_model(model):
    """이 저장을 만든 모델명 (워커가 시도 직전에 호출)."""
    global _signature_model
    _signature_model = str(model or "")


def render_signature(model=None, today=None):
    """서명 문구 렌더링. 비활성·빈 템플릿이면 빈 문자열."""
    if not _signature_config["enabled"]:
        return ""
    template = _signature_config["template"].strip()
    if not template:
        return ""
    import datetime

    date_str = today or datetime.date.today().isoformat()
    model_name = _signature_model if model is None else str(model or "")
    return template.replace("{model}", model_name).replace("{date}", date_str)


def _cue_times_ms(block):
    """번호 포함 SRT 블록 문자열 -> (start_ms, end_ms) | None."""
    lines = block.split("\n")
    if len(lines) < 2:
        return None
    m = TIMESTAMP_RE.search(lines[1])
    if not m:
        return None
    g = [int(x) for x in m.groups()]
    start = ((g[0] * 60 + g[1]) * 60 + g[2]) * 1000 + g[3]
    end = ((g[4] * 60 + g[5]) * 60 + g[6]) * 1000 + g[7]
    return start, end


def insert_signature_cues(cues, text, position="start"):
    """번호가 매겨진 SRT 블록 목록에 서명 큐를 넣고 번호를 다시 매긴다.

    cues: gst_patches가 만든 "번호\\n시간 --> 시간\\n본문\\n" 블록 목록.
    시작 위치: 첫 큐 앞 0초부터 최대 3초 (첫 큐가 먼저 시작하면 그
    시작까지만). 끝 위치: 마지막 큐 종료부터 3초.
    """
    if not cues or not text:
        return cues
    times = [_cue_times_ms(c) for c in cues]
    if any(t is None for t in times):
        return cues
    if position == "end":
        start_ms = times[-1][1]
        end_ms = start_ms + 3000
        sig = f"0\n{ms_to_timestamp(start_ms)} --> {ms_to_timestamp(end_ms)}\n{text}\n"
        merged = list(cues) + [sig]
    else:
        first_start, first_end = times[0]
        if first_start > 0:
            end_ms = min(3000, first_start)
        else:
            end_ms = min(3000, first_end)
        if end_ms <= 0:
            return cues
        sig = f"0\n{ms_to_timestamp(0)} --> {ms_to_timestamp(end_ms)}\n{text}\n"
        merged = [sig] + list(cues)
    renumbered = []
    for i, block in enumerate(merged, start=1):
        _old, sep, rest = block.partition("\n")
        renumbered.append(f"{i}{sep}{rest}" if sep else f"{i}\n{block}")
    return renumbered


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
