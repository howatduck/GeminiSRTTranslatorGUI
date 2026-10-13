# -*- coding: utf-8 -*-
"""자막 정리 도구 (리네임 + ilass 싱크) 라이브러리.

kracc 서버의 subs_toolkit.py를 GUI용으로 라이브러리화한 것이다.
원본과 달리 아래 제약을 지킨다:
  - os.chdir() 사용 금지 (절대 경로만 사용)
  - sys.stdout 하이재킹 금지 (log 콜백 사용)
  - sys.exit() 금지 (SubtitleToolsError 예외 발생)
"""

import datetime
import json
import os
import re
import shutil
import subprocess
import sys

# ============================================================
# 상수
# ============================================================

VIDEO_EXTS = {".mkv", ".mp4", ".avi", ".m2ts", ".ts"}
SUB_EXTS = {".srt", ".ass", ".smi", ".sub", ".vtt"}
SUB_EXT_PRIORITY = [".srt", ".ass", ".smi", ".sub", ".vtt"]

EPISODE_PATTERNS = [
    re.compile(r"[Ss](\d{1,2})[.\-_ ]?[Ee](\d{1,3})"),
    re.compile(r"(?<!\d)(\d{1,2})[xX](\d{1,3})(?!\d)"),
]
LANG_SUFFIX_PATTERN = re.compile(r"\.([a-zA-Z]{2,3}(?:[-.][a-zA-Z]+)?)$")
YEAR_PATTERN = re.compile(r"(19\d{2}|20\d{2})")

ILASS_NATIVE_SUB_EXTS = {".srt", ".ass", ".ssa"}
CONVERTIBLE_TO_SRT_EXTS = {".vtt", ".smi", ".sub"}

LANG_NAMES = {
    "eng": ["english"],
    "kor": ["korean"],
    "jpn": ["japanese"],
    "fre": ["french"], "fra": ["french"],
    "ger": ["german"], "deu": ["german"],
    "spa": ["spanish"],
    "chi": ["chinese"], "zho": ["chinese"],
}
LANG_2LETTER = {
    "eng": "en", "kor": "ko", "fre": "fr", "fra": "fr",
    "ger": "de", "deu": "de", "spa": "es", "jpn": "ja",
    "chi": "zh", "zho": "zh",
}
SYNC_LANG_CHOICES = ["eng", "kor", "jpn", "fre", "ger", "spa", "chi"]

TEXT_SUBTITLE_CODECS = {
    "subrip", "srt", "ass", "ssa", "webvtt", "mov_text", "text",
    "microdvd", "mpl2", "jacosub", "sami",
}
IMAGE_SUBTITLE_CODECS = {
    "hdmv_pgs_subtitle", "pgssub", "dvd_subtitle", "dvdsub",
    "dvb_subtitle", "xsub",
}

TIMECODE_RE = re.compile(
    r"(\d{1,2}:\d{2}:\d{2}[.,]\d{1,3})\s*-->\s*(\d{1,2}:\d{2}:\d{2}[.,]\d{1,3})"
)

# ilass GitHub 릴리즈 (번들용)
ILASS_HOMEPAGE = "https://github.com/SandroHc/ilass"
ILASS_LICENSE = "AGPL-3.0"


class SubtitleToolsError(Exception):
    """자막 도구 실행 오류."""


# ============================================================
# 실행 파일 탐색
# ============================================================

def _bundled_dir():
    """PyInstaller 번들 내부 디렉토리 (동결 시) 또는 exe所在 디렉토리."""
    if getattr(sys, "frozen", False):
        base = getattr(sys, "_MEIPASS", None)
        if base:
            return base
        return os.path.dirname(sys.executable)
    return None


def find_ilass():
    """ilass 실행 파일 경로 탐색. 없으면 None.

    탐색 순서: PyInstaller 번들 내부 -> exe所在 디렉토리 -> PATH
    """
    candidates = []
    bdir = _bundled_dir()
    if bdir:
        candidates.append(os.path.join(bdir, "ilass.exe"))
        candidates.append(os.path.join(bdir, "ilass"))
    # 개발 환경: 프로젝트 루트
    here = os.path.dirname(os.path.abspath(__file__))
    candidates.append(os.path.join(os.path.dirname(here), "ilass.exe"))
    for c in candidates:
        if c and os.path.isfile(c):
            return c
    return shutil.which("ilass")


