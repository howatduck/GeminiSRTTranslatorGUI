# -*- coding: utf-8 -*-
"""에이전트 파일 교환 모드 (ChatGPT 웹 등 로컬 파일 접근이 없는 AI용).

라이브러리 SubtitleSession의 배치 프로토콜을 파일로 주고받는다.
내보내기는 현재 배치를 batch_NNN.json과 안내문(instructions.md)으로
교환 폴더에 쓰고, 가져오기는 번역된 JSON을 세션에 커밋한 뒤 다음
배치 파일을 쓴다. 진행 상태·검증·출력 조립은 전부 라이브러리 세션이
담당하므로, 에이전트 스킬(gst agent CLI)과 같은 세션을 공유한다.

교환 폴더: 입력 파일 옆의 "<파일명>_agent_exchange/".
"""

import json
import os

try:
    from core.gst_compat import SubtitleSession
except Exception:  # gst_compat 자체가 없을 일은 없지만 방어적으로
    SubtitleSession = None

DEFAULT_BATCH_SIZE = 50


def _require_session():
    if SubtitleSession is None:
        raise RuntimeError(
            "gemini-srt-translator 라이브러리에서 SubtitleSession을 찾을 수 "
            "없습니다. 라이브러리 설치를 확인하세요."
        )


def exchange_dir_for(input_file):
    """입력 파일에 대응하는 교환 폴더 경로."""
    directory = os.path.dirname(os.path.abspath(input_file))
    stem = os.path.splitext(os.path.basename(input_file))[0]
    return os.path.join(directory, f"{stem}_agent_exchange")


def _batch_filename(batch_number):
    return f"batch_{int(batch_number):03d}.json"


def _new_session(input_file, target_language=None, batch_size=None,
                 description=None):
    _require_session()
    kwargs = {"input_file": input_file, "resume": True}
    if target_language:
        kwargs["target_language"] = target_language
    if batch_size:
        kwargs["batch_size"] = batch_size
    if description:
        kwargs["description"] = description
    return SubtitleSession(**kwargs)


def _write_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _write_instructions(path, target_language, system_prompt,
                        style_instruction=""):
    lines = [
        "# 자막 번역 파일 교환 안내",
        "",
        f"대상 언어: {target_language}",
        "",
        "## 진행 방법",
        "",
        "1. 함께 있는 batch_NNN.json 파일의 각 항목에서 `text`만 대상 언어로 "
        "번역하세요. `index` 값과 항목 수는 원본과 똑같이 유지하세요.",
        "2. 번역한 JSON 배열을 파일로 저장해 프로그램의 [번역본 가져오기]로 "
        "넣으세요.",
        "3. 다음 배치가 있으면 새 batch 파일이 생깁니다. 완료될 때까지 "
        "반복하세요.",
        "",
    ]
    if style_instruction:
        lines += ["## 추가 스타일 지침", "", style_instruction, ""]
    if system_prompt:
        lines += ["## 번역 규칙 (라이브러리 제공)", "", system_prompt, ""]
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def _write_batch(session, exchange_dir, target_language, style_instruction,
                 include_prompt):
    """현재 배치를 교환 폴더에 쓰고 결과 dict를 반환. 배치 없으면 None."""
    payload = session.get_next_batch(include_system_prompt=include_prompt)
    if not payload:
        return None
    status = session.get_status()
    batch_file = os.path.join(
        exchange_dir, _batch_filename(status.get("batch_number", 1)))
    _write_json(batch_file, payload.get("batch") or [])
    result = {
        "state": "ready",
        "batch_file": batch_file,
        "status": status,
    }
    instructions = os.path.join(exchange_dir, "instructions.md")
    if include_prompt or not os.path.isfile(instructions):
        _write_instructions(
            instructions, target_language,
            payload.get("system_prompt", ""), style_instruction)
        result["instructions_file"] = instructions
    return result


def start_exchange(input_file, target_language, batch_size=DEFAULT_BATCH_SIZE,
                   style_instruction=""):
    """교환 시작(또는 이어하기): 현재 배치를 파일로 내보낸다.

    반환 dict: state("ready"|"completed"), batch_file, instructions_file,
    status, output_file(완료 시).
    """
    if not input_file or not os.path.isfile(input_file):
        raise RuntimeError(f"입력 파일이 없습니다: {input_file}")
    description = style_instruction or None
    session = _new_session(input_file, target_language=target_language,
                           batch_size=batch_size, description=description)
    if session.is_complete():
        return {"state": "completed", "output_file": session.output_file,
                "status": session.get_status()}
    exchange_dir = exchange_dir_for(input_file)
    os.makedirs(exchange_dir, exist_ok=True)
    result = _write_batch(session, exchange_dir, target_language,
                          style_instruction, include_prompt=True)
    if result is None:
        return {"state": "completed", "output_file": session.output_file,
                "status": session.get_status()}
    return result


def commit_exchange(input_file, translated_file,
                    batch_size=DEFAULT_BATCH_SIZE):
    """번역된 배치 파일을 커밋하고, 남은 배치가 있으면 파일로 쓴다.

    파일 내용은 문자열 그대로 라이브러리 commit_batch에 넘긴다 —
    라이브러리가 json_repair로 마크다운 코드펜스·후행 쉼표·
    {"batch": [...]} / {"items": [...]} 래핑까지 흡수하므로,
    앞단에서 엄격하게 파싱하면 오히려 관용도가 떨어진다 (CLI와 동일).
    """
    if not translated_file or not os.path.isfile(translated_file):
        raise RuntimeError(f"번역 파일이 없습니다: {translated_file}")
    with open(translated_file, encoding="utf-8-sig") as f:
        text = f.read()
    if not text.strip():
        raise RuntimeError("번역 파일이 비어 있습니다.")
    session = _new_session(input_file, batch_size=batch_size)
    result = session.commit_batch(text)
    if not result.get("success"):
        raise RuntimeError(result.get("error") or "배치 검증에 실패했습니다.")
    if session.is_complete():
        return {"state": "completed", "output_file": session.output_file,
                "status": session.get_status()}
    exchange_dir = exchange_dir_for(input_file)
    os.makedirs(exchange_dir, exist_ok=True)
    status = session.get_status()
    nxt = _write_batch(session, exchange_dir,
                       status.get("target_language", ""), "",
                       include_prompt=False)
    if nxt is None:
        return {"state": "completed", "output_file": session.output_file,
                "status": session.get_status()}
    return nxt


def exchange_status(input_file, batch_size=DEFAULT_BATCH_SIZE):
    """현재 세션 상태 + 기다리는 배치 파일 경로."""
    session = _new_session(input_file, batch_size=batch_size)
    status = session.get_status()
    result = {"state": "completed" if session.is_complete() else "ready",
              "status": status, "output_file": session.output_file}
    if not session.is_complete():
        result["batch_file"] = os.path.join(
            exchange_dir_for(input_file),
            _batch_filename(status.get("batch_number", 1)))
    return result


def reset_exchange(input_file):
    """세션 진행 상태를 초기화한다 (교환 폴더 파일은 남긴다)."""
    session = _new_session(input_file)
    session.reset_progress()
    return {"state": "reset", "status": session.get_status()}
