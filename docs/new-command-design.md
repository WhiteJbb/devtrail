# Telegram LLM 자연어 연동 + `/new` 세션 리셋 설계

작성일: 2026-06-25

두 가지 설계를 함께 다룬다.
1. **Telegram LLM 자연어 연동** — 의도 분류 전용에서 실제 대화 가능한 구조로 확장
2. **`/new` 세션 리셋** — 대화 히스토리를 지우되 활성 태스크 + 에이전트 메모리는 유지

---

## Part 1. Telegram LLM 자연어 연동

---

## 1. 현재 상태 — 무엇이 부족한가

현재 `Assistant`는 LLM을 **의도 분류 한 번**에만 사용한다.

```
자유 문장 → interpret() [LLM: JSON 의도 분류] → command 확인 → execute
                                              → unknown → help 텍스트 반환
```

문제:
- "LLM 라우터 설계 어디까지 됐어?" 같은 질문은 `unknown`으로 분류돼 help 텍스트가 나온다.
- 대화 히스토리가 없어 맥락 없는 단발성 응답만 가능하다.
- LLM이 프로젝트 컨텍스트를 모른다 (시스템 프롬프트 없음).

---

## 2. 목표 — 자연스러운 대화

```
자유 문장 → 의도 분류 [light task]
              → 알려진 명령 → (파괴적이면 확인 후) execute
              → 모르는 질문/대화 → chat() [writer task, 히스토리 + 컨텍스트 포함]
```

예시 비교:

| 입력 | 현재 | 목표 |
|---|---|---|
| "오늘 할 일 알려줘" | todo 명령 실행 | 동일 |
| "LLM 라우터 어디까지 됐어?" | help 텍스트 | LLM이 컨텍스트 기반으로 직접 답변 |
| "Kimi provider 어떻게 연결돼?" | help 텍스트 | 코드 구조 설명 |
| "아까 말한 fallback 이슈 해결 방법은?" | help 텍스트 | 이전 대화 참조해서 답변 |

---

## 3. 아키텍처 — 2단계 라우팅

```
MessengerBot._handle_text()
    │
    ├─ /slash → CommandRouter (변경 없음)
    │
    └─ 자유 문장
           │
           ▼
     Assistant.route(text, history)
           │
           ├─ command 확인 → [파괴적?] → 확인 메시지 → execute()
           │                           → 안전함 → 즉시 execute()
           │
           └─ unknown / 대화형 → Assistant.chat(text, history)
                                       LLM에 히스토리 + 시스템 컨텍스트 포함
```

핵심 변경:
- `interpret()` 결과가 `unknown`이면 `help_text()` 대신 `chat()` 호출
- `chat()`은 `_history`와 system context를 포함해 LLM에 전달
- 히스토리는 `MessengerBot` 이 chat_id별로 관리

---

## 4. 히스토리 구조

`MessengerBot` 에 추가:

```python
_history: dict[str, list[dict]]  # chat_id → [{"role": "user"|"assistant", "content": str}]
```

- 각 대화 턴마다 user/assistant 메시지를 append
- `/new` 명령 시 `_history[chat_id]` 초기화 (시스템 컨텍스트는 재주입)
- 메모리 제한: 최근 N턴만 유지 (기본값 20턴, 약 10회 대화)

---

## 5. 시스템 프롬프트 구조

```
당신은 work-agent 개인 에이전트입니다.
사용자의 개인 지식 관리, 작업 기록, 콘텐츠 생성을 돕습니다.

[프로젝트 컨텍스트]
{agent_memory_summary}

[활성 태스크]
{active_tasks_summary}

규칙:
- 작업/코드 관련 질문에 직접 답한다
- vault나 대화에 없는 사실은 만들지 않는다
- 실행 가능한 작업은 /명령 형태로 제안하고 사용자가 결정하게 한다
- 짧고 명확하게 답한다 (Telegram 4096자 제한)
```

