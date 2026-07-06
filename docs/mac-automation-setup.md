# Mac 자동화 설정 가이드

macOS에서 devtrail을 24시간 자동 실행하는 설정 방법. Windows 버전은
`docs/old/server-automation.md` 참고. Mac을 처음 써본다는 전제로 터미널
기초부터 순서대로 정리했다.

---

## 0. 터미널 기초

- **터미널 앱 열기**: `Cmd + Space` → "터미널" 입력 → Enter. (Windows의 PowerShell과
  같은 역할. 이 문서의 모든 명령어는 이 터미널 창에 입력한다.)
- **기본 명령어 대응표**:

  | 하는 일 | Windows(PowerShell) | Mac(터미널, bash/zsh) |
  |---|---|---|
  | 현재 위치 확인 | `pwd` | `pwd` |
  | 폴더 목록 | `dir` / `ls` | `ls` |
  | 폴더 이동 | `cd 경로` | `cd 경로` |
  | 폴더 생성 | `mkdir 이름` | `mkdir 이름` |
  | 홈 폴더 | `$HOME` (`C:\Users\사용자명`) | `~` (`/Users/사용자명`) |
  | 경로 구분자 | `\` | `/` |
  | 스크립트 실행 | `powershell -File x.ps1` | `bash x.sh` |

- macOS 기본 터미널 셸은 zsh다. 이 가이드의 명령어는 bash/zsh 둘 다에서 그대로 동작한다.
- 명령어 실행 중 `Password:`가 뜨면 로그인 비밀번호를 입력하는 것 — 입력해도 화면에
  글자가 안 보이는 게 정상이다. 입력 후 Enter.

---

## 1. 사전 준비

### 1-1. Xcode Command Line Tools 설치 (git 포함)

```bash
xcode-select --install
```

팝업이 뜨면 "설치" 클릭. 몇 분 걸린다. 이미 설치돼 있으면
`xcode-select: error: command line tools are already installed` 메시지가 뜨는데,
정상이니 다음 단계로 넘어가면 된다.

### 1-2. Homebrew 설치 (macOS 패키지 매니저 — Windows의 winget/choco 같은 것)

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

설치가 끝나면 터미널에 PATH 등록 안내 문구가 나온다. Apple Silicon(M1/M2/M3 등) Mac
이면 아래를 실행해 반영한다:

```bash
echo 'eval "$(/opt/homebrew/bin/brew shellenv)"' >> ~/.zprofile
eval "$(/opt/homebrew/bin/brew shellenv)"
```

인텔 Mac이면 경로가 `/usr/local/bin/brew`다. 터미널을 새로 열거나 위 `eval` 줄을
다시 실행하면 반영된다. 확인:

```bash
brew --version
```

### 1-3. Python 3.11+ 설치

```bash
brew install python@3.11
```

확인:

```bash
python3.11 --version
```

### 1-4. 레포 클론

```bash
git clone https://github.com/WhiteJbb/devtrail.git ~/devtrail
cd ~/devtrail
```

### 1-5. Obsidian Vault 클론

Vault가 git으로 관리되고 있다면:

```bash
git clone https://github.com/WhiteJbb/personal-vault.git ~/devtrail-vault
```

위처럼 홈 바로 아래(`~/devtrail-vault`)에 두는 것을 권장한다. 데스크톱·문서·
iCloud Drive 등 macOS 보호 폴더에 두면 launchd 자동 실행 시 권한 오류가 난다
(8번 트러블슈팅의 "Operation not permitted" 항목 참고).

---

## 2. venv 생성 + 패키지 설치

```bash
cd ~/devtrail
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e .
devtrail --help
```

`devtrail --help`에서 명령 목록이 뜨면 정상이다. `command not found: devtrail`이
뜨면 `source .venv/bin/activate`를 안 했거나 venv 생성이 실패한 것이니 위 단계를
다시 확인한다.

(참고: `source .venv/bin/activate`로 활성화한 venv는 그 터미널 창에만 적용된다.
새 터미널 창을 열면 다시 activate 해야 하지만, 이후 automation 스크립트들은
venv를 activate하지 않고도 `.venv/bin/devtrail` 절대경로로 직접 실행하도록
작성돼 있어 자동화 자체에는 영향 없다.)

---

## 3. `.env` 설정

`~/devtrail/.env` 파일을 만들고 아래 내용을 채운다 (Windows `.env.example`과 항목은 동일,
경로만 Mac 형식):

```env
OBSIDIAN_VAULT_PATH=/Users/사용자명/devtrail-vault

TELEGRAM_BOT_TOKEN=<봇 토큰>
TELEGRAM_CHAT_ID=<채팅 ID>

# LLM (택1)
LLM_PROVIDER=gemini
GEMINI_API_KEY=<키>