def find_ffmpeg():
    bdir = _bundled_dir()
    if bdir:
        for name in ("ffmpeg.exe", "ffmpeg"):
            c = os.path.join(bdir, name)
            if os.path.isfile(c):
                return c
    return shutil.which("ffmpeg")


def find_ffprobe():
    bdir = _bundled_dir()
    if bdir:
        for name in ("ffprobe.exe", "ffprobe"):
            c = os.path.join(bdir, name)
            if os.path.isfile(c):
                return c
    return shutil.which("ffprobe")


# ============================================================
# 1) 리네임
# ============================================================

def get_episode_key(filename):
    """파일명에서 (시즌, 에피소드) 튜플 추출. 못 찾으면 None."""
    stem = os.path.splitext(filename)[0]
    for pattern in EPISODE_PATTERNS:
        m = pattern.search(stem)
        if m:
            season, episode = m.groups()
            return (int(season), int(episode))
    return None


def get_year_key(filename):
    """파일명에서 연도 추출. 못 찾으면 None."""
    stem = os.path.splitext(filename)[0]
    m = YEAR_PATTERN.search(stem)
    return m.group(1) if m else None


def split_lang_suffix(sub_filename):
    """자막 파일명에서 언어 접미사와 확장자 분리.

    예: 'movie.en.srt' -> ('.en', '.srt'), 'movie.srt' -> ('', '.srt')
    """
    stem, ext = os.path.splitext(sub_filename)
    m = LANG_SUFFIX_PATTERN.search(stem)
    if m:
        lang_part = m.group(1)
        if 2 <= len(lang_part.split("-")[0].split(".")[0]) <= 3:
            return f".{lang_part}", ext
    return "", ext


def scan_and_match(folder, mode="tv", max_files=50000):
    """폴더를 재귀 스캔하며 (영상, 자막) 매칭 목록 생성.

    반환: (plan, unmatched)
      plan: [(old_path, new_path), ...]  (절대 경로)
      unmatched: [sub_path, ...]  (매칭 실패)

    max_files: 스캔 중 파일 수가 이를 넘으면 SubtitleToolsError 발생.
      (홈 디렉토리 같은 대용량 트리를 실수로 스캔하는 것 방지)
    """
    folder = os.path.abspath(folder)
    plan = []
    unmatched = []

    seen = 0
    for root, _dirs, files in os.walk(folder):
        seen += len(files)
        if seen > max_files:
            raise SubtitleToolsError(
                f"파일이 너무 많습니다 ({max_files}개 초과). "
                f"시즌 폴더처럼 작은 단위의 폴더를 직접 선택하세요: {folder}"
            )
        videos = [f for f in files if os.path.splitext(f)[1].lower() in VIDEO_EXTS]
        subs = [f for f in files if os.path.splitext(f)[1].lower() in SUB_EXTS]

        if not videos or not subs:
            continue

        video_keys = []
        for v in videos:
            key = get_episode_key(v) if mode == "tv" else get_year_key(v)
            if key is not None:
                video_keys.append((key, v))

        for sub in subs:
            sub_key = get_episode_key(sub) if mode == "tv" else get_year_key(sub)
            matched_video = None

            if sub_key is not None:
                for key, v in video_keys:
                    if key == sub_key:
                        matched_video = v
                        break

            if matched_video is None and len(videos) == 1:
                matched_video = videos[0]

            if matched_video is None:
                unmatched.append(os.path.join(root, sub))
                continue

            video_base = os.path.splitext(matched_video)[0]
            lang_suffix, sub_ext = split_lang_suffix(sub)
            new_sub_name = f"{video_base}{lang_suffix}{sub_ext}"

            old_path = os.path.join(root, sub)
            new_path = os.path.join(root, new_sub_name)

            if old_path == new_path:
                continue

            plan.append((old_path, new_path))

    return plan, unmatched


def plan_rename(folder, mode="tv"):
    """리네임 계획만 생성 (미리보기용). 부작용 없음."""
    if not os.path.isdir(folder):
        raise SubtitleToolsError(f"폴더를 찾을 수 없습니다: {folder}")
    return scan_and_match(folder, mode)


