# -*- coding: utf-8 -*-
"""모델별 토큰 단가(pricing.json) 기반 비용 추정 (순수 함수).

단가표는 gemini-srt-translator 패키지에 내장된 pricing.json을 사용한다.
"""

import json
import os

TOKEN_REPORT_DIRNAME = ".token_reports"


def _pricing_path():
    """설치된 라이브러리의 pricing.json 경로. 없으면 None."""
    try:
        import importlib.util
        spec = importlib.util.find_spec("gemini_srt_translator")
        if spec and spec.origin:
            p = os.path.join(os.path.dirname(spec.origin), "pricing.json")
            if os.path.isfile(p):
                return p
    except Exception:
        pass
    return None


def load_pricing():
    """pricing.json 전체 dict. 실패 시 {}."""
    path = _pricing_path()
    if not path:
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _normalize_model(model_name):
    return (model_name or "").strip().lower()


def get_model_rates(model_name, tier="standard", pricing=None):
    """(input $/1M, output $/1M) 반환. 모르면 None."""
    pricing = pricing if pricing is not None else load_pricing()
    models = pricing.get("models", {})
    # 정확한 이름 우선, 없으면 소문자 매칭
    entry = models.get(model_name) or models.get(_normalize_model(model_name))
    if not entry:
        # 'models/' 접두사 등 변형 대응
        short = _normalize_model(model_name).split("/")[-1]
        for k, v in models.items():
            if _normalize_model(k) == short:
                entry = v
                break
    if not entry:
        return None
    rates = entry.get(tier) or entry.get("standard")
    if not rates or "input" not in rates or "output" not in rates:
        return None
    return float(rates["input"]), float(rates["output"])


def estimate_cost(model_name, prompt_tokens, output_tokens, tier="standard",
                  pricing=None):
    """예상 비용 dict {'input': $, 'output': $, 'total': $, 'tier': tier}.
    단가를 모르면 None."""
    rates = get_model_rates(model_name, tier, pricing)
    if not rates:
        return None
    in_rate, out_rate = rates
    input_cost = (prompt_tokens or 0) / 1_000_000 * in_rate
    output_cost = (output_tokens or 0) / 1_000_000 * out_rate
    return {
        "input": round(input_cost, 6),
        "output": round(output_cost, 6),
        "total": round(input_cost + output_cost, 6),
        "tier": tier,
    }


def token_report_path_for(output_file_path):
    """작업 출력 파일에 대응하는 토큰 리포트 경로."""
    base = os.path.splitext(os.path.basename(output_file_path or ""))[0]
    d = os.path.join(os.path.dirname(output_file_path or "") or ".",
                     TOKEN_REPORT_DIRNAME)
    return os.path.join(d, f"{base}_tokens.json")


def read_report_cost(report_path):
    """토큰 리포트에서 cost dict 읽기. 없으면 None."""
    try:
        with open(report_path, encoding="utf-8") as f:
            report = json.load(f)
        cost = report.get("cost")
        if isinstance(cost, dict) and "total" in cost:
            return cost
    except Exception:
        pass
    return None
