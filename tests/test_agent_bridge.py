# -*- coding: utf-8 -*-
"""core.agent_bridge 테스트.

SubtitleSession을 흉내 낸 FakeSession으로 흐름을 검증하고,
실제 라이브러리가 있는 환경에서는 진짜 세션 E2E도 돌린다.
"""

import json
import os

import pytest

from core import agent_bridge


class FakeSession:
    """실제 SubtitleSession의 파일 기반 진행 상태 흉내 (인스턴스 간 공유)."""

    STORE = {}

    def __init__(self, input_file, target_language=None, batch_size=None,
                 description=None, resume=True):
        self.input_file = input_file
        self.output_file = os.path.splitext(input_file)[0] + "_translated.srt"
        self.batch_size = batch_size or 50
        self.state = self.STORE.setdefault(
            input_file, {"done": 0, "total": 6, "commits": []})
        self.state["batch_size"] = self.batch_size

    def is_complete(self):
        return self.state["done"] >= self.state["total"]

    def get_status(self):
        done, total = self.state["done"], self.state["total"]
        return {
            "batch_number": done // self.batch_size + 1,
            "completed_lines": done,
            "total_lines": total,
            "progress_percent": round(done / total * 100, 2),
            "target_language": "Korean",
        }

    def get_next_batch(self, include_system_prompt=True):
        if self.is_complete():
            return None
        start = self.state["done"]
        end = min(start + self.batch_size, self.state["total"])
        payload = {"batch": [{"index": str(i), "text": f"line {i}"}
                             for i in range(start, end)]}
        if include_system_prompt:
            payload["system_prompt"] = "PROMPT"
        return payload

    def commit_batch(self, data):
        # 실제 라이브러리 흉내: 문자열이면 코드펜스를 벗기고 JSON으로 읽고
        # (실패 시 거부), {"batch"/"items": [...]} 래핑도 풀어 받는다.
        if isinstance(data, str):
            text = data.strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[-1]
                if text.rstrip().endswith("```"):
                    text = text.rstrip()[:-3]
            try:
                data = json.loads(text)
            except Exception:
                return {"success": False, "error": "bad json"}
        if isinstance(data, dict):
            data = data.get("batch") or data.get("items")
        start = self.state["done"]
        end = min(start + self.batch_size, self.state["total"])
        expected = [str(i) for i in range(start, end)]
        if not isinstance(data, list) or \
                [str(d.get("index")) for d in data] != expected:
            return {"success": False, "error": "index mismatch"}
        self.state["done"] += len(data)
        self.state["commits"].append(data)
        return {"success": True}

    def reset_progress(self):
        self.state["done"] = 0
        self.state["commits"] = []


@pytest.fixture
def fake_env(tmp_path, monkeypatch):
    FakeSession.STORE = {}
    monkeypatch.setattr(agent_bridge, "SubtitleSession", FakeSession)
    src = tmp_path / "movie.srt"
    src.write_text("dummy", encoding="utf-8")
    return src


def test_exchange_dir_for(tmp_path):
    d = agent_bridge.exchange_dir_for(str(tmp_path / "a" / "movie.srt"))
    assert d.endswith(os.path.join("a", "movie_agent_exchange"))


def test_start_exchange_writes_batch_and_instructions(fake_env):
    result = agent_bridge.start_exchange(str(fake_env), "Korean",
                                         batch_size=4)
    assert result["state"] == "ready"
    batch_file = result["batch_file"]
    assert os.path.basename(batch_file) == "batch_001.json"
    items = json.loads(open(batch_file, encoding="utf-8").read())
    assert len(items) == 4 and items[0] == {"index": "0", "text": "line 0"}
    inst = open(result["instructions_file"], encoding="utf-8").read()
    assert "PROMPT" in inst and "Korean" in inst


def test_start_exchange_with_style(fake_env):
    result = agent_bridge.start_exchange(
        str(fake_env), "Korean", batch_size=4, style_instruction="STYLE-X")
    inst = open(result["instructions_file"], encoding="utf-8").read()
    assert "STYLE-X" in inst


def test_commit_exchange_until_completed(fake_env):
    src = str(fake_env)
    agent_bridge.start_exchange(src, "Korean", batch_size=4)
    ex_dir = agent_bridge.exchange_dir_for(src)
    t1 = os.path.join(ex_dir, "translated_1.json")
    with open(t1, "w", encoding="utf-8") as f:
        json.dump([{"index": str(i), "text": f"번역 {i}"} for i in range(4)], f)
    result = agent_bridge.commit_exchange(src, t1, batch_size=4)
    assert result["state"] == "ready"
    assert os.path.basename(result["batch_file"]) == "batch_002.json"

    t2 = os.path.join(ex_dir, "translated_2.json")
    with open(t2, "w", encoding="utf-8") as f:
        json.dump([{"index": str(i), "text": f"번역 {i}"} for i in (4, 5)], f)
    result = agent_bridge.commit_exchange(src, t2, batch_size=4)
    assert result["state"] == "completed"
    assert result["output_file"].endswith("_translated.srt")


