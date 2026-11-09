# -*- coding: utf-8 -*-
"""작업 재시도 계획: 모델 폴백 체인 × 배치 크기 래더 (순수 함수)."""


def batch_ladder(start, step, floor):
    """배치 크기 내림 순서: start에서 step씩 줄여 floor까지.

    step이 0 이하이거나 floor가 start 이상이면 [start]만 반환한다
    (래더 비활성). floor는 최소 1, start를 넘지 않게 보정한다.
    """
    try:
        start = int(start)
        step = int(step or 0)
        floor = int(floor or 0)
    except (TypeError, ValueError):
        return [start]
    if start <= 0:
        return [start]
    if step <= 0 or floor <= 0 or floor >= start:
        return [start]
    floor = max(1, floor)
    sizes = [start]
    cur = start
    while cur > floor:
        cur = max(floor, cur - step)
        sizes.append(cur)
    return sizes


def build_attempt_plan(models, batch_start, batch_step, batch_floor,
                       max_profiles=16):
    """(모델, 배치) 시도 프로필 목록 — 배치 단계 우선, 그 안에서 모델 순.

    예: 모델 [A, B], 래더 [1000, 500] →
    [(A,1000), (B,1000), (A,500), (B,500)]
    같은 배치에서 모델을 먼저 갈아타고, 그다음 배치를 줄이는 순서라
    과부하(모델 문제)와 줄수 오류(배치 문제) 양쪽에 고르게 대응한다.
    """
    chain = []
    for m in models or []:
        if m and m not in chain:
            chain.append(m)
    if not chain:
        chain = [None]
    ladder = batch_ladder(batch_start, batch_step, batch_floor)
    plan = [(m, b) for b in ladder for m in chain]
    return plan[:max_profiles]
