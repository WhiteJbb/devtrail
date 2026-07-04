# 서버 자동화 설정 가이드

24시간 서버(Windows)에서 work-agent를 자동 실행하는 설정 방법.

---

## 구조 개요

```
10분마다: update-work-agent.ps1   — 코드 최신화
10분마다: sync-vault.ps1          — Vault git 동기화 (pull/push)
매일 23:30: run-nightly-safe.ps1  — 전체 파이프라인 실행
```

nightly 실행 중에는 `.nightly.lock` 파일로 sync-vault 스케줄 실행을 차단한다.
nightly 내부에서 sync-vault를 호출할 때는 `-Internal` 플래그로 lock 체크를 건너뜀.

---

## 1. 사전 준비

### 1-1. 레포 클론

```powershell
git clone https://github.com/<user>/work-agent C:\work\work-agent
cd C:\work\work-agent
```

### 1-2. Vault 클론 (Obsidian vault가 git으로 관리되는 경우)

```powershell
git clone https://github.com/<user>/vault D:\vault
```

remote가 없으면 `git init` 후 remote 추가.

---

## 2. 설치

```powershell
powershell -ExecutionPolicy Bypass -File C:\work\work-agent\install.ps1
```

완료 후 Step 5에서 `OBSIDIAN_VAULT_PATH` 값이 올바르게 출력되는지 확인.

---

## 3. .env 설정

`C:\work\work-agent\.env` 파일에 아래 항목 입력:

```env
OBSIDIAN_VAULT_PATH = D:\vault

TELEGRAM_BOT_TOKEN  = <봇 토큰>
TELEGRAM_CHAT_ID    = <채팅 ID>

# LLM (택1)
LLM_PROVIDER        = gemini
GEMINI_API_KEY      = <키>

# LLM_PROVIDER     = openai
# OPENAI_API_KEY   = <키>
```

---

## 4. 스크립트 수동 테스트 (순서대로)

Task Scheduler 등록 전에 각 스크립트가 정상 동작하는지 확인한다.

```powershell
# 코드 업데이트 확인
powershell -ExecutionPolicy Bypass -File C:\work\work-agent\scripts\update-work-agent.ps1

# Vault 동기화 (로컬/리모트 변경 없으면 "Nothing to sync" 출력)
powershell -ExecutionPolicy Bypass -File C:\work\work-agent\scripts\sync-vault.ps1

# nightly 전체 파이프라인 (LLM 호출 포함, 수 분 소요)
powershell -ExecutionPolicy Bypass -File C:\work\work-agent\scripts\run-nightly-safe.ps1
```

로그 위치: `C:\work\work-agent\logs\`

---

## 5. Task Scheduler 등록

**관리자 PowerShell**에서 실행:

```powershell
powershell -ExecutionPolicy Bypass -File C:\work\work-agent\scripts\register-schedules.ps1
```

등록되는 작업:

| 작업명 | 주기 | 스크립트 |
|--------|------|---------|
| `work-agent-update` | 10분마다 | `update-work-agent.ps1` |
| `work-agent-vault-sync` | 10분마다 | `sync-vault.ps1` |
| `work-agent-nightly` | 매일 23:30 | `run-nightly-safe.ps1` |
| `work-agent-weekly` | 매주 금요일 23:00 | `work-agent weekly-distill` |

등록 확인:

```powershell
schtasks /Query /TN "work-agent-nightly" /FO LIST
```

삭제:

```powershell
schtasks /Delete /TN work-agent-update     /F
schtasks /Delete /TN work-agent-vault-sync /F
schtasks /Delete /TN work-agent-nightly    /F
schtasks /Delete /TN work-agent-weekly     /F
```

---

## 6. Telegram 봇 테스트

봇을 실행한 뒤 아래 명령으로 서버 연결을 확인한다:

```
/start          — help 출력
/capture 테스트  — 메모 저장
/sync           — 수동 vault 동기화
URL 붙여넣기     — URL 캡처 + LLM 요약
```

봇 실행:

```powershell
# 새 터미널에서
C:\work\work-agent\.venv\Scripts\work-agent.exe run-bot
```

또는 `launch.bat`으로 대시보드 실행 후 봇 시작.

---

## 7. PowerShell 실행 정책 (서버 최초 1회)

스크립트가 "실행 불가" 오류가 나면:

```powershell
Set-ExecutionPolicy RemoteSigned -Scope CurrentUser
```

Task Scheduler에서는 `-ExecutionPolicy Bypass`를 명시하므로 별도 설정 불필요.

---

## 트러블슈팅

### 한글 깨짐 / 파싱 오류 (NativeCommandError, 종결자 없음)

PowerShell 5.1이 UTF-8 파일을 BOM 없이 읽으면 CP949로 해석해 파싱 오류 발생.

**증상**: `문자열에 " 종결자가 없습니다`, `NativeCommandError`

**확인**:
```powershell
$bytes = [System.IO.File]::ReadAllBytes("C:\work\work-agent\install.ps1")
$bytes[0..2]  # 239 187 191 (= EF BB BF) 이어야 BOM 있음
```

**수정** (레포 최신 버전 pull 후 자동 해결):
```powershell
git pull
```

직접 BOM을 추가하려면:
```python
# Python으로 BOM 추가
with open('install.ps1', 'rb') as f: data = f.read()
if data[:3] != b'\xef\xbb\xbf':
    with open('install.ps1', 'wb') as f: f.write(b'\xef\xbb\xbf' + data)
```

### sync-vault.ps1 — "Nothing to sync"만 출력

정상 동작. 로컬/리모트 변경이 없을 때 조기 종료.

### nightly 실패 후 lock 파일 잔류

4시간 경과 후 자동 제거. 즉시 해제하려면:
```powershell
Remove-Item C:\work\work-agent\.nightly.lock -Force
```

### Vault git 충돌

`sync-vault.ps1`이 충돌 감지 시 중단하고 Telegram 알림 전송.
수동으로 vault 디렉토리에서 충돌 해결 후 재실행:
```powershell
cd D:\vault
git status        # 충돌 파일 확인
# 편집기로 충돌 해결 후
git add .
git rebase --continue
```