def apply_rename(plan, log=None):
    """리네임 계획 적용. 반환: (적용 수, 건너뜀 수)."""
    log = log or (lambda msg: None)
    applied = 0
    skipped = 0
    for old_path, new_path in plan:
        if os.path.exists(new_path):
            log(f"[건너뜀 - 대상 이미 존재] {os.path.basename(old_path)}")
            skipped += 1
            continue
        os.rename(old_path, new_path)
        log(f"[리네임] {os.path.basename(old_path)} -> {os.path.basename(new_path)}")
        applied += 1
    return applied, skipped


# ============================================================
# 2) 싱크
# ============================================================

def _norm_timecode(tc):
    tc = tc.replace(".", ",")
    h, m, rest = tc.split(":")
    s, ms = rest.split(",")
    ms = (ms + "000")[:3]
    return f"{int(h):02d}:{m}:{s},{ms}"


def sanitize_srt(path):
    """SRT 정규화. 반환: 블록 수."""
    with open(path, encoding="utf-8", errors="replace") as f:
        raw_lines = f.read().splitlines()

    blocks = []
    cur_time = None
    cur_text = []

    for line in raw_lines:
        m = TIMECODE_RE.search(line)
        if m:
            if cur_time is not None:
                blocks.append((cur_time, cur_text))
            cur_time = (_norm_timecode(m.group(1)), _norm_timecode(m.group(2)))
            cur_text = []
            continue

        stripped = line.strip()
        if cur_time is None:
            continue
        if stripped == "":
            continue
        if cur_text == [] and stripped.isdigit():
            continue  # 시퀀스 번호 줄은 건너뜀
        cur_text.append(line.rstrip())

    if cur_time is not None:
        blocks.append((cur_time, cur_text))

    with open(path, "w", encoding="utf-8") as f:
        for i, (t, text) in enumerate(blocks, 1):
            f.write(f"{i}\n{t[0]} --> {t[1]}\n")
            f.write("\n".join(text))
            f.write("\n\n")

    return len(blocks)


def convert_to_srt(src_path, out_srt, ffmpeg=None):
    ffmpeg = ffmpeg or find_ffmpeg()
    if not ffmpeg:
        raise SubtitleToolsError("ffmpeg를 찾을 수 없습니다.")
    try:
        subprocess.run(
            [ffmpeg, "-y", "-loglevel", "error", "-nostdin",
             "-i", src_path, out_srt],
            check=True,
        )
    except subprocess.CalledProcessError:
        return False

    if not (os.path.isfile(out_srt) and os.path.getsize(out_srt) > 0):
        return False

    return sanitize_srt(out_srt) > 0


def detect_sub_stream(video_path, lang_code, ffprobe=None):
    ffprobe = ffprobe or find_ffprobe()
    if not ffprobe:
        raise SubtitleToolsError("ffprobe를 찾을 수 없습니다.")
    try:
        out = subprocess.run(
            [ffprobe, "-v", "error",
             "-select_streams", "s",
             "-show_entries", "stream=index,codec_name:stream_tags=language,title",
             "-of", "json",
             video_path],
            capture_output=True, text=True, check=True,
        ).stdout
        data = json.loads(out)
    except Exception:
        return None, None

    streams = data.get("streams", [])
    candidates = []
    for i, s in enumerate(streams):
        tags = s.get("tags", {}) or {}
        lang = (tags.get("language") or "").lower()
        title = (tags.get("title") or "").lower()
        codec = (s.get("codec_name") or "").lower()
        candidates.append((i, lang, title, codec))

    lang_code = lang_code.lower()
    two_letter = LANG_2LETTER.get(lang_code, "")
    name_variants = LANG_NAMES.get(lang_code, [])

    def lang_match(lang):
        return lang == lang_code or (two_letter and lang == two_letter)

    def title_match(title):
        return any(name in title for name in name_variants)

    def pick(pred):
        for i, lang, title, codec in candidates:
            if pred(lang, title):
                return i, codec
        return None, None

    idx, codec = pick(lambda l, t: lang_match(l) and "forced" not in t)
    if idx is None:
        idx, codec = pick(lambda l, t: lang_match(l))
    if idx is None:
        idx, codec = pick(lambda l, t: title_match(t) and "forced" not in t)
    if idx is None:
        idx, codec = pick(lambda l, t: title_match(t))
    return idx, codec


