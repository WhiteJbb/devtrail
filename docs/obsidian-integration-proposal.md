# Obsidian 연동 설계 제안

> 상태: **제안(미구현)**. 구현 결정 시 이 문서를 기준으로 진행한다.
> 결정 사항: Obsidian과 Notion을 **나란히 선택적인 소스**로 둔다(둘 다 켜져 있으면 둘 다 읽음).

## 배경 / 왜 잘 맞나

이 프로젝트는 이미 **마크다운 + frontmatter를 단일 진실원천(SOT)** 으로 쓰고, `content_sources` / `storage` 계층이 분리돼 있다. Obsidian 볼트는 결국 **frontmatter 달린 `.md` 파일 폴더**이므로 거의 "끼우기만" 하면 된다.

- **API·키·네트워크 불필요** — Notion real client는 아직 실연결 검증 전인데, Obsidian은 파일 read/write라 단순하고 확실하다.
- **변환 손실 0** — Notion은 블록→마크다운 변환·속성 매핑이 필요했지만 Obsidian은 마크다운+frontmatter 네이티브라 임피던스 미스매치가 없다.
- **git 친화적** — 볼트를 git 저장소로 두면 `git_source`와 한 몸이 된다.
- **태그/폴더 필터** — `#blog-idea`, `#worklog` 태그나 폴더로 입력 소스를 고를 수 있다.
- **편집 UI 공짜** — 드래프트를 볼트 안에 저장하면 Obsidian이 그대로 초안 편집기가 된다(`status: draft→review` 같은 frontmatter가 Obsidian 속성으로 보임).

## 핵심 원칙

Obsidian은 서버가 없으니 "연동 = 볼트 폴더 read/write". 기존 계층에 **파일 기반 소스 하나**를 더하는 것이고, Notion 계층은 그대로 둔다.

## 1) 입력 — `ObsidianSource` (content_sources)

- 위치: `app/content_sources/obsidian_source.py`, `ContentSource` 프로토콜 구현 → `SourceChunk[]` 반환(기존 패턴 그대로)
- 동작: `OBSIDIAN_VAULT_DIR` 아래 `.md` 노트를 읽어 frontmatter 제거 후 본문을
  `SourceChunk(source_type="obsidian", ref=상대경로, title=노트명, text=본문)` 으로 변환
- 필터(선택): `OBSIDIAN_TAGS`(예: `blog-idea,worklog`) 또는 `OBSIDIAN_FOLDERS`로 관련 노트만.
  frontmatter `tags:` 또는 본문 `#tag` 파싱
- 확장(선택): 노트 안 `[[위키링크]]`를 1-depth 따라가 관련 노트도 컨텍스트에 포함
- 배선: `app/agents/context_builder.py`의 `build_source_collector`에 한 줄 추가
  → **모든 Agent(블로그/회고/할일/포폴/이력서)가 자동으로 Obsidian도 근거로 사용**

## 2) 출력/편집 — 드래프트를 볼트 안에

- **코드 변경 없음.** `WORKSPACE_DIR`(또는 drafts 경로)을 볼트 안 폴더로 지정하면 끝
- 효과: 생성·`revise`한 초안이 볼트에 생기고 Obsidian이 그대로 편집기가 됨.
  `status: idea→draft→review→published`가 Obsidian 속성으로 표시
- `list` 명령이 그 폴더를 스캔하므로 상태 관리도 그대로 동작

## 3) 설정 (.env, 전부 optional)

```env
OBSIDIAN_VAULT_DIR=            # 비우면 Obsidian 비활성
OBSIDIAN_TAGS=blog-idea,worklog
OBSIDIAN_FOLDERS=
```

→ Notion처럼 "비우면 꺼짐, 채우면 켜짐". Notion과 **공존**.

## 흐름

```
Obsidian 노트 ┐
로컬 docs     ├─→ 수집 → 초안 ──(볼트 안 저장)──→ Obsidian에서 편집 → export-tistory
Git/Notion    ┘
```

## 작업량 / 리스크

- `ObsidianSource` + config + `context_builder` 한 줄 + 테스트(로컬 파일이라 mock 불필요, tmp 볼트로 실테스트)
  → **반나절 분량, 작은 PR 하나**
- 리스크 낮음(네트워크/키 없음)
- 유일한 과제: **이미지 임베드**(`![[img.png]]`)를 티스토리 export에서 어떻게 처리할지 — 별도 작업으로 분리

## 구현 시 체크리스트

- [ ] `app/content_sources/obsidian_source.py` (`ObsidianSource`)
- [ ] `app/config.py` — `OBSIDIAN_VAULT_DIR` / `OBSIDIAN_TAGS` / `OBSIDIAN_FOLDERS` + `.env.example`
- [ ] `app/agents/context_builder.py` — 소스 목록에 추가(설정 시에만)
- [ ] tests — tmp 볼트로 읽기/필터 검증
- [ ] README — Obsidian 섹션(입력 소스 + 볼트 안 드래프트 설정 가이드)
- [ ] (후속) 이미지 `![[...]]` → 티스토리 export 처리
