# -*- coding: utf-8 -*-
"""GUI 자체 스킬 설치 (라이브러리 install_skill이 모르는 대상용).

라이브러리(gemini-srt-translator)의 install_skill은 agents(범용)·
antigravity·claude 대상만 안다. Gemini CLI와 GitHub Copilot처럼 SKILL.md
표준을 쓰지만 라이브러리가 모르는 대상은, 라이브러리가 제공하는
SKILL.md 내용을 그대로 사용해 GUI가 직접 대상 경로에 복사한다.

경로 근거 (2026-10-30 공식 문서·실측 확인):
  - Gemini CLI: 전역 ~/.gemini/skills, 프로젝트 .gemini/skills
    (https://geminicli.com/docs/cli/skills/)
  - Muse: 전역 ~/.copilot/skills, 프로젝트 .github/skills
    (https://docs.github.com/en/copilot/how-tos/copilot-cli/customize-copilot/create-skills)
  - agy (Antigravity CLI): 워크스페이스의 .agents/skills는 자동 발견하지만
    전역에서는 ~/.gemini/config/skills.json에 절대 경로로 등록해야 발견한다
    (agy 내장 agy-customizations 문서 + 데탑 실측). 그래서 agy 대상은
    파일 복사(~/.agents/skills)에 더해 skills.json 등록까지 수행한다.
"""

import json
import os
import tempfile

SKILL_NAME = "subtitle-translator"

# target_id -> (전역 상대 경로, 프로젝트 상대 경로) — skills 폴더까지
EXTRA_TARGETS = {
    "gemini_cli": (".gemini/skills", ".gemini/skills"),
    "copilot": (".copilot/skills", ".github/skills"),
    "agy": (".agents/skills", ".agents/skills"),
}

EXTRA_TARGET_IDS = tuple(EXTRA_TARGETS.keys())


def load_skill_content():
    """라이브러리가 제공하는 SKILL.md 내용. 못 찾으면 None."""
    try:
        from core.gst_compat import get_skill_path
    except Exception:
        return None
    if get_skill_path is None:
        return None
    try:
        path = get_skill_path()
    except Exception:
        return None
    if not path or not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None


def dest_path(target, is_global=False, cwd=None, home=None):
    """대상별 SKILL.md 설치 경로."""
    if target not in EXTRA_TARGETS:
        raise ValueError(f"알 수 없는 확장 대상: {target}")
    global_rel, project_rel = EXTRA_TARGETS[target]
    if is_global:
        base = home or os.path.expanduser("~")
        rel = global_rel
    else:
        base = os.path.abspath(cwd or os.getcwd())
        rel = project_rel
    return os.path.join(base, *rel.split("/"), SKILL_NAME, "SKILL.md")


def _register_agy_global(home):
    """agy 전역 발견용으로 ~/.gemini/config/skills.json에 스킬 폴더를 등록.

    반환: skills.json 경로. 기존 entries는 보존하고, 같은 경로가 이미
    있으면 그대로 둔다. '~' 경로는 agy가 확장하지 못해 절대 경로로 쓴다
    (2026-10-30 실측). 쓰기는 임시 파일 + os.replace 원자적 교체로 해서
    도중 실패해도 기존 설정을 잃지 않는다.
    """
    home = os.path.abspath(home or os.path.expanduser("~"))
    skills_dir = os.path.join(home, ".agents", "skills")
    config_dir = os.path.join(home, ".gemini", "config")
    config_path = os.path.join(config_dir, "skills.json")

    data = {}
    if os.path.isfile(config_path):
        try:
            with open(config_path, encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            raise RuntimeError(
                f"기존 skills.json을 읽을 수 없어 agy 등록을 중단합니다: "
                f"{config_path} ({e})"
            )
    entries = data.get("entries")
    if not isinstance(entries, list):
        entries = []
    wanted = os.path.normpath(skills_dir)
    if not any(isinstance(e, dict) and isinstance(e.get("path"), str)
               and os.path.normpath(e["path"]) == wanted
               for e in entries):
        entries.append({"path": skills_dir})
    data["entries"] = entries

    os.makedirs(config_dir, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=config_dir, prefix=".skills-",
                                    suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, config_path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
    return config_path


def install_extra_skill(target, is_global=False, cwd=None, content=None,
                        home=None):
    """확장 대상에 SKILL.md 설치. 반환: [설치·등록 경로].

    content를 주면 라이브러리 조회 없이 그 내용을 쓴다 (테스트용).
    agy 전역 설치는 skills.json 등록 경로도 반환 목록에 포함한다.
    """
    if content is None:
        content = load_skill_content()
    if content is None:
        raise RuntimeError(
            "라이브러리의 SKILL.md를 찾을 수 없습니다. "
            "gemini-srt-translator 설치를 확인하세요."
        )
    dest = dest_path(target, is_global=is_global, cwd=cwd, home=home)
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    with open(dest, "w", encoding="utf-8") as f:
        f.write(content)
    paths = [dest]
    if target == "agy" and is_global:
        paths.append(_register_agy_global(home))
    return paths