def extract_sub_stream(video_path, stream_spec, out_srt, ffmpeg=None):
    ffmpeg = ffmpeg or find_ffmpeg()
    if not ffmpeg:
        raise SubtitleToolsError("ffmpeg를 찾을 수 없습니다.")
    try:
        subprocess.run(
            [ffmpeg, "-y", "-loglevel", "error", "-nostdin",
             "-i", video_path, "-map", stream_spec, out_srt],
            check=True,
        )
    except subprocess.CalledProcessError:
        return False

    if not (os.path.isfile(out_srt) and os.path.getsize(out_srt) > 0):
        return False

    return sanitize_srt(out_srt) > 0


def resolve_reference(video_path, lang_code, forced_stream, work_dir,
                      ffmpeg=None, ffprobe=None):
    """싱크 레퍼런스 결정. 반환: (ref_path, 설명, is_temp).

    ref_path가 None이면 레퍼런스 생성 실패.
    """
    if forced_stream:
        tmp_ref = os.path.join(work_dir, "._ilass_ref.srt")
        if extract_sub_stream(video_path, forced_stream, tmp_ref, ffmpeg):
            return tmp_ref, f"강제 지정 스트림({forced_stream})에서 추출한 자막", True
        return None, f"강제 지정 스트림({forced_stream}) 추출 실패", False

    sub_idx, codec = detect_sub_stream(video_path, lang_code, ffprobe)

    if sub_idx is not None and codec in TEXT_SUBTITLE_CODECS:
        stream_spec = f"0:s:{sub_idx}"
        tmp_ref = os.path.join(work_dir, "._ilass_ref.srt")
        if extract_sub_stream(video_path, stream_spec, tmp_ref, ffmpeg):
            return tmp_ref, f"텍스트 자막 트랙({stream_spec}, codec={codec})에서 추출", True
        return video_path, f"자막 추출/정규화 실패({stream_spec}), 영상 오디오로 폴백", False

    if sub_idx is not None and codec in IMAGE_SUBTITLE_CODECS:
        return video_path, f"이미지 자막(codec={codec})이라 영상 오디오로 정렬", False

    if sub_idx is not None:
        stream_spec = f"0:s:{sub_idx}"
        tmp_ref = os.path.join(work_dir, "._ilass_ref.srt")
        if extract_sub_stream(video_path, stream_spec, tmp_ref, ffmpeg):
            return tmp_ref, f"알 수 없는 자막 코덱({codec}), 텍스트로 추출 시도", True
        return video_path, f"알 수 없는 자막 코덱({codec}) 추출 실패, 영상 오디오로 폴백", False

    return video_path, "내장 자막 없음 -> 영상 오디오로 정렬", False


def run_ilass(ref_path, sub_path, out_path, ilass=None,
              split_penalty=None, no_split=False, log=None):
    """ilass 실행. 반환: (출력 텍스트, 종료 코드)."""
    ilass = ilass or find_ilass()
    if not ilass:
        raise SubtitleToolsError(
            f"ilass가 설치되어 있지 않습니다. {ILASS_HOMEPAGE} 참고 "
            "(또는 앱에 내장된 ilass 사용)"
        )
    log = log or (lambda msg: None)

    cmd = [ilass, ref_path, sub_path, out_path]
    if no_split:
        cmd.append("--no-split")
    elif split_penalty is not None:
        cmd += ["--split-penalty", str(split_penalty)]

    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, bufsize=1,
    )
    chunks = []
    for line in proc.stdout:
        chunks.append(line)
        log(line.rstrip("\n"))
    proc.wait()
    return "".join(chunks), proc.returncode


