# CLI 이름 변경: work-agent → devtrail

저장소 이름(devtrail)과 CLI 이름(work-agent)이 달라 문서·설정에 두 이름이 섞여 있고,
MCP 서버명(`work-agent-vault`)까지 더해 이름이 3개가 된 상태를 정리한다.
**별칭 없이 한 번에 전부 교체**하는 방향으로 결정했다(외부 세팅은 어차피 재등록).

## 진행 조건과 순서

- **`docs/vault-mcp-fix-plan.md`의 P1~P5가 끝난 뒤** 별도 브랜치(`refactor/rename-devtrail`)에서
  진행한다. fix-plan이 `work-agent project-briefing` 등 옛 이름 기준으로 쓰여 있으므로
  순서를 지켜야 문서와 코드가 어긋나지 않는다.
- 버그 픽스 커밋과 절대 섞지 않는다. 리네임 커밋은 기계적 치환이라 diff가 크므로
  기능 변경이 한 줄이라도 섞이면 리뷰가 불가능해진다.
- **0단계(스케줄러 정지)를 코드 변경보다 먼저** 해야 한다. `work-agent-update` 작업이
  10분마다 git pull + 재설치를 수행하므로, 실행 중에 리네임 커밋이 내려가면 옛 작업
  정의가 새 스크립트 경로를 찾지 못해 어중간하게 깨진다.

## 0. 준비 — 기존 스케줄러 작업 정지/삭제 (사람이 실행)

관리자 PowerShell에서:

```powershell
schtasks /Delete /TN work-agent-bot             /F
schtasks /Delete /TN work-agent-update          /F
schtasks /Delete /TN work-agent-vault-sync      /F
schtasks /Delete /TN work-agent-nightly         /F
schtasks /Delete /TN work-agent-weekly          /F
schtasks /Delete /TN work-agent-notify-morning  /F
schtasks /Delete /TN work-agent-notify-evening  /F
# register-local.ps1을 쓴 머신이면 추가로:
Unregister-ScheduledTask -TaskName work-agent-vault-sync -Confirm:$false
# 떠 있는 봇 프로세스 종료
taskkill /F /IM work-agent.exe /T
```

## 1. 코드 일괄 변경 (Sonnet 작업 범위)

원칙: `work-agent` → `devtrail`, `work_agent` → `devtrail`, `WorkAgent` → `Devtrail`,
`work-agent-vault`(MCP 서버명) → `devtrail-vault`, 스케줄러 작업명 `work-agent-*` →
`devtrail-*`. **`docs/old/`는 과거 기록이므로 건드리지 않는다.**

### 1.1 패키지/엔트리포인트

- `pyproject.toml`: `name = "work-agent"` → `"devtrail"`,
  `[project.scripts]`의 `work-agent = "app.cli:app"` → `devtrail = "app.cli:app"`.

### 1.2 애플리케이션 코드

- `app/cli.py` — help/echo 텍스트의 명령 예시 (`work-agent mcp-serve`, `claude mcp add ...` 등).
- `app/mcp_server.py` — `FastMCP("work-agent-vault")` → `FastMCP("devtrail-vault")`,
  docstring의 등록 예시.
- `app/messaging/bot.py` — 사용자에게 보이는 안내 메시지.
- `app/prompts/distill_candidates.md` — 프롬프트 본문 내 언급.
- `app/services/wiki_service.py` — 템플릿/로그 문자열 내 언급.
- `dashboard.py`, `start.py`, `start.ps1`, `install.ps1`
  (`work-agent.exe` 경로 → `devtrail.exe`, 출력 문구, `--project WorkAgent` 예시 →
  `--project Devtrail`).
- `tests/test_smoke_pipeline.py` — 참조 문자열.

### 1.3 스케줄러/운영 스크립트

- `scripts/register-schedules.ps1` — 작업명 7개 전부 `devtrail-*`로, 등록/삭제/조회
  루프와 하단 안내 문구까지. `update-work-agent.ps1` 경로 참조도 새 파일명으로.
- `scripts/update-work-agent.ps1` → **파일명을 `scripts/update-devtrail.ps1`로 변경**
  (`git mv`), 내부의 로그 파일명(`logs/update-work-agent.log` → `logs/update-devtrail.log`),
  `taskkill /F /IM work-agent.exe` → `devtrail.exe`, 주석/로그 문구.
