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
