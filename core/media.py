# -*- coding: utf-8 -*-
"""ffprobe/ffmpeg 기반 미디어·자막 헬퍼."""

import os
import re
import sys

from core.languages import _normalize_lang_name

_SDH_TITLE_RE = re.compile(
    r"(?<![a-z0-9])sdh(?![a-z0-9])"
    r"|hearing[ -]impaired"
    r"|closed captions?"
    r"|(?<![a-z0-9])cc(?![a-z0-9])",
    re.IGNORECASE,
)


# =====================================================================
# [미디어/자막 헬퍼 함수] FFprobe 및 FFmpeg를 통한 자막 트랙 검사 및 추출
# =====================================================================
def _get_video_subtitle_streams(video_path: str) -> list:
    """ffprobe를 통해 비디오 파일 내의 모든 자막 스트림 정보 반환"""
    import subprocess, json
    cmd = [
        "ffprobe", "-v", "error",
        "-select_streams", "s",
        "-show_entries", "stream=index,codec_name,disposition:stream_tags=language,title",
        "-of", "json",
        video_path
    ]
    try:
        startupinfo = None
        if sys.platform == "win32":
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        res = subprocess.run(
            cmd, capture_output=True, text=True, check=True,
            encoding="utf-8", errors="replace", startupinfo=startupinfo
        )
        data = json.loads(res.stdout)
        return data.get("streams", [])
    except Exception:
        return []

def _stream_language(stream) -> str:
    """스트림의 정규화된 언어명 (language 태그, 없거나 und면 title로 판별)."""
    tags = stream.get("tags", {}) or {}
    lang = (tags.get("language", "") or "").strip()
    if not lang or lang.lower() == "und":
        return _normalize_lang_name(tags.get("title", "") or "")
    return _normalize_lang_name(lang)


def _is_forced_stream(stream) -> bool:
    """forced(강제) 자막 여부: disposition 플래그 또는 title 표기."""
    disp = stream.get("disposition", {}) or {}
    if disp.get("forced", 0) == 1:
        return True
    title = (stream.get("tags", {}) or {}).get("title", "") or ""
    return "forced" in title.lower()


def _is_sdh_stream(stream) -> bool:
    """SDH(청각장애인용) 자막 여부: disposition hearing_impaired 플래그
    또는 title의 SDH/CC/hearing impaired 표기 (단어 경계 기준)."""
    disp = stream.get("disposition", {}) or {}
    if disp.get("hearing_impaired", 0) == 1:
        return True
    title = (stream.get("tags", {}) or {}).get("title", "") or ""
    return bool(_SDH_TITLE_RE.search(title))


def _pick_translation_stream(streams, prefer_sdh=False):
    """번역용 자막 트랙 선택.

    우선순위는 (영어 우선 → forced 후순위 → SDH 정책) 사전식 순서이며,
    동급이면 원래 스트림 순서를 유지한다. SDH 트랙이 없으면 기존 동작과
    동일하다. prefer_sdh=True면 같은 등급에서 SDH를 일반 자막보다 먼저
    고른다. streams가 비어 있으면 None.
    """
    if not streams:
        return None

    def key(s):
        sdh_rank = 0 if (_is_sdh_stream(s) == prefer_sdh) else 1
        return (
            0 if _stream_language(s) == "english" else 1,
            1 if _is_forced_stream(s) else 0,
            sdh_rank,
        )

    return min(streams, key=key)


def _pick_same_language_stream(streams, norm_target_langs, prefer_sdh=False):
    """목표 언어와 일치하는 트랙 중 하나를 선택.

    우선순위: 목표 언어 목록의 순서 → forced 후순위 → SDH 정책.
    forced는 일부 대사만 담긴 부분 자막이라 SDH보다도 뒤로 민다.
    norm_target_langs: {원본 언어명: 정규화된 이름} (순서 유지).
    반환: (stream, 매칭된 원본 언어명) 또는 (None, None).
    """
    lang_rank = {orig: i for i, orig in enumerate(norm_target_langs)}
    matches = []
    for s in streams:
        s_lang = _stream_language(s)
        if not s_lang:
            continue
        for orig_l, norm_l in norm_target_langs.items():
            if norm_l and s_lang == norm_l:
                matches.append((s, orig_l))
                break
    if not matches:
        return None, None

    def key(match):
        s, orig_l = match
        sdh_rank = 0 if (_is_sdh_stream(s) == prefer_sdh) else 1
        return (
            lang_rank[orig_l],
            1 if _is_forced_stream(s) else 0,
            sdh_rank,
        )

    return min(matches, key=key)


def _get_media_duration(file_path: str) -> float:
    """ffprobe를 통해 미디어 파일의 총 재생 시간(초) 반환"""
    import subprocess
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        file_path
    ]
    try:
        startupinfo = None
        if sys.platform == "win32":
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        res = subprocess.run(
            cmd, capture_output=True, text=True, check=True,
            encoding="utf-8", errors="replace", startupinfo=startupinfo
        )
        return float(res.stdout.strip())
    except Exception:
        return 0.0

def _extract_subtitle_track(video_path: str, stream_index: int, output_srt_path: str, progress_callback=None) -> bool:
    """ffmpeg를 사용하여 지정된 자막 스트림을 .srt 파일로 추출 (실시간 진행률 콜백 지원)"""
    import subprocess
    total_duration = _get_media_duration(video_path) if progress_callback else 0.0

    out_dir = os.path.dirname(os.path.abspath(output_srt_path))
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    cmd = [
        "ffmpeg", "-y", "-v", "error",
        "-i", video_path,
        "-map", f"0:{stream_index}",
        "-c:s", "srt",
    ]
    if progress_callback:
        cmd.extend(["-progress", "pipe:1", "-nostats"])
    cmd.append(output_srt_path)

    try:
        startupinfo = None
        if sys.platform == "win32":
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

        if progress_callback:
            process = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                text=True, encoding="utf-8", errors="replace", startupinfo=startupinfo
            )
            for line in process.stdout:
                line = line.strip()
                if line.startswith("out_time_us="):
                    try:
                        us = int(line.split("=", 1)[1])
                        curr_sec = us / 1_000_000.0
                        if total_duration > 0:
                            pct = min(100.0, max(0.0, (curr_sec / total_duration) * 100.0))
                            progress_callback(pct, curr_sec, total_duration)
                    except (ValueError, TypeError):
                        pass
                elif line.startswith("progress="):
                    val = line.split("=", 1)[1]
                    if val == "end" and total_duration > 0:
                        progress_callback(100.0, total_duration, total_duration)
            process.wait()
            return process.returncode == 0 and os.path.exists(output_srt_path) and os.path.getsize(output_srt_path) > 0
        else:
            subprocess.run(
                cmd, capture_output=True, text=True, check=True,
                encoding="utf-8", errors="replace", startupinfo=startupinfo
            )
            return os.path.exists(output_srt_path) and os.path.getsize(output_srt_path) > 0
    except Exception:
        return False
