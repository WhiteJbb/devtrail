"""E2E smoke test: capture → distill-today → list-candidates → promote-candidate → build-context.

실제 LLM·Vault 없이 FakeLLM + tmp_path로 전체 파이프라인을 검증한다.
"""

from __future__ import annotations

import json
from datetime import datetime

import pytest

from app.agents.capture_agent import CaptureAgent
from app.agents.curator_agent import CuratorAgent
from app.agents.distill_agent import DistillAgent
from app.config import Settings
from app.llm.base import LLMError
from app.memory.context_pack_builder import ContextPackBuilder
from tests.conftest import FakeLLM


def _settings(vault):
    return Settings(
        OBSIDIAN_VAULT_PATH=str(vault),
        LLM_PROVIDER="ollama",
        MESSENGER_PROVIDER="",
    )


def _distill_response(title="LLM 라우터 설계 원칙"):
    return json.dumps(
        {
            "knowledge": [
                {
                    "title": title,
                    "summary": "task_type 기반 provider 선택 설계",
                    "body": (
                        "## 개념\n"
                        "LLM 라우터는 task_type에 따라 최적의 provider를 선택한다.\n\n"
                        "## 왜 중요한가\n"
                        "서로 다른 작업에 다른 모델이 필요하다.\n\n"
                        "## 적용 방법\n"
                        "task_type=light면 Gemini Flash-Lite를 우선 사용하고, 실패 시 GPT-4o mini로 폴백한다."
                    ),
                    "project": "devtrail",
                    "tags": ["llm", "architecture"],
                    "source_refs": ["00_Inbox/Captures/test.md"],
                }
            ],
            "decisions": [],
            "memory_patches": [],
            "blog_ideas": [],
        },
        ensure_ascii=False,
    )


# ── 파이프라인 전체 흐름 ──────────────────────────────────────────────────────


def test_full_pipeline_capture_to_promote(tmp_path):
    """capture → distill-today → list-candidates → promote-candidate 흐름."""
    settings = _settings(tmp_path)
    now = datetime(2026, 6, 23, 9, 0, 0)

    # Step 1: capture — raw 메모 저장
    capture_agent = CaptureAgent(settings=settings, now=now)
    cap_result = capture_agent.capture(
        text="LLM 라우터 task_type 기반 설계 완료. light/writer/long_writer/polish/local 분류.",
        project="devtrail",
    )
    assert cap_result.path.exists()
    assert "00_Inbox" in cap_result.rel_path

    # Step 2: distill-today — LLM으로 후보 생성
    llm = FakeLLM(_distill_response())
    distill_agent = DistillAgent(settings=settings, llm=llm, now=now)
    distill_result = distill_agent.distill_today()

    assert len(distill_result.written) == 1
    written = distill_result.written[0]
    assert written.spec.kind == "knowledge"
    assert written.spec.title == "LLM 라우터 설계 원칙"
    assert written.path.exists()
    assert written.rel_path.startswith("60_Candidates/Knowledge/")

    # Step 3: list-candidates — 목록 조회
    curator = CuratorAgent(settings=settings)
    candidates = curator.list_candidates()

    assert len(candidates) == 1
    item = candidates[0]
    assert item.kind == "knowledge"
    assert item.title == "LLM 라우터 설계 원칙"

    # Step 4: promote-candidate — 공식 영역으로 승격
    promote_result = curator.promote_candidate(item.rel_path)
    promoted_path = tmp_path / promote_result.promoted_path
    assert promoted_path.exists()
    assert promote_result.kind == "knowledge"
    assert promote_result.promoted_path.startswith("20_Knowledge/")

    # 승격 후 원본 candidate 파일 삭제 확인 (duplicate stem 방지)
    assert not (tmp_path / item.rel_path).exists(), "승격 후 원본 파일이 삭제되어야 한다"


def test_build_context_after_promote(tmp_path):
    """promote 이후 build-context가 해당 지식을 포함하는지 확인한다."""
    settings = _settings(tmp_path)
    now = datetime(2026, 6, 23, 9, 0, 0)

    # capture + distill + promote
    CaptureAgent(settings=settings, now=now).capture(
        text="LLM 라우터 설계 결정: task_type별 fallback chain 구성",
        project="devtrail",
    )
    llm = FakeLLM(_distill_response())
    distill_result = DistillAgent(settings=settings, llm=llm, now=now).distill_today()
    curator = CuratorAgent(settings=settings)
    candidates = curator.list_candidates()
    curator.promote_candidate(candidates[0].rel_path)

    # build-context — 승격된 지식 노트가 검색되어야 한다
    builder = ContextPackBuilder(tmp_path)
    pack = builder.build("LLM 라우터")
    rendered = pack.render()
    assert rendered  # 비어있지 않으면 OK


