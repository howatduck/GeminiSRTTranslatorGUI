# -*- coding: utf-8 -*-
"""core/skill_install_extra.py 테스트 (Qt·라이브러리 없이 실행 가능)."""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core import skill_install_extra as extra


def test_extra_target_ids():
    assert set(extra.EXTRA_TARGET_IDS) == {"gemini_cli", "copilot", "agy"}


def test_dest_path_gemini_cli(tmp_path):
    home = str(tmp_path / "home")
    p = extra.dest_path("gemini_cli", is_global=True, home=home)
    assert p == os.path.join(home, ".gemini", "skills",
                             "subtitle-translator", "SKILL.md")
    proj = str(tmp_path / "proj")
    p2 = extra.dest_path("gemini_cli", is_global=False, cwd=proj)
    assert p2 == os.path.join(proj, ".gemini", "skills",
                              "subtitle-translator", "SKILL.md")


def test_dest_path_copilot(tmp_path):
    home = str(tmp_path / "home")
    p = extra.dest_path("copilot", is_global=True, home=home)
    assert p == os.path.join(home, ".copilot", "skills",
                             "subtitle-translator", "SKILL.md")
    proj = str(tmp_path / "proj")
    p2 = extra.dest_path("copilot", is_global=False, cwd=proj)
    assert p2 == os.path.join(proj, ".github", "skills",
                              "subtitle-translator", "SKILL.md")


def test_dest_path_unknown_target():
    with pytest.raises(ValueError):
        extra.dest_path("nope", is_global=True, home="/tmp")


def test_install_extra_skill_writes_content(tmp_path):
    home = str(tmp_path / "home")
    paths = extra.install_extra_skill(
        "copilot", is_global=True, home=home, content="# skill body")
    assert len(paths) == 1
    with open(paths[0], encoding="utf-8") as f:
        assert f.read() == "# skill body"


def test_install_extra_skill_project(tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir()
    paths = extra.install_extra_skill(
        "gemini_cli", is_global=False, cwd=str(proj), content="x")
    assert paths[0].endswith(
        os.path.join(".gemini", "skills", "subtitle-translator", "SKILL.md"))
    assert os.path.isfile(paths[0])


def test_install_extra_skill_no_content(monkeypatch):
    monkeypatch.setattr(extra, "load_skill_content", lambda: None)
    with pytest.raises(RuntimeError):
        extra.install_extra_skill("gemini_cli", is_global=True, home="/tmp")


def test_install_agy_global_registers_skills_json(tmp_path):
    import json as _json
    home = tmp_path / "home"
    home.mkdir()
    paths = extra.install_extra_skill(
        "agy", is_global=True, home=str(home), content="# skill")
    # 파일 복사 + skills.json 등록 두 경로가 반환된다
    assert len(paths) == 2
    skill_md = home / ".agents" / "skills" / "subtitle-translator" / "SKILL.md"
    assert skill_md.is_file()
    config_path = home / ".gemini" / "config" / "skills.json"
    assert str(config_path) == paths[1]
    data = _json.loads(config_path.read_text(encoding="utf-8"))
    # '~'가 아닌 절대 경로로 등록돼야 agy가 발견한다
    assert data["entries"] == [
        {"path": str(home / ".agents" / "skills")}]


def test_install_agy_global_preserves_existing_entries(tmp_path):
    import json as _json
    home = tmp_path / "home"
    config_dir = home / ".gemini" / "config"
    config_dir.mkdir(parents=True)
    (config_dir / "skills.json").write_text(
        _json.dumps({"entries": [{"path": "/other/skills"}],
                     "inherits": []}),
        encoding="utf-8")
    extra.install_extra_skill(
        "agy", is_global=True, home=str(home), content="# skill")
    data = _json.loads((config_dir / "skills.json").read_text(encoding="utf-8"))
    paths = [e["path"] for e in data["entries"]]
    assert "/other/skills" in paths
    assert str(home / ".agents" / "skills") in paths
    assert data["inherits"] == []
    # 재설치해도 중복 등록되지 않는다
    extra.install_extra_skill(
        "agy", is_global=True, home=str(home), content="# skill")
    data = _json.loads((config_dir / "skills.json").read_text(encoding="utf-8"))
    assert [e["path"] for e in data["entries"]].count(
        str(home / ".agents" / "skills")) == 1


def test_install_agy_project_no_registration(tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir()
    paths = extra.install_extra_skill(
        "agy", is_global=False, cwd=str(proj), content="# skill")
    assert len(paths) == 1  # 프로젝트 범위는 skills.json 등록 없음
    assert not (proj / ".gemini").exists()


def test_register_agy_global_invalid_json(tmp_path):
    home = tmp_path / "home"
    config_dir = home / ".gemini" / "config"
    config_dir.mkdir(parents=True)
    (config_dir / "skills.json").write_text("{invalid", encoding="utf-8")
    with pytest.raises(RuntimeError):
        extra.install_extra_skill(
            "agy", is_global=True, home=str(home), content="# skill")


def test_register_agy_global_trailing_slash_not_duplicated(tmp_path):
    import json as _json
    home = tmp_path / "home"
    config_dir = home / ".gemini" / "config"
    config_dir.mkdir(parents=True)
    existing = str(home / ".agents" / "skills") + "/"
    (config_dir / "skills.json").write_text(
        _json.dumps({"entries": [{"path": existing}]}), encoding="utf-8")
    extra.install_extra_skill(
        "agy", is_global=True, home=str(home), content="# skill")
    data = _json.loads((config_dir / "skills.json").read_text(encoding="utf-8"))
    assert len(data["entries"]) == 1  # 정규화 비교로 중복 등록 방지


def test_register_agy_global_leaves_no_temp_files(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    extra.install_extra_skill(
        "agy", is_global=True, home=str(home), content="# skill")
    config_dir = home / ".gemini" / "config"
    names = [p.name for p in config_dir.iterdir()]
    assert names == ["skills.json"]  # 원자적 쓰기 임시 파일 잔재 없음


def test_load_skill_content_via_gst_compat(tmp_path, monkeypatch):
    import core.gst_compat as gc
    skill_file = tmp_path / "SKILL.md"
    skill_file.write_text("# real skill", encoding="utf-8")
    monkeypatch.setattr(gc, "get_skill_path", lambda: str(skill_file))
    assert extra.load_skill_content() == "# real skill"
    monkeypatch.setattr(gc, "get_skill_path", lambda: None)
    assert extra.load_skill_content() is None
    monkeypatch.setattr(gc, "get_skill_path", lambda: "/nonexistent/SKILL.md")
    assert extra.load_skill_content() is None
