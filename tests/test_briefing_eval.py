"""고정 평가 Vault 비교 — 기본 briefing 대비 structured briefing의 보존·위치 확보·상한 (tests/briefing_eval.py).

크기·시간은 비교 표로 보고만 하고 개선을 단정하지 않는다 — structured 응답은 기본보다 길고 느리다.
"""

from __future__ import annotations

import pytest

from tests.briefing_eval import run_eval


@pytest.fixture(scope="module")
def rows():
    return {r["scenario"]: r for r in run_eval()}


def test_structured_never_loses_a_target_the_default_kept(rows):
    for name, r in rows.items():
        assert r["structured"]["targets_in_text"] >= r["legacy"]["targets_in_text"], name
        # 본문에 보이는 목표 줄은 모두 경로·줄·버전까지 응답에 있다
        assert r["structured"]["located"] == r["structured"]["targets_in_text"], name
        assert r["structured"]["text_chars"] <= 20000, name


def test_late_constraint_and_older_follow_ups_are_kept(rows):
    late = rows["긴 Context 후반 제약"]
    assert late["legacy"]["targets_in_text"] < late["targets"] == late["structured"]["targets_in_text"]
    older = rows["이전 세션의 긴 Next Session"]
    assert older["legacy"]["targets_in_text"] < older["targets"] == older["structured"]["targets_in_text"]


def test_over_budget_constraints_are_flagged_not_silent(rows):
    huge = rows["제약만 2만 자 초과"]
    assert huge["structured"]["critical_omission"] is True
    assert huge["structured"]["targets_in_text"] < huge["targets"]
    # 빠진 목표 줄은 omissions의 이어읽기 1회로 회수된다
    assert huge["structured"]["confirm_calls"] == 2
    assert all(r["structured"]["critical_omission"] is False for n, r in rows.items() if n != "제약만 2만 자 초과")


def test_budget_order_keeps_context_and_follow_ups_before_recent(rows):
    """확정 설계 #7 예산 순서: 제약 → 맥락 → 후속 → 최근 결과·결정. 예산이 모자라면 최근 결과·결정에서 줄어든다."""
    r = rows["본문 예산 초과 — 맥락·후속 vs 최근 결과"]["structured"]
    assert r["kept"] == {"constraint": "1/1", "context": "4/4", "follow_up": "2/2"}
    assert set(r["budget_cut"]) == {"recent"}
    assert r["critical_omission"] is False and r["text_chars"] <= 20000


def test_non_template_headings_over_empty_bullets_are_kept(rows):
    """템플릿과 정확히 같은 빈 절만 지운다 — 빈 불릿만 거느린 비템플릿 제목(제약·맥락·메모리·후속)은 모두 본문에 남는다."""
    r = rows["템플릿을 고쳐 쓴 Context·빈 불릿 아래 제목"]["structured"]
    assert r["kept"] == {"constraint": "2/2", "context": "3/3", "follow_up": "2/2"}
    assert r["critical_omission"] is False