def find_pairs(target_dir):
    """폴더에서 (영상, 자막) 쌍 탐색. 반환: (pairs, skipped_no_sub)."""
    target_dir = os.path.abspath(target_dir)
    entries = os.listdir(target_dir)
    entries_lower_map = {}
    for e in entries:
        entries_lower_map.setdefault(e.lower(), e)

    videos = []
    for e in entries:
        base, ext = os.path.splitext(e)
        if ext.lower() in VIDEO_EXTS:
            videos.append(e)
    videos.sort()

    pairs = []
    skipped_no_sub = []
    for video in videos:
        base, _ = os.path.splitext(video)
        found_sub = None
        found_ext = None
        for sext in SUB_EXT_PRIORITY:
            candidate = base + sext
            actual = entries_lower_map.get(candidate.lower())
            if actual and os.path.isfile(os.path.join(target_dir, actual)):
                found_sub = actual
                found_ext = sext
                break
        if found_sub:
            pairs.append((video, found_sub, found_ext))
        else:
            skipped_no_sub.append(video)

    return pairs, skipped_no_sub


def already_synced(target_dir, base, sub):
    """이 자막이 이미 싱크됐는지 판단 (.bak 존재 여부)."""
    target_dir = os.path.abspath(target_dir)
    final_sub_path = os.path.join(target_dir, base + ".srt")
    candidates = [
        final_sub_path + ".bak",
        os.path.join(target_dir, sub) + ".bak",
    ]
    return any(os.path.exists(p) for p in candidates)


def run_sync(target_dir, lang="eng", stream=None, split_penalty=None,
             no_split=False, no_backup=False, no_log=False,
             force_resync=False, log=None, progress=None,
             ilass=None, ffmpeg=None, ffprobe=None, work_dir=None):
    """ilass 싱크 실행. 반환: 결과 요약 dict.

    log: 로그 콜백(msg), progress: 진행 콜백(done, total)
    """
    log = log or (lambda msg: None)
    progress = progress or (lambda done, total: None)

    target_dir = os.path.abspath(target_dir)
    if not os.path.isdir(target_dir):
        raise SubtitleToolsError(f"폴더를 찾을 수 없습니다: {target_dir}")

    ilass = ilass or find_ilass()
    if not ilass:
        raise SubtitleToolsError(
            f"ilass를 찾을 수 없습니다. {ILASS_HOMEPAGE}에서 설치하거나 "
            "앱에 내장된 ilass를 사용하세요."
        )
    ffmpeg = ffmpeg or find_ffmpeg()
    ffprobe = ffprobe or find_ffprobe()
    if not ffmpeg or not ffprobe:
        raise SubtitleToolsError("ffmpeg/ffprobe를 찾을 수 없습니다.")

    work_dir = work_dir or target_dir

    log_path = None
    log_file = None
    if not no_log:
        log_name = ("sync_subs_ilass_"
                    f"{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.log")
        log_path = os.path.join(target_dir, log_name)
        log_file = open(log_path, "a", encoding="utf-8", errors="replace")
        log(f"[로그] 전체 로그 저장: {log_path}")

    def _log(msg):
        log(msg)
        if log_file:
            log_file.write(msg + "\n")
            log_file.flush()

    try:
        return _run_sync_impl(
            target_dir, lang=lang, stream=stream,
            split_penalty=split_penalty, no_split=no_split,
            no_backup=no_backup, force_resync=force_resync,
            log=_log, progress=progress,
            ilass=ilass, ffmpeg=ffmpeg, ffprobe=ffprobe,
            work_dir=work_dir,
        )
    finally:
        if log_file:
            log_file.close()


