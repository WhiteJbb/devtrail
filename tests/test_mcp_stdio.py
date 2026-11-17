"""실제 CLI 자식 프로세스와 stdio로 검색·원문 계약을 검증한다."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from typing import Any

import anyio
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from app.config import Settings


def test_cli_stdio_discovery_search_and_versioned_read() -> None:
    """내부 tool manager를 거치지 않고 CLI의 initialize/list/call을 왕복한다."""
    repo = Path(__file__).resolve().parents[1]
    with TemporaryDirectory(prefix="devtrail-stdio-") as temporary:
        root = Path(temporary)
        vault = root / "vault"
        notes = {
            "30_Projects/Alpha/Context.md": "---\nproject: Alpha\n---\n# Alpha\n배경\n",
            "30_Projects/Beta/Context.md": "---\nproject: Beta\n---\n# Beta\n배경\n",
            "30_Projects/Alpha/Decisions/search.md":
                "---\ntitle: 알파 결정\n---\n# 검색 결정\n왕복토큰 알파 원문\n다음 줄\n",
            "30_Projects/Beta/Decisions/search.md": "왕복토큰 베타 원문\n",
            "40_AgentMemory/06_Lessons.md": "왕복토큰 공통 교훈\n",
            "50_Outputs/Digest/unknown.md": "왕복토큰 소속 불명\n",
            "00_Inbox/private.md": "왕복토큰 읽기 금지\n",
        }
        for relative, text in notes.items():
            path = vault / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")

        # 모든 설정을 기본값으로 덮어 repo .env와 부모 프로세스의 비밀값을 배제한다.
        env = {field.alias: str(field.default) for field in Settings.model_fields.values()}
        env.update({
            "OBSIDIAN_VAULT_PATH": str(vault), "PYTHONPATH": str(repo),
            "HOME": str(root), "USERPROFILE": str(root), "PYTHONIOENCODING": "utf-8",
        })
        params = StdioServerParameters(
            command=sys.executable, args=["-m", "app.cli", "mcp-serve"],
            cwd=str(root), env=env,
        )
        transcript: list[dict[str, Any]] = []

        async def exchange() -> int:
            with anyio.fail_after(30):
                async with stdio_client(params) as (reader, writer):
                    async with ClientSession(reader, writer) as session:
                        initialized = await session.initialize()
                        assert initialized.serverInfo.name == "devtrail-vault"
                        transcript.append({"initialize": initialized.model_dump(mode="json")})
                        listing = await session.list_tools()
                        schemas = {tool.name: tool.inputSchema for tool in listing.tools}
                        assert schemas["search_vault"]["required"] == ["query"]
                        assert schemas["read_note"]["required"] == ["rel_path"]
                        assert {"query", "limit", "structured", "project", "include_common",
                                "include_unattributed", "include_history", "kinds", "cursor",
                                "max_chars"} == set(schemas["search_vault"]["properties"])
                        assert {"rel_path", "structured", "start_line", "max_lines", "max_chars",
                                "expected_version"} == set(schemas["read_note"]["properties"])
                        transcript.append({"tools/list": {name: schemas[name] for name in
                                                           ("search_vault", "read_note")}})

                        async def call(name: str, **arguments: Any) -> Any:
                            result = await session.call_tool(name, arguments)
                            transcript.append({"tool": name, "arguments": arguments,
                                               "response": result.model_dump(mode="json")})
                            assert not result.isError, result
                            assert result.structuredContent is not None
                            return result.structuredContent["result"]

                        search_args = {"query": "왕복토큰", "structured": True, "project": "Alpha"}
                        search = await call("search_vault", **search_args)
                        own = "30_Projects/Alpha/Decisions/search.md"
                        assert search["ok"] and search["scope"]["project"] == "Alpha"
                        assert [hit["path"] for hit in search["results"]] == [own]
                        assert search["filtered"]["documents"]["other_project"] >= 1
                        assert search["filtered"]["documents"]["common"] == 1
                        hit = search["results"][0]
                        version = "sha256:" + hashlib.sha256(notes[own].encode()).hexdigest()[:16]
                        assert hit["source_version"] == version
                        excerpt = hit["excerpts"][0]
                        read_args = {
                            "rel_path": own, "structured": True,
                            "start_line": excerpt["start_line"],
                            "max_lines": excerpt["end_line"] - excerpt["start_line"] + 1,
                            "expected_version": hit["source_version"],
                        }
                        page = await call("read_note", **read_args)
                        expected = "\n".join(notes[own].splitlines()[
                            excerpt["start_line"] - 1:excerpt["end_line"]])
                        assert page["ok"] and page["content"] == expected == excerpt["text"]
                        assert page["source_version"] == version

                        common = await call("search_vault", **search_args, include_common=True)
                        assert common["ok"]
                        assert {h["path"] for h in common["results"]} == {
                            own, "40_AgentMemory/06_Lessons.md"}
                        legacy = await call("search_vault", query="왕복토큰", limit=10)
                        assert isinstance(legacy, list) and len(legacy) == 4
                        assert all(set(h) == {"path", "title", "status", "score", "summary"}
                                   for h in legacy)
                        assert await call("read_note", rel_path=own) == notes[own]

                        (vault / own).write_text(notes[own] + "변경된 줄\n", encoding="utf-8")
                        changed = await call("read_note", **read_args)
                        assert not changed["ok"]
                        assert changed["error"]["code"] == "version_mismatch"
                        assert "content" not in changed
                        denied = await call("read_note", rel_path="00_Inbox/private.md", structured=True)
                        assert denied["error"]["code"] == "scope_violation"

                        markers = list((root / ".claude/.vault-mcp/mcp_sessions").glob("*.json"))
                        assert len(markers) == 1
                        pid = json.loads(markers[0].read_text(encoding="utf-8"))["pid"]
                        assert pid != os.getpid()
                        return pid

        pid = asyncio.run(exchange())
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            pass
        else:
            raise AssertionError(f"stdio 종료 뒤 자식 프로세스가 남았습니다: {pid}")
        print(json.dumps({"command": [sys.executable, "-m", "app.cli", "mcp-serve"],
                          "exchanges": transcript, "child_reaped": True}, ensure_ascii=False))
    assert not root.exists()
    print("temporary_vault_removed=true")


def test_cli_stdio_structured_briefing_then_evidence_read() -> None:
    """임시 fixture vault와 실제 mcp-serve 자식 프로세스로 structured briefing → 근거 구간 읽기를 왕복한다.

    운영 PM(사용자 Claude 설정·실제 vault)과 무관한 제품 왕복 검증이다.
    """
    repo = Path(__file__).resolve().parents[1]
    with TemporaryDirectory(prefix="devtrail-stdio-brief-") as temporary:
        root = Path(temporary)
        vault = root / "vault"
        background = "".join(f"- 배경 {i}: " + "설명 " * 20 + "\n" for i in range(300))
        context_rel = "30_Projects/Alpha/Context.md"
        process_rel = "60_Candidates/SessionHandoffs/Alpha/process.md"
        notes = {
            context_rel: "---\nproject: Alpha\nupdated_at: 2099-01-01\n---\n# Alpha — Project Context\n\n## 배경\n\n"
                         + background + "\n## 목표\n\n- \n\n## 제약\n\n- 왕복 제약: 공식 영역 직접 쓰기 금지\n- \n- 두 번째 제약\n"
                         "\n### 운영 서버에서만 적용\n\n- \n",
            "30_Projects/Beta/Context.md": "---\nproject: Beta\n---\n## 제약\n\n- 베타 제약\n",
            process_rel: "---\ntitle: Alpha Process\nproject: Alpha\nhandoff_type: process\nsession_id: s1\n"
                         "created_at: 2026-11-10T10:00:00\n---\n# Process\n\n## What Changed\n\n- 결과\n\n"
                         "## Next Session\n\n- 왕복 후속 항목\n",
            "60_Candidates/SessionHandoffs/Beta/process.md": "---\ntitle: Beta Process\nproject: Beta\n"
                         "handoff_type: process\nsession_id: b1\n---\n## Next Session\n\n- 베타 후속\n",
            # 제약만으로 20000자를 넘는 프로젝트 — requires_read가 생긴다
            "30_Projects/Gamma/Context.md": "---\nproject: Gamma\nupdated_at: 2099-01-01\n---\n## 원칙\n\n"
                         + "".join(f"- 원칙 {i:03d}: " + "지켜야 할 내용 " * 10 + "\n" for i in range(250)),
        }
        for relative, text in notes.items():
            path = vault / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")

        env = {field.alias: str(field.default) for field in Settings.model_fields.values()}
        env.update({
            "OBSIDIAN_VAULT_PATH": str(vault), "PYTHONPATH": str(repo),
            "HOME": str(root), "USERPROFILE": str(root), "PYTHONIOENCODING": "utf-8",
        })
        params = StdioServerParameters(command=sys.executable, args=["-m", "app.cli", "mcp-serve"], cwd=str(root), env=env)
        transcript: list[dict[str, Any]] = []

        async def exchange() -> None:
            with anyio.fail_after(30):
                async with stdio_client(params) as (reader, writer):
                    async with ClientSession(reader, writer) as session:
                        await session.initialize()
                        listing = await session.list_tools()
                        schema = {t.name: t.inputSchema for t in listing.tools}["get_project_briefing"]
                        assert schema["required"] == ["project_or_repo"]
                        assert set(schema["properties"]) == {"project_or_repo", "structured"}
                        assert schema["properties"]["structured"].get("default") is False
                        transcript.append({"tools/list": {"get_project_briefing": schema}})

                        async def call(name: str, **arguments: Any) -> Any:
                            result = await session.call_tool(name, arguments)
                            transcript.append({"tool": name, "arguments": arguments,
                                               "response_chars": len(json.dumps(result.model_dump(mode="json"),
                                                                                ensure_ascii=False))})
                            assert not result.isError, result
                            if result.structuredContent is not None:
                                return result.structuredContent["result"]
                            # 반환 타입이 dict인 기존 tool은 structuredContent 없이 JSON 텍스트 한 덩어리로 온다
                            assert len(result.content) == 1 and result.content[0].type == "text"
                            return json.loads(result.content[0].text)

                        default = await call("get_project_briefing", project_or_repo="Alpha")
                        assert set(default) == {"project", "matched", "candidates", "text", "source_refs"}
                        brief = await call("get_project_briefing", project_or_repo="Alpha", structured=True)
                        assert brief["schema_version"] == "1" and brief["matching"]["status"] == "resolved"
                        assert len(brief["text"]) <= 20000 and brief["partial"] is False
                        assert "베타" not in json.dumps(brief, ensure_ascii=False)
                        assert set(default) <= set(brief) and brief["source_refs"] == [context_rel, process_rel]
                        assert [s["key"] for s in brief["sections"]] == ["constraints", "context", "recent",
                                                                         "follow_ups", "gaps"]
                        order = brief["budget"]["budget_order"]
                        assert order.index("context_section") < order.index("next_session") < order.index("decision")
                        sections = {s["key"]: s for s in brief["sections"]}
                        constraint = sections["constraints"]["items"][0]
                        assert len(constraint["segments"]) == 2 and constraint["contiguous"] is False
                        raw_lines = notes[context_rel].splitlines()
                        version = "sha256:" + hashlib.sha256(notes[context_rel].encode()).hexdigest()[:16]
                        assert constraint["source_version"] == version
                        for seg in constraint["segments"]:
                            page = await call("read_note", rel_path=context_rel, structured=True,
                                              start_line=seg["start_line"],
                                              max_lines=seg["end_line"] - seg["start_line"] + 1,
                                              expected_version=constraint["source_version"])
                            assert page["ok"]
                            assert page["content"] == seg["text"] == "\n".join(
                                raw_lines[seg["start_line"] - 1:seg["end_line"]])
                            assert seg["text"] in brief["text"]
                        # 템플릿과 정확히 같은 빈 절(`## 목표` + `- `)만 지우고, 빈 불릿만 거느린 비템플릿 제목은 남긴다
                        assert "## 목표" not in brief["text"]
                        assert {"heading": "목표", "reason": "template_section"}.items() <= next(
                            c for c in sections["context"]["cleaned_sections"] if c["heading"] == "목표").items()
                        scope = next(i for i in sections["constraints"]["items"] if i.get("scaffold_only"))
                        assert [h["text"] for h in scope["heading_path"]] == ["제약"]
                        (seg,) = scope["segments"]
                        page = await call("read_note", rel_path=context_rel, structured=True, start_line=seg["start_line"],
                                          max_lines=1, expected_version=scope["source_version"])
                        assert page["ok"] and page["content"] == seg["text"] == "### 운영 서버에서만 적용"
                        assert seg["text"] in brief["text"]
                        follow = sections["follow_ups"]["items"][0]
                        assert follow["segments"][0]["text"] == "- 왕복 후속 항목" and follow["path"] == process_rel
                        # 긴 배경 뒤의 제약이 남고, 잘린 배경은 생략 위치·이어읽기 인자로 회수된다
                        # 반환된 read 객체를 변환 없이 그대로 read_note 인자로 넘긴다
                        om = next(o for o in brief["omissions"] if o["section"] == "context")
                        page = await call("read_note", **om["read"])
                        assert page["ok"] and page["start_line"] == om["lines"][0]
                        assert page["content"].splitlines()[0] == raw_lines[om["lines"][0] - 1]

                        gamma = await call("get_project_briefing", project_or_repo="Gamma", structured=True)
                        assert gamma["critical_omission"] is True and gamma["requires_read"]
                        gamma_lines = (vault / "30_Projects/Gamma/Context.md").read_text(encoding="utf-8").splitlines()
                        for need in gamma["requires_read"]:
                            page = await call("read_note", **need["read"])
                            assert page["ok"] and page["start_line"] == need["lines"][0]
                            assert page["content"].splitlines() == gamma_lines[need["lines"][0] - 1:need["lines"][1]]

                        (vault / context_rel).write_text(notes[context_rel] + "- 바뀐 줄\n", encoding="utf-8")
                        seg = constraint["segments"][0]
                        changed = await call("read_note", rel_path=context_rel, structured=True,
                                             start_line=seg["start_line"], max_lines=1,
                                             expected_version=constraint["source_version"])
                        assert changed["ok"] is False and changed["error"]["code"] == "version_mismatch"
                        stale = await call("read_note", **om["read"])  # 반환 인자 그대로도 변경을 잡는다
                        assert stale["ok"] is False and stale["error"]["code"] == "version_mismatch"

        asyncio.run(exchange())
        print(json.dumps({"command": [sys.executable, "-m", "app.cli", "mcp-serve"], "exchanges": transcript},
                         ensure_ascii=False))
    assert not root.exists()