# LLM_PROVIDER=openai
# OPENAI_API_KEY=<키>
```

터미널에서 파일을 만들려면:

```bash
nano .env
```

내용을 붙여넣고 `Ctrl+O` → Enter(저장) → `Ctrl+X`(종료).

---

## 4. 스크립트 수동 테스트 (launchd 등록 전에 먼저 확인)

```bash
bash scripts/mac/update-devtrail.sh
bash scripts/mac/sync-vault.sh
bash scripts/mac/run-nightly-safe.sh   # LLM 호출 포함, 수 분 소요
```

로그는 `~/devtrail/logs/`에 쌓인다. `sync-vault.sh`는 로컬/원격 변경이 없으면
"Nothing to sync."만 출력하고 끝나는 게 정상이다.

---

## 5. launchd 등록 (Windows Task Scheduler에 대응)

macOS에는 Task Scheduler가 없고 대신 **launchd**를 쓴다. 이 레포의 등록 스크립트는
사용자 로그인 세션 기준으로 동작하는 `~/Library/LaunchAgents`에 설치한다.

### 옵션 A — 전체 자동화 (봇 + update + vault-sync + nightly + weekly + 알림 2개)

```bash
bash scripts/mac/register-schedules.sh
```

7개 작업이 등록된다:

| 작업 | 주기 |
|---|---|
| `com.devtrail.bot` | 로그인 시 시작, 죽으면 자동 재시작 |
| `com.devtrail.update` | 10분마다 |
| `com.devtrail.vault-sync` | 10분마다 |
| `com.devtrail.nightly` | 매일 23:30 |
| `com.devtrail.weekly` | 매주 일요일 18:00 |
| `com.devtrail.notify-morning` | 매일 08:00 |
| `com.devtrail.notify-evening` | 매일 21:30 |

### 옵션 B — vault 동기화만 (가벼운 로컬 용도)

```bash
bash scripts/mac/register-local.sh
```

`com.devtrail.vault-sync-local` 하나만 10분마다 등록된다.

### 등록 확인

```bash
launchctl list | grep devtrail
```

각 줄의 두 번째 칸이 최근 종료 코드다. `-`는 아직 한 번도 안 돌았다는 뜻(정상,
StartInterval/StartCalendarInterval 대기 중), `0`은 정상 종료, 그 외 숫자는 실패다.

### 삭제

```bash
launchctl unload ~/Library/LaunchAgents/com.devtrail.bot.plist             && rm ~/Library/LaunchAgents/com.devtrail.bot.plist
launchctl unload ~/Library/LaunchAgents/com.devtrail.update.plist          && rm ~/Library/LaunchAgents/com.devtrail.update.plist
launchctl unload ~/Library/LaunchAgents/com.devtrail.vault-sync.plist      && rm ~/Library/LaunchAgents/com.devtrail.vault-sync.plist
launchctl unload ~/Library/LaunchAgents/com.devtrail.nightly.plist         && rm ~/Library/LaunchAgents/com.devtrail.nightly.plist
launchctl unload ~/Library/LaunchAgents/com.devtrail.weekly.plist          && rm ~/Library/LaunchAgents/com.devtrail.weekly.plist
launchctl unload ~/Library/LaunchAgents/com.devtrail.notify-morning.plist  && rm ~/Library/LaunchAgents/com.devtrail.notify-morning.plist
launchctl unload ~/Library/LaunchAgents/com.devtrail.notify-evening.plist  && rm ~/Library/LaunchAgents/com.devtrail.notify-evening.plist
```

### 스크립트/설정을 고친 뒤 다시 적용하려면

plist 내용(주기 등)을 바꿨으면 등록 스크립트를 다시 실행하면 된다(내부적으로
`launchctl unload` 후 `load`를 다시 한다):

```bash
bash scripts/mac/register-schedules.sh
```

---

## 6. 절전 방지 (중요 — 이거 안 하면 Mac이 잠들 때 자동화도 멈춘다)

Windows Task Scheduler는 태스크별로 "배터리에서도 실행" 옵션이 있었지만, Mac은
시스템 자체가 잠들면(sleep) launchd 예약도 그 시간 동안 돌지 않는다. 노트북이면
화면을 닫는 것만으로도 잠든다.

**GUI로 설정** (권장): 설정(시스템 설정) → 잠금 화면 → "디스플레이가 꺼져있을 때
자동으로 잠자기 안 함" 켜기. 또는 배터리/에너지 설정에서 "절전 모드" 관련 항목을
"안 함"으로.

**터미널로 설정**: (관리자 비밀번호 필요)

```bash
sudo pmset -a sleep 0        # 시스템 절전 안 함
sudo pmset -a disksleep 0    # 디스크 절전 안 함
```

화면만 꺼지고(`displaysleep`) 시스템은 안 자는 상태로 두면 되므로 `displaysleep`은
건드리지 않아도 된다. 노트북이면 뚜껑을 닫으면 위 설정과 무관하게 잠드니, 항상 켜둘
Mac이라면 뚜껑을 열어두거나 외장 모니터를 연결해 "클램셸 모드"로 두는 방법을 쓴다.

확인:

```bash
pmset -g
```

---

## 7. Telegram 봇 테스트

```bash
/start          — help 출력
/capture 테스트  — 메모 저장
/sync           — 수동 vault 동기화
URL 붙여넣기     — URL 캡처 + LLM 요약
```

봇을 수동으로 먼저 확인하고 싶으면:

```bash
source .venv/bin/activate
devtrail serve-bot
```

---

## 8. 트러블슈팅

### `command not found: devtrail`

venv를 activate 안 했거나, launchd/스크립트가 `.venv/bin/devtrail`을 못 찾는 것.
`ls ~/devtrail/.venv/bin/devtrail`로 실제로 파일이 있는지 먼저 확인.

### launchd에 등록은 됐는데 안 도는 것 같음

```bash
launchctl list | grep devtrail
cat ~/devtrail/logs/launchd-*.err.log
```

`launchd-*.err.log`/`launchd-*.out.log`는 launchd가 스크립트를 실행한 시스템
레벨 출력이고, `logs/nightly.log` 등은 스크립트 자체가 남긴 로그다. 둘 다 확인.

### "Operation not permitted" 같은 권한 오류 (TCC)

Vault가 iCloud Drive, 데스크톱, 문서, 다운로드 등 macOS가 보호하는 위치에 있으면
git 명령이 `Operation not permitted`로 실패한다. 자동화에서 특히 헷갈리는 이유:

- macOS 권한(TCC)은 **접근을 시도한 프로세스별로** 부여된다.
- 터미널에서 수동 실행 → Terminal.app의 권한을 따른다.
- launchd가 실행 → Terminal.app과 무관하게 `/bin/bash` 자체의 권한을 따른다.

그래서 **"수동으로 돌리면 되는데 launchd로만 돌리면 실패"** 하는 증상이 나온다.
터미널에 전체 디스크 접근 권한을 줘도 launchd 실행에는 효과가 없다. 실패 여부는
`~/devtrail/logs/launchd-*.err.log`에 `Operation not permitted`가 찍히는지로 확인한다.

**해결 방법 1 — Vault를 보호 폴더 밖에 두기 (권장)**

이 가이드의 기본 경로(`~/devtrail-vault`, 홈 바로 아래)는 보호 대상이 아니라서
문제 자체가 생기지 않는다. Vault가 데스크톱/문서/iCloud에 있다면 홈 아래로 옮기고
`.env`의 `OBSIDIAN_VAULT_PATH`만 고치는 것이 가장 깔끔하다. 권한 설정 관리가
필요 없고, macOS 업데이트로 TCC 동작이 바뀌어도 영향이 없다.

**해결 방법 2 — 프로세스에 전체 디스크 접근 권한 부여**

Vault 위치를 옮길 수 없을 때만 사용한다. 설정 → 개인정보 보호 및 보안 →
전체 디스크 접근 권한에서 `+`를 누르고:

- 터미널 수동 실행용: 응용 프로그램 → 유틸리티 → "터미널" 추가 후 터미널 재시작.
- launchd 자동 실행용: 파일 선택 창에서 `Cmd + Shift + G` → `/bin` 입력 →
  `bash` 선택. (launchd 작업은 재시작할 필요 없이 다음 주기 실행부터 적용된다.)

단, `/bin/bash`에 전체 디스크 접근을 주면 이 Mac에서 bash로 실행되는 **모든**
스크립트가 그 권한을 갖게 되므로 보안상 부여 범위가 넓다. 가능하면 해결 방법 1을
먼저 검토할 것.

### plist 문법을 직접 고쳤는데 로드가 안 됨

```bash
plutil -lint ~/Library/LaunchAgents/com.devtrail.nightly.plist
```

오류 위치를 알려준다. 가능하면 `scripts/mac/launchd/*.plist.template`을 고치고
`register-schedules.sh`를 다시 실행하는 쪽을 권장한다(직접 수정한 결과물은 다음
등록 스크립트 실행 시 덮어써진다).

### Mac이 잠들었다 깨어난 직후 여러 작업이 한꺼번에 도는 것 같다

launchd는 시스템이 잠들어 있던 동안 놓친 `StartCalendarInterval`을 깨어난 직후
한 번에 몰아서 실행하는 catch-up 동작이 있다. 완전한 24시간 무인 서버로 쓰려면
6번의 절전 방지 설정이 필수다.

### nightly 실패 후 `.nightly.lock` 파일이 안 지워짐

4시간 지나면 다음 실행 때 자동으로 정리된다. 바로 풀고 싶으면:

```bash
rm ~/devtrail/.nightly.lock
```

### Vault git 충돌

`sync-vault.sh`/`sync-vault-local.sh`가 충돌을 감지하면 중단하고 Telegram으로
알린다. 수동으로 해결:

```bash
cd ~/devtrail-vault
git status
# 충돌 해결 후
git add .
git commit
```