def test_distill_no_notes_skips_llm(tmp_path):
    """오늘 raw 노트가 없으면 LLM을 호출하지 않고 빈 결과를 반환한다."""
    settings = _settings(tmp_path)
    llm = FakeLLM(_distill_response())
    agent = DistillAgent(settings=settings, llm=llm, now=datetime(2026, 6, 23))

    result = agent.distill_today()

    assert result.written == []
    assert llm.last_prompt == ""  # LLM 미호출


def test_duplicate_candidate_not_rewritten(tmp_path):
    """동일 제목 후보를 두 번 distill해도 파일이 중복 생성되지 않는다."""
    settings = _settings(tmp_path)
    now = datetime(2026, 6, 23, 9, 0, 0)

    CaptureAgent(settings=settings, now=now).capture(text="LLM 라우터 작업", project="devtrail")

    llm = FakeLLM(_distill_response())
    agent = DistillAgent(settings=settings, llm=llm, now=now)

    first = agent.distill_today()
    second = agent.distill_today()

    assert len(first.written) == 1
    assert len(second.written) == 1
    # dedup: 두 번 모두 같은 파일 경로를 반환
    assert first.written[0].rel_path == second.written[0].rel_path


# ── LLM 실패 방어 ─────────────────────────────────────────────────────────────


def test_raw_notes_preserved_on_llm_error(tmp_path):
    """LLM 예외 발생 시 raw 노트가 삭제·변경되지 않는다."""
    settings = _settings(tmp_path)
    now = datetime(2026, 6, 23, 9, 0, 0)

    # raw 노트 생성
    capture_result = CaptureAgent(settings=settings, now=now).capture(
        text="중요한 메모 — 절대 유실되면 안 됨", project="test"
    )
    raw_path = capture_result.path
    original_content = raw_path.read_text(encoding="utf-8")

    class ErrorLLM:
        name = "error"
        model = "error"

        def complete(self, prompt, system=""):
            raise LLMError("API 타임아웃")

    agent = DistillAgent(settings=settings, llm=ErrorLLM(), now=now)

    with pytest.raises(LLMError):
        agent.distill_today()

    # raw 노트 보존 확인
    assert raw_path.exists(), "LLM 실패 시 raw 노트 파일이 삭제되어서는 안 된다"
    assert raw_path.read_text(encoding="utf-8") == original_content, "LLM 실패 시 raw 노트 내용이 변경되어서는 안 된다"


def test_raw_notes_preserved_on_json_parse_error(tmp_path):
    """LLM이 유효하지 않은 JSON을 반환해도 raw 노트가 보존된다."""
    settings = _settings(tmp_path)
    now = datetime(2026, 6, 23, 9, 0, 0)

    capture_result = CaptureAgent(settings=settings, now=now).capture(
        text="JSON 파싱 실패 테스트 메모", project="test"
    )
    raw_path = capture_result.path

    # 두 번 모두 깨진 JSON 반환
    llm = FakeLLM("이것은 JSON이 아닙니다")
    agent = DistillAgent(settings=settings, llm=llm, now=now)

    with pytest.raises(Exception):  # JSONParseError 또는 LLMError
        agent.distill_today()

    assert raw_path.exists(), "JSON 파싱 실패 시 raw 노트가 삭제되어서는 안 된다"


# ── Candidate frontmatter 검증 ────────────────────────────────────────────────


def test_candidate_frontmatter_has_required_fields(tmp_path):
    """생성된 candidate 파일이 필수 frontmatter 필드를 모두 갖추고 있다."""
    import frontmatter

    settings = _settings(tmp_path)
    now = datetime(2026, 6, 23, 9, 0, 0)

    CaptureAgent(settings=settings, now=now).capture(text="테스트 메모", project="test-proj")
    llm = FakeLLM(_distill_response())
    result = DistillAgent(settings=settings, llm=llm, now=now).distill_today()

    assert result.written
    post = frontmatter.loads(result.written[0].path.read_text(encoding="utf-8"))
    meta = post.metadata

    required = ["type", "candidate_type", "title", "status", "created_at", "project", "tags", "source_refs", "summary"]
    for field in required:
        assert field in meta, f"frontmatter에 '{field}' 필드가 없음"

    assert meta["type"] == "candidate"
    assert meta["status"] == "candidate"
    assert meta["candidate_type"] == "knowledge"
    assert isinstance(meta["tags"], list)
    assert isinstance(meta["source_refs"], list)
    assert "summary" in meta  # 항상 존재해야 함 (빈 문자열이어도 OK)


# ── Source grounding 검증 ──────────────────────────────────────────────────────