def test_commit_exchange_count_mismatch(fake_env):
    src = str(fake_env)
    agent_bridge.start_exchange(src, "Korean", batch_size=4)
    bad = os.path.join(agent_bridge.exchange_dir_for(src), "bad.json")
    with open(bad, "w", encoding="utf-8") as f:
        json.dump([{"index": "0", "text": "x"}], f)
    with pytest.raises(RuntimeError):
        agent_bridge.commit_exchange(src, bad, batch_size=4)


def test_commit_exchange_fenced_json(fake_env):
    # ChatGPT 등이 붙이는 마크다운 코드펜스도 라이브러리처럼 흡수한다
    src = str(fake_env)
    agent_bridge.start_exchange(src, "Korean", batch_size=6)
    fenced = os.path.join(agent_bridge.exchange_dir_for(src), "fenced.txt")
    with open(fenced, "w", encoding="utf-8") as f:
        f.write("```json\n")
        json.dump([{"index": str(i), "text": "t"} for i in range(6)], f)
        f.write("\n```")
    result = agent_bridge.commit_exchange(src, fenced, batch_size=6)
    assert result["state"] == "completed"


def test_commit_exchange_bad_json(fake_env, tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{nope", encoding="utf-8")
    with pytest.raises(RuntimeError):
        agent_bridge.commit_exchange(str(fake_env), str(bad))


def test_commit_exchange_dict_wrapped(fake_env):
    src = str(fake_env)
    agent_bridge.start_exchange(src, "Korean", batch_size=6)
    wrapped = os.path.join(agent_bridge.exchange_dir_for(src), "w.json")
    with open(wrapped, "w", encoding="utf-8") as f:
        json.dump({"batch": [{"index": str(i), "text": "t"}
                              for i in range(6)]}, f)
    result = agent_bridge.commit_exchange(src, wrapped, batch_size=6)
    assert result["state"] == "completed"


def test_status_and_reset(fake_env):
    src = str(fake_env)
    agent_bridge.start_exchange(src, "Korean", batch_size=4)
    st = agent_bridge.exchange_status(src, batch_size=4)
    assert st["state"] == "ready"
    assert os.path.basename(st["batch_file"]) == "batch_001.json"
    agent_bridge.reset_exchange(src)
    st = agent_bridge.exchange_status(src, batch_size=4)
    assert st["status"]["completed_lines"] == 0


def test_start_exchange_missing_file(tmp_path):
    with pytest.raises(RuntimeError):
        agent_bridge.start_exchange(str(tmp_path / "nope.srt"), "Korean")


# ---------- 실제 라이브러리 E2E (있는 환경에서만) ----------

SRT_6 = """1
00:00:01,000 --> 00:00:02,000
Hello there.

2
00:00:02,500 --> 00:00:03,500
How are you?

3
00:00:04,000 --> 00:00:05,000
I am fine.

4
00:00:05,500 --> 00:00:06,500
Let us go home.

5
00:00:07,000 --> 00:00:08,000
The train is late.

6
00:00:08,500 --> 00:00:09,500
See you tomorrow.
"""


def test_real_session_end_to_end(tmp_path):
    pytest.importorskip("gemini_srt_translator")
    if agent_bridge.SubtitleSession is None:
        pytest.skip("SubtitleSession unavailable")
    src = tmp_path / "real.srt"
    src.write_text(SRT_6, encoding="utf-8")

    result = agent_bridge.start_exchange(str(src), "Korean", batch_size=4)
    assert result["state"] == "ready"
    items = json.loads(open(result["batch_file"], encoding="utf-8").read())
    assert len(items) == 4

    def translate(path, items_, fence=False):
        out = [{"index": it["index"], "text": "KO:" + it["text"]}
               for it in items_]
        body = json.dumps(out, ensure_ascii=False)
        if fence:
            body = "```json\n" + body + "\n```"
        p = tmp_path / path
        p.write_text(body, encoding="utf-8")
        return str(p)

    result = agent_bridge.commit_exchange(
        str(src), translate("t1.json", items), batch_size=4)
    assert result["state"] == "ready"
    items2 = json.loads(open(result["batch_file"], encoding="utf-8").read())
    assert len(items2) == 2

    result = agent_bridge.commit_exchange(
        str(src), translate("t2.json", items2, fence=True), batch_size=4)
    assert result["state"] == "completed"
    out_text = open(result["output_file"], encoding="utf-8").read()
    assert out_text.count("KO:") == 6
    assert "00:00:01,000 --> 00:00:02,000" in out_text
