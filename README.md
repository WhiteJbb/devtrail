# Work Agent

Work Agent is an Obsidian-based LLM Wiki and Personal Knowledge OS.

It captures work traces, indexes an Obsidian vault, and uses that durable context to generate blog, portfolio, resume, todo, and worklog drafts. The original BlogAgent implementation is still kept as an output agent; the new center is the Obsidian vault and Wiki Core.

The detailed refactoring plan lives in [docs/architecture.md](docs/architecture.md).

## Current Phase

This branch implements Phase 1 through Phase 4 of the LLM Wiki Core refactor:

- Phase 1: docs and settings now describe Obsidian LLM Wiki Core as the project center.
- Phase 2: `work-agent init-vault` creates the base vault structure.
- Phase 3: `work-agent index-vault` parses Markdown/frontmatter/wiki links and updates `index.md`; `work-agent search` performs simple keyword search.
- Phase 4: `work-agent capture`, `capture-chat`, `capture-commit`, and `daily-log` store raw traces in safe vault areas and append `log.md`.

Existing BlogAgent, Notion, Telegram, Tistory export, and document agents are preserved.

## Core Commands

```bash
work-agent init-vault
work-agent index-vault
work-agent search "RAG"
work-agent capture "오늘 작업 메모" --project WorkAgent
work-agent capture-chat --source chatgpt --project WorkAgent --file chat.md
work-agent capture-commit --repo . --project WorkAgent
work-agent daily-log
```

Legacy and output-agent commands still exist:

```bash
work-agent ask "오늘 작업 회고 정리해줘"
work-agent suggest-topics
work-agent list
work-agent write-draft "주제"
work-agent revise latest
work-agent preview latest
work-agent export-tistory latest
work-agent publish-done latest --url "https://..."
work-agent sync-notion
work-agent worklog
work-agent todo
work-agent portfolio
work-agent resume
work-agent serve-bot
work-agent push-digest
```

The older experimental LLM wiki commands are also kept:

```bash
work-agent wiki-ingest
work-agent wiki-query "질문"
work-agent wiki-lint
```

## Environment

Copy `.env.example` to `.env` and fill only what you need.

For Phase 1-3 Wiki Core commands, the important setting is:

```env
OBSIDIAN_VAULT_PATH=C:/Users/username/Documents/ObsidianVault
```

`OBSIDIAN_VAULT_DIR` is still supported for compatibility, but `OBSIDIAN_VAULT_PATH` is preferred.

LLM-backed commands such as `write-draft`, `suggest-topics`, and `ask` still require `LLM_PROVIDER`. Notion is now treated as legacy optional state tracking; set `LEGACY_NOTION_ENABLED=true` only when you want the old Notion Blog DB integration to use real API keys.

## Vault Shape

`init-vault` creates this base structure without overwriting existing notes:

```text
00_Inbox/
10_Worklog/
20_Knowledge/
30_Projects/
40_AgentMemory/
50_Outputs/
60_Candidates/
90_Templates/
index.md
log.md
AGENTS.md
```

Writable areas for agents:

```text
00_Inbox/
10_Worklog/
50_Outputs/Blog/Drafts/
50_Outputs/Portfolio/
50_Outputs/Resume/
50_Outputs/Interview/
60_Candidates/
```

Protected areas should be changed through candidates or patches:

```text
20_Knowledge/
40_AgentMemory/Core/
30_Projects/*/Context.md
```

## Development

Run tests with:

```bash
.venv\Scripts\python.exe -m pytest -q
```

On Windows, if the default temp directory is not writable, set `TMP` and `TEMP` to a workspace-local folder before running pytest.