시스템 프롬프트는 **매 chat() 호출마다** 재조합하지 않고,  
세션 시작(또는 `/new`) 시 한 번 조합해 `_system_prompt[chat_id]` 에 저장한다.

---

## 6. `chat()` 인터페이스

`app/assistant/assistant.py` 에 추가:

```python
def chat(self, text: str, history: list[dict], system_prompt: str) -> str:
    """
    multi-turn 대화 응답. light/writer task LLM 사용.
    history: [{"role": "user"|"assistant", "content": str}, ...]
    """
    messages = [{"role": "system", "content": system_prompt}]
    messages.extend(history[-40:])  # 최근 20턴 (40 메시지)
    messages.append({"role": "user", "content": text})

    return self.llm.complete_chat(messages)
    # LLMProvider에 complete_chat(messages) 추가 필요
    # 또는 기존 complete()에 history 파라미터 추가
```

---

## 7. LLMProvider 변경 — `complete_chat()`

현재 `LLMProvider.complete(prompt: str)` 는 단일 프롬프트만 받는다.  
multi-turn을 지원하려면 messages 배열을 받는 메서드가 필요하다.

선택지:

**A. `complete_chat(messages: list[dict]) → str` 추가 (권장)**
- 기존 `complete()`는 유지해서 호환성 깨지 않음
- Gemini / OpenAI-compatible 모두 messages 배열 지원함

**B. `complete(prompt, history=None)` 로 시그니처 확장**
- 기존 코드 변경 없이 추가 가능하지만 interface가 지저분해짐

task_type: `chat()` 에서는 `light` provider 사용 (분류가 아니라 짧은 대답이 많음).  
길어질 것 같으면 `writer`로 escalate.

---

## 8. `MessengerBot._handle_text()` 변경 (의사코드)

```python
def _handle_text(self, chat_id: str, text: str) -> str:
    # ... URL, pending 처리 (현재와 동일) ...

    if t.startswith("/"):
        return self.router.handle(t)

    if self.assistant is None:
        return self.router.handle(t)

    # 의도 분류
    intent = self.assistant.interpret(t)

    if intent.command not in ("unknown", "help", ""):
        # 파괴적 명령(삭제 등)만 확인 요청, 나머지는 즉시 실행
        if _is_destructive(intent.command):
            self._pending[chat_id] = intent
            return f"해석: {self.assistant.describe(intent)}\n실행할까요? (예/아니오)"
        return self.assistant.execute(intent)

    # unknown → 대화형 LLM 응답
    history = self._history.get(chat_id, [])
    system_prompt = self._system_prompt.get(chat_id) or _build_system_prompt()
    reply = self.assistant.chat(t, history, system_prompt)

    # 히스토리 업데이트
    self._history.setdefault(chat_id, [])
    self._history[chat_id].append({"role": "user", "content": t})
    self._history[chat_id].append({"role": "assistant", "content": reply})

    return reply
```

`_is_destructive()` 기준: `task-delete`, `del` 등 삭제/완료 불가역 명령만 확인.  
capture, search, todo 등 읽기/쓰기 안전한 명령은 즉시 실행.

---

## 9. 히스토리 관리 정책

| 항목 | 값 | 이유 |
|---|---|---|
| 최대 보관 턴 수 | 20턴 (40 메시지) | Gemini Flash context 제한 여유 확보 |
| 히스토리 저장소 | `dict[chat_id, list]` (메모리) | 재시작 시 초기화 허용, DB 불필요 |
| 영속화 | 미지원 (재시작 시 소멸) | `/new`로 명시 초기화와 구별 불필요 |
| 초과 시 처리 | 오래된 것부터 truncate | 최신 컨텍스트 우선 |

---

## Part 2. `/new` 세션 리셋

---

## 10. 문제 정의