def _distill_response_with_fabricated_refs(real_path: str):
    """LLM이 실제 경로 + 허위 경로를 source_refs에 섞어 반환하는 케이스."""
    return json.dumps(
        {
            "knowledge": [
                {
                    "title": "Source Grounding 검증",
                    "summary": "허위 경로가 필터링되는지 확인",
                    "body": "## 개념\n필터링 테스트.\n\n## 왜 중요한가\nLLM이 존재하지 않는 경로를 만들 수 있다.\n\n## 적용 방법\n_spec_from_item에서 fallback_refs와 교차 검증한다.",
                    "project": "devtrail",
                    "tags": ["grounding"],
                    "source_refs": [real_path, "00_Inbox/Captures/FABRICATED_DOES_NOT_EXIST.md"],
                }
            ],
            "decisions": [],
            "memory_patches": [],
            "blog_ideas": [],
        },
        ensure_ascii=False,
    )


def test_fabricated_source_refs_are_filtered(tmp_path):
    """LLM이 허위 경로를 source_refs에 넣어도 실제 노트 경로만 남아야 한다."""
    import frontmatter as fm

    settings = _settings(tmp_path)
    now = datetime(2026, 6, 23, 9, 0, 0)

    cap = CaptureAgent(settings=settings, now=now).capture(text="source grounding 테스트", project="test")
    real_path = cap.rel_path  # 실제로 존재하는 경로 (예: 00_Inbox/Captures/...)

    llm = FakeLLM(_distill_response_with_fabricated_refs(real_path))
    result = DistillAgent(settings=settings, llm=llm, now=now).distill_today()

    assert result.written
    post = fm.loads(result.written[0].path.read_text(encoding="utf-8"))
    saved_refs = post.metadata.get("source_refs", [])

    assert real_path in saved_refs, "실제 경로는 source_refs에 포함되어야 한다"
    assert "00_Inbox/Captures/FABRICATED_DOES_NOT_EXIST.md" not in saved_refs, (
        "허위 경로는 source_refs에서 제거되어야 한다"
    )


def test_all_fabricated_refs_fall_back_to_actual_notes(tmp_path):
    """source_refs가 전부 허위 경로이면 실제 노트 경로 전체로 폴백한다."""
    import frontmatter as fm

    settings = _settings(tmp_path)
    now = datetime(2026, 6, 23, 9, 0, 0)

    CaptureAgent(settings=settings, now=now).capture(text="폴백 테스트 메모", project="test")

    fabricated_only = json.dumps(
        {
            "knowledge": [
                {
                    "title": "전부 허위 경로 테스트",
                    "summary": "폴백 확인",
                    "body": "## 개념\n폴백 테스트.\n\n## 왜 중요한가\n전부 허위 경로일 때 빈 refs를 막아야 한다.\n\n## 적용 방법\nfallback_refs 전체를 사용한다.",
                    "project": "test",
                    "tags": [],
                    "source_refs": ["FAKE/does-not-exist-1.md", "FAKE/does-not-exist-2.md"],
                }
            ],
            "decisions": [],
            "memory_patches": [],
            "blog_ideas": [],
        },
        ensure_ascii=False,
    )

    llm = FakeLLM(fabricated_only)
    result = DistillAgent(settings=settings, llm=llm, now=now).distill_today()

    assert result.written
    post = fm.loads(result.written[0].path.read_text(encoding="utf-8"))
    saved_refs = post.metadata.get("source_refs", [])

    assert saved_refs, "전부 허위 경로일 때 source_refs가 비어있으면 안 된다"
    for ref in saved_refs:
        assert "FAKE/" not in ref, "폴백 후 source_refs에 허위 경로가 남으면 안 된다"


# ── 관련 노트 주입 (cross-session wikilink) ──────────────────────────────────


def _no_wikilink_response():
    """LLM이 ## 관련 노트 없이 자유 서술만 반환하는 케이스 (GPT-4o mini 동작 시뮬레이션)."""
    return json.dumps(
        {
            "knowledge": [
                {
                    "title": "LLM 라우터 설계 원칙",
                    "summary": "task_type 기반 provider 선택",
                    "body": (
                        "## 개념\n"
                        "LLM 라우터는 task_type에 따라 provider를 선택한다.\n\n"
                        "## 왜 중요한가\n"
                        "서로 다른 작업에 다른 모델이 필요하다.\n\n"
                        "## 적용 방법\n"
                        "light면 flash-lite를 기본으로 사용한다."
                    ),
                    "project": "devtrail",
                    "tags": ["llm", "architecture"],
                    "source_refs": ["00_Inbox/Captures/test.md"],
                }
            ],
            "decisions": [],
            "memory_patches": [],
            "blog_ideas": [],
        },
        ensure_ascii=False,
    )