def _run_sync_impl(target_dir, lang, stream, split_penalty, no_split,
                   no_backup, force_resync, log, progress,
                   ilass, ffmpeg, ffprobe, work_dir):
    _log = log
    _log("=============================================")
    _log(f"=== ilass 자막 싱크 시작: {target_dir} ===")
    if stream:
        _log(f"레퍼런스: 스트림 {stream} 강제 추출 (모든 파일에 동일 적용)")
    else:
        _log(f"레퍼런스: 자동 감지 (언어={lang}, 텍스트 자막 우선 / 없으면 영상 오디오)")
    if force_resync:
        _log("이미 .bak이 있는 파일도 --force-resync로 강제 재처리합니다.")
    else:
        _log("이미 .bak이 존재하는 파일 = 이미 싱크 완료로 간주하고 건너뜁니다.")

    pairs, skipped_no_sub = find_pairs(target_dir)

    total = 0
    ok = 0
    fail = 0
    skip = 0
    already = 0
    results = []

    # 진행률용 전체 쌍 수 (미리 계산 불가 항목 제외하고 근사)
    grand_total = len(pairs) + len(skipped_no_sub)
    done = 0

    for video, sub, ext in pairs:
        base, _ = os.path.splitext(video)

        if not force_resync and already_synced(target_dir, base, sub):
            _log(f"[건너뜀 - 이미 싱크됨] {base} (.bak 존재)")
            already += 1
            done += 1
            progress(done, grand_total)
            continue

        total += 1
        _log(f"[처리 중] {base} ({ext.lstrip('.')})")

        ext_lower = ext.lower()
        sub_for_ilass = os.path.join(target_dir, sub)
        converted_input = None

        if ext_lower not in ILASS_NATIVE_SUB_EXTS:
            if ext_lower in CONVERTIBLE_TO_SRT_EXTS:
                converted_input = os.path.join(work_dir, "._ilass_input.srt")
                if convert_to_srt(sub_for_ilass, converted_input, ffmpeg):
                    _log(f"  [변환] {sub} -> 임시 .srt 변환/정규화 완료")
                    sub_for_ilass = converted_input
                else:
                    _log(f"  [경고] {sub} -> .srt 변환 실패라 건너뜁니다")
                    if converted_input and os.path.exists(converted_input):
                        os.remove(converted_input)
                    skip += 1
                    done += 1
                    progress(done, grand_total)
                    continue
            else:
                _log(f"  [경고] ilass 미지원 포맷({ext})이라 건너뜁니다.")
                skip += 1
                done += 1
                progress(done, grand_total)
                continue

        ref_path, reason, is_temp_ref = resolve_reference(
            os.path.join(target_dir, video), lang, stream, work_dir,
            ffmpeg=ffmpeg, ffprobe=ffprobe,
        )
        if ref_path is None:
            _log(f"  [경고] 레퍼런스 생성 실패로 건너뜁니다: {video} ({reason})")
            if converted_input and os.path.exists(converted_input):
                os.remove(converted_input)
            skip += 1
            done += 1
            progress(done, grand_total)
            continue
        _log(f"  [레퍼런스] {reason}")

        final_sub_path = os.path.join(target_dir, base + ".srt")

        if not no_backup:
            bak_source = final_sub_path if os.path.exists(final_sub_path) else sub_for_ilass
            bak_path = bak_source + ".bak"
            if os.path.exists(bak_source) and not os.path.exists(bak_path):
                shutil.copy2(bak_source, bak_path)
                _log(f"  [백업] {os.path.basename(bak_path)}")

        tmp_out = os.path.join(work_dir, base + ".synced.srt")

        _output, status = run_ilass(
            ref_path, sub_for_ilass, tmp_out, ilass=ilass,
            split_penalty=split_penalty, no_split=no_split, log=_log,
        )

        if is_temp_ref and os.path.exists(ref_path):
            os.remove(ref_path)
        if converted_input and os.path.exists(converted_input):
            os.remove(converted_input)

        if status == 0 and os.path.isfile(tmp_out):
            shutil.move(tmp_out, final_sub_path)
            note = "" if ext_lower == ".srt" else f" (원본 {ext} 유지)"
            _log(f"  [완료] {os.path.basename(final_sub_path)} 싱크 완료{note}")
            ok += 1
            results.append({"base": base, "status": "ok", "ref": reason})
        else:
            _log(f"  [실패] ilass 실행 실패: {base}")
            if os.path.exists(tmp_out):
                os.remove(tmp_out)
            fail += 1
            results.append({"base": base, "status": "fail", "ref": reason})

        done += 1
        progress(done, grand_total)

    for video in skipped_no_sub:
        _log(f"[건너뜀] 매칭 자막 없음: {video}")
        skip += 1
        done += 1
        progress(done, grand_total)

    _log("=============================================")
    _log(f"총 처리: {total} | 성공: {ok} | 실패: {fail} | "
         f"건너뜀: {skip} | 이미 싱크됨: {already}")

    return {
        "total": total, "ok": ok, "fail": fail,
        "skip": skip, "already": already, "results": results,
    }
