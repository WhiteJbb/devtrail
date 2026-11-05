"""고정 평가 Vault 비교 — legacy 상위 5 정답 회귀 방지, 관련도 역전·후반 발췌·격리 개선 확인 (tests/evidence_eval.py)."""

from __future__ import annotations

import pytest

from tests.evidence_eval import CASES, build_eval_vault, run_case


@pytest.fixture(scope="module")
def eval_rows(tmp_path_factory):
    vault = build_eval_vault(tmp_path_factory.mktemp("eval-vault"))
    return {case.name: (case, run_case(vault, case)) for case in CASES}


def test_every_case_has_evidence_in_first_structured_response(eval_rows):
    for name, (_, row) in eval_rows.items():
        assert row["structured"]["rank"] == 1, name
        assert row["structured"]["evidence_in_response"], name
        assert row["structured"]["calls"] == 1, name


def test_legacy_top5_answers_do_not_regress(eval_rows):
    required = [(n, r) for n, (_, r) in eval_rows.items() if r["legacy"]["rank"]]
    assert len(required) >= 4  # 회귀 집합이 비면 이 검사는 의미가 없다
    for name, row in required:
        assert row["structured"]["rank"] is not None and row["structured"]["rank"] <= row["legacy"]["rank"], name


def test_relevance_inversion_and_late_evidence_improve(eval_rows):
    for name, (case, row) in eval_rows.items():
        if case.kind == "inversion":
            assert row["legacy"]["rank"] is None or row["legacy"]["rank"] > 1, name
        if case.kind in ("inversion", "late"):
            assert not row["legacy"]["evidence_in_response"] and row["structured"]["evidence_in_response"], name


def test_project_isolation_and_history_exclusion(eval_rows):
    for name, (case, row) in eval_rows.items():
        assert row["structured"]["foreign_in_top5"] == 0, name
        assert row["structured"]["superseded_in_top5"] == 0, name
    assert eval_rows["다른 프로젝트 격리"][1]["legacy"]["foreign_in_top5"] > 0
    assert eval_rows["자동 승격 결정"][1]["legacy"]["superseded_in_top5"] == 1