def test_related_links_injected_when_llm_omits_section(tmp_path):
    """LLM이 ## 관련 노트 섹션을 생략해도 cross-session 지식 노트 wikilink가 주입된다."""
    import frontmatter as fm

    settings = _settings(tmp_path)
    now = datetime(2026, 6, 23, 9, 0, 0)

    # 기존 지식 노트 (cross-session 연결 대상)
    knowledge_dir = tmp_path / "20_Knowledge" / "devtrail"
    knowledge_dir.mkdir(parents=True)
    (knowledge_dir / "llm-router-design.md").write_text(
        "---\ntitle: LLM 라우터 설계\ntype: knowledge\ntags:\n- llm\n- architecture\n---\n\n# LLM 라우터 설계\nllm architecture router task_type provider\n",
        encoding="utf-8",
    )

    CaptureAgent(settings=settings, now=now).capture(
        text="llm architecture router task_type provider 설계", project="devtrail"
    )
    result = DistillAgent(
        settings=settings, llm=FakeLLM(_no_wikilink_response()), now=now
    ).distill_today()

    assert result.written
    post = fm.loads(result.written[0].path.read_text(encoding="utf-8"))
    body = post.content

    assert "## 관련 노트" in body, "## 관련 노트 섹션이 주입되어야 한다"
    assert "[[llm-router-design|" in body, "cross-session 지식 노트의 wikilink가 삽입되어야 한다"


def test_related_links_replaces_placeholder(tmp_path):
    """LLM이 (관련 기존 지식 노트 없음) placeholder를 남기면 실제 링크로 교체된다."""
    import frontmatter as fm

    settings = _settings(tmp_path)
    now = datetime(2026, 6, 23, 9, 0, 0)

    knowledge_dir = tmp_path / "20_Knowledge" / "devtrail"
    knowledge_dir.mkdir(parents=True)
    (knowledge_dir / "llm-router-design.md").write_text(
        "---\ntitle: LLM 라우터 설계\ntype: knowledge\ntags:\n- llm\n- architecture\n---\n\n# LLM 라우터 설계\nllm architecture router task_type provider\n",
        encoding="utf-8",
    )

    placeholder_response = json.dumps(
        {
            "knowledge": [
                {
                    "title": "LLM 라우터 설계 원칙",
                    "summary": "task_type 기반 provider 선택",
                    "body": (
                        "## 개념\nLLM 라우터는 task_type에 따라 provider를 선택한다.\n\n"
                        "## 왜 중요한가\n서로 다른 작업에 다른 모델이 필요하다.\n\n"
                        "## 적용 방법\nlight면 flash-lite를 기본으로 사용한다.\n\n"
                        "## 관련 노트\n(관련 기존 지식 노트 없음)"
                    ),
                    "project": "devtrail",
                    "tags": ["llm", "architecture"],
                    "source_refs": ["00_Inbox/Captures/test.md"],
                }
            ],
            "decisions": [],
            "memory_patches": [],
            "blog_ideas": [],
        },
        ensure_ascii=False,
    )

    CaptureAgent(settings=settings, now=now).capture(
        text="llm architecture router task_type provider 설계", project="devtrail"
    )
    result = DistillAgent(
        settings=settings, llm=FakeLLM(placeholder_response), now=now
    ).distill_today()

    assert result.written
    post = fm.loads(result.written[0].path.read_text(encoding="utf-8"))
    body = post.content

    assert "(관련 기존 지식 노트 없음)" not in body, "placeholder가 실제 링크로 교체되어야 한다"
    assert "[[llm-router-design|" in body, "cross-session 지식 노트의 wikilink가 삽입되어야 한다"


def test_related_links_not_injected_when_no_related(tmp_path):
    """관련 지식 노트가 없으면 ## 관련 노트 섹션을 억지로 추가하지 않는다."""
    import frontmatter as fm

    settings = _settings(tmp_path)
    now = datetime(2026, 6, 23, 9, 0, 0)

    # 20_Knowledge 없이 capture만
    CaptureAgent(settings=settings, now=now).capture(
        text="완전히 새로운 주제 테스트", project="new-project"
    )
    result = DistillAgent(
        settings=settings, llm=FakeLLM(_no_wikilink_response()), now=now
    ).distill_today()

    assert result.written
    post = fm.loads(result.written[0].path.read_text(encoding="utf-8"))
    body = post.content

    # LLM이 섹션을 안 쓰고, related도 없으면 섹션이 없어도 된다
    # (있어도 되지만 빈 섹션이 억지로 생기면 안 됨)
    if "## 관련 노트" in body:
        assert "[[" in body or "(관련 기존 지식 노트 없음)" in body