- `scripts/run-bot-service.ps1` — `.venv\Scripts\work-agent.exe` → `devtrail.exe`.
- `scripts/register-local.ps1`, `scripts/sync-vault.ps1`, `scripts/run-nightly-safe.ps1`,
  `scripts/run-weekly-safe.ps1`, `scripts/run-notify.ps1` — 작업명/실행 파일/문구.
- `scripts/hooks/session-start-briefing.ps1`, `scripts/hooks/stop-process-check.ps1`,
  `scripts/hooks/print_briefing.py`(fix-plan 4.4에서 CLI 커맨드로 대체됐다면 해당 커맨드
  호출부) — 주석의 등록 예시 포함.

### 1.4 문서

- `README.md`, `AGENTS.md`, `CLAUDE.md`, `.claude/global.md`
- `docs/service-improvement-plan.md`, `docs/vault-mcp-implementation-summary.md`,
  `docs/vault-mcp-fix-plan.md` — 명령 예시를 새 이름으로.
- `docs/old/` **제외**.

### 1.5 변경 후 검증 (코드 단계)

```powershell
# 남은 참조가 docs/old/ 뿐인지 확인 (0건이어야 하는 위치에서 발견되면 수정)
git grep -il "work-agent" -- ':!docs/old'
git grep -il "work_agent" -- ':!docs/old'
git grep -il "WorkAgent"  -- ':!docs/old'
py -3.11 -m pytest -q   # 기존 실패 15개 외 추가 실패 없음
```

## 2. 재설치 (사람이 실행)

패키지 **이름**이 바뀌므로 pip 입장에선 다른 패키지다 — 옛것을 먼저 제거해야
`work-agent.exe`가 venv에 잔존하지 않는다:

```powershell
.\.venv\Scripts\pip uninstall work-agent -y
.\.venv\Scripts\pip install -e .
Get-Command devtrail        # devtrail.exe 확인
Get-Command work-agent      # "not recognized"여야 정상
devtrail --help
```

## 3. 외부 세팅 재등록 (사람이 실행)

1. **스케줄러**: 갱신된 `scripts/register-schedules.ps1` 실행 → `devtrail-*` 작업 7개 확인.
   (로컬 머신이면 `register-local.ps1`.)
2. **MCP**:
   ```
   claude mcp remove work-agent-vault
   claude mcp add devtrail-vault -- devtrail mcp-serve
   ```
   Claude Desktop을 쓰면 `claude_desktop_config.json`의 `mcpServers` 키도
   `devtrail-vault` / `command: "devtrail"`로 수정.
3. **전역 CLAUDE.md** (`C:\Users\admin\.claude\CLAUDE.md` — 레포 밖이라 코드로 못 고침):
   capture-session rule의 실행 패턴을 `devtrail capture-session --project <프로젝트명>
   --from-repo --from-agent --summary-file ./session-summary.md`로 수정.
4. **Telegram 봇**: `devtrail-bot` 작업이 재등록되면 자동 기동. 수동 확인은
   `devtrail serve-bot`.

## 4. 최종 검증 체크리스트

- [ ] `devtrail --help`, `devtrail mcp-serve`(Ctrl+C로 종료), `devtrail push-digest --daily --dry-run`(있다면) 동작
- [ ] `schtasks /Query | findstr devtrail` — 7개 작업 존재, `findstr work-agent` — 0건
- [ ] 새 Claude 세션에서 `devtrail-vault` MCP tool 목록 확인 (`get_project_briefing` 호출)
- [ ] Telegram 봇 응답 확인 (`/help`)
- [ ] 다음 nightly(23:30) 이후 `logs/` 에 새 로그 파일 생성 확인

## 범위 제외 / 주의

- **Vault 데이터는 리네임하지 않는다** — `30_Projects/WorkAgent/` 같은 vault 폴더나
  기존 노트의 project 필드는 그대로 둔다. vault 프로젝트명 변경은 노트 이력 전체에
  영향이 있어 원하면 별도 결정.
- git 저장소/브랜치/과거 커밋 메시지는 당연히 그대로.
- `logs/update-work-agent.log` 등 기존 로그 파일은 지우지 말고 그대로 두면 된다
  (새 로그는 새 이름으로 쌓임).

## 롤백

코드 커밋 revert 후 §2를 역방향으로(`pip uninstall devtrail` → `pip install -e .`),
§0/§3의 작업을 옛 이름으로 재등록하면 된다. 스케줄러 작업 정의는 스크립트로 재생성
가능하므로 백업 불필요.