`/clear` (Claude Code) 또는 봇 재시작 시:
- `_pending` 큐(확인 대기 중인 Intent)가 그냥 남거나 날아간다.
- `_history`(대화 히스토리)가 소멸한다.
- 어떤 태스크를 진행하고 있었는지 다음 세션이 모른다.

**원하는 동작:**  
`/new` → 대화 히스토리·pending 초기화 + **활성 태스크 + 에이전트 메모리**를 새 세션 system prompt에 재주입.

---

## 11. `/new` 동작 순서

```
1. _pending[chat_id] 초기화          ← 확인 대기 중인 명령 취소
2. _history[chat_id] 초기화           ← 대화 히스토리 비움
3. TaskAgent().service.list_tasks()  → 미완료 태스크 수집
4. AgentMemoryLoader().load_summary() → 핵심 컨텍스트 요약 수집
5. _build_system_prompt()로 재조합    ← 새 시스템 프롬프트 생성
6. _system_prompt[chat_id] 갱신
7. 사용자에게 요약 응답
```

응답 예시:
```
새 세션을 시작했습니다.

[이어갈 컨텍스트]
활성 태스크 2건:
· LLM 라우터 Telegram 연결 설계
· weekly-distill E2E 테스트

미해결 이슈:
· LONG_WRITER_PROVIDER 환경변수 미연결 (app/config.py:40)
· _FallbackProvider vs FallbackChain 중복 (llm_router_todo.md)

무엇부터 이어갈까요?
```

---

## 12. 컨텍스트 범위

### 활성 태스크
`list_tasks()` 에서 상태 `todo` / `in_progress` 만. 완료 항목 제외.

### 에이전트 메모리
`40_AgentMemory/Core/` + `05_OpenLoops.md` 의 **요약본** (전체 아님).  
`AgentMemoryLoader.load_summary()` 메서드를 추가해서 짧게 뽑는다.

---

## 13. 구현 위치 요약

| 컴포넌트 | 변경 내용 |
|---|---|
| `app/messaging/bot.py` | `_history`, `_system_prompt` dict 추가; `reset_session(chat_id)` 메서드 추가 |
| `app/messaging/router.py` | `cmd == "new"` 분기 추가 → `bot.reset_session(chat_id)` 호출 |
| `app/assistant/assistant.py` | `chat(text, history, system_prompt) → str` 메서드 추가 |
| `app/llm/base.py` | `complete_chat(messages: list[dict]) → str` 인터페이스 추가 |
| `app/memory/agent_memory_loader.py` | `load_summary() → str` 메서드 추가 |

---

## 14. 범위 제외 항목

- 대화 히스토리 영속화 (재시작 후 복원) → 미지원, 재시작 시 소멸
- 여러 chat_id 간 컨텍스트 공유 → 미지원
- 클라우드 세션 동기화 → 미지원

---

## 15. 미결 질문

1. `complete_chat()` — Gemini provider 구현 시 `start_chat()` API 쓸지, messages 조합 방식 쓸지
2. 에이전트 메모리 요약 길이 — Telegram 4096자 제한 고려, 시스템 프롬프트 내 메모리 섹션 최대 몇 자
3. 히스토리 truncate 기준 — 20턴(40 메시지) 고정 vs 토큰 카운트 기반
4. `/new` 트리거 위치 — `CommandRouter` 에서 처리할지, `MessengerBot` 에서 가로챌지

---

## 관련 파일

- [app/messaging/bot.py](../app/messaging/bot.py) — `MessengerBot`, `_pending` 관리
- [app/messaging/router.py](../app/messaging/router.py) — `CommandRouter._dispatch()`
- [app/assistant/assistant.py](../app/assistant/assistant.py) — `interpret()`, `execute()`
- [app/llm/base.py](../app/llm/base.py) — `LLMProvider` 인터페이스
- [app/agents/task_agent.py](../app/agents/task_agent.py) — 태스크 조회
- [app/memory/agent_memory_loader.py](../app/memory/agent_memory_loader.py) — 에이전트 메모리
