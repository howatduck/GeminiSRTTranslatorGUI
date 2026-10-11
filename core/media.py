# -*- coding: utf-8 -*-
"""ffprobe/ffmpeg 기반 미디어·자막 헬퍼."""

import os
import sys


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
                cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
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
