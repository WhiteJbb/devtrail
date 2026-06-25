현재 work-agent의 LLM 구조를 역할 기반 라우팅 + fallback 구조로 확장해줘.

목표는 Gemini가 503, timeout, 429 등으로 자주 실패할 때 자동으로 다른 LLM API로 fallback하고, 작업 성격에 따라 적절한 모델을 선택하는 것이다.

중요:

* DeepSeek는 사용하지 않는다.
* 기존 Gemini 중심 구조는 유지한다.
* 기존 LOCAL_LLM_PROVIDER / WRITER_PROVIDER 구조와 호환되게 구현한다.
* 큰 리팩토링보다 현재 구조를 확장하는 방식으로 진행한다.
* source에 없는 사실이나 수치를 만들면 안 된다는 기존 원칙은 유지한다.
* 테스트는 API 키 없이 fake/mock 기반으로 통과해야 한다.

최종 모델 구조는 아래와 같다.

1. Light Task
   용도:

* 의도 분류
* 태깅
* 짧은 요약
* distill-today
* suggest-knowledge
* suggest-blog-topics
* suggest-memory-patch
* ask 자연어 의도 분류
* capture 요약

라우팅:
Gemini Flash-Lite → GPT-4o mini → Ollama qwen3:8b

2. Writer Task
   용도:

* 일반 블로그 초안
* worklog
* resume 초안
* portfolio 초안
* portfolio-draft
* interview-questions

라우팅:
Gemini Flash → GPT-4o mini → Kimi

3. Long Context Writer Task
   용도:

* 긴 ContextPack 기반 글쓰기
* weekly-distill
* summarize-project
* 월간 회고
* 프로젝트 전체 요약
* 여러 Claude Code 세션 요약 기반 개발일지
* build-context 이후 긴 글쓰기

라우팅:
Kimi → Gemini Flash → GPT-4o mini

4. Polish Task
   용도:

* resume 최종 문장 다듬기
* portfolio 최종 문장 다듬기
* revise-blog
* 자기소개서/포트폴리오 톤 조정

라우팅:
GPT-4o mini → Gemini Flash

5. Local Emergency
   용도:

* 인터넷/API 전체 장애 시 최소 동작
* 짧은 요약/분류 정도만 수행

모델:
Ollama qwen3:8b

.env 예시는 아래처럼 확장한다.

LOCAL_LLM_PROVIDER=gemini
WRITER_PROVIDER=gemini
LONG_WRITER_PROVIDER=kimi
POLISH_PROVIDER=openai_compatible

GEMINI_API_KEY=...
GEMINI_FLASH_MODEL=gemini-2.5-flash
GEMINI_LITE_MODEL=gemini-2.5-flash-lite

OPENAI_API_KEY=...
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_MODEL=gpt-4o-mini

KIMI_API_KEY=...
KIMI_BASE_URL=https://api.moonshot.ai/v1
KIMI_MODEL=kimi-k2

OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=qwen3:8b

구현 요구사항:

1. app/llm/router.py 추가 또는 확장

* task_type을 받아 적절한 provider chain을 선택한다.
* task_type 후보:

  * light
  * writer
  * long_writer
  * polish
  * local
* task_type이 명시되지 않으면 기존 동작과 최대한 호환되도록 writer 또는 local 기본값을 사용한다.

2. app/llm/fallback.py 추가

* provider chain을 순서대로 실행한다.
* 다음 오류는 즉시 다음 provider로 fallback한다.

  * HTTP 503
  * HTTP 429
  * timeout
  * connection error
  * provider unavailable
* JSON parse 실패는 같은 provider로 1회 재시도한 뒤, 그래도 실패하면 다음 provider로 fallback한다.
* context length 초과는 먼저 context 압축/절단 로직을 적용하고, 그래도 실패하면 long_writer provider chain으로 넘긴다.
* fallback이 발생하면 어떤 provider에서 어떤 provider로 넘어갔는지 로그를 남긴다.

3. Kimi provider 추가

* Kimi는 OpenAI-compatible 방식으로 구현한다.
* 가능하면 기존 openai_compatible provider를 재사용하고, base_url / api_key / model만 Kimi 설정을 읽도록 한다.
* 별도 파일을 만든다면 app/llm/kimi_provider.py로 둔다.
* KIMI_BASE_URL, KIMI_API_KEY, KIMI_MODEL 환경변수를 지원한다.

4. OpenAI provider 확인

* GPT-4o mini fallback을 위해 OpenAI-compatible provider가 OPENAI_BASE_URL, OPENAI_API_KEY, OPENAI_MODEL을 안정적으로 읽는지 확인한다.
* 기존 OpenAI-compatible 설정과 충돌하지 않게 한다.

5. Ollama fallback 확인

* Ollama는 local emergency fallback으로만 사용한다.
* Ollama가 꺼져 있거나 연결 실패하면 전체 실패 메시지를 명확하게 반환한다.
* Ollama fallback은 긴 글쓰기 품질을 보장하지 않아도 된다.

6. 명령별 task_type 연결
   아래 명령은 light로 라우팅한다.

* capture 요약
* distill-today
* suggest-knowledge
* suggest-blog-topics
* suggest-memory-patch
* ask 의도 분류

아래 명령은 writer로 라우팅한다.

* write-blog
* worklog
* resume
* portfolio
* portfolio-draft
* interview-questions

아래 명령은 long_writer로 라우팅한다.

* weekly-distill
* summarize-project
* build-context 결과를 기반으로 한 긴 글쓰기
* 긴 ContextPack이 포함된 write-blog
* 월간/주간 종합 회고

아래 명령은 polish로 라우팅한다.

* revise-blog
* resume 최종 다듬기
* portfolio 최종 다듬기

7. Output Guard 유지/강화

* source에 없는 사실, 수치, 성과를 임의로 만들지 않는다.
* 후보 파일에는 근거 source를 남긴다.
* LLM이 새로운 수치를 만들거나 과장 표현을 만들면 제거하거나 경고 주석을 남긴다.
* JSON 출력이 필요한 작업은 JSON schema 검증을 통과해야 저장한다.

8. 설정 파일 업데이트

* .env.example에 아래 항목 추가

  * LONG_WRITER_PROVIDER
  * POLISH_PROVIDER
  * OPENAI_API_KEY
  * OPENAI_BASE_URL
  * OPENAI_MODEL
  * KIMI_API_KEY
  * KIMI_BASE_URL
  * KIMI_MODEL
* README 또는 AI 설정 문서에 최종 구조를 간단히 반영한다.
* DeepSeek 관련 내용은 추가하지 않는다.

9. 테스트 추가
   API 키 없이 동작하는 fake provider 기반 테스트를 추가한다.

테스트 케이스:

* Gemini 503 발생 시 GPT-4o mini로 fallback 되는지
* GPT-4o mini도 실패하면 light task에서 Ollama fallback까지 가는지
* long_writer task는 Kimi를 1순위로 선택하는지
* writer task는 Gemini Flash → GPT-4o mini → Kimi 순서인지
* polish task는 GPT-4o mini → Gemini Flash 순서인지
* JSON parse 실패 시 같은 provider로 1회 재시도하는지
* 모든 provider 실패 시 사용자가 이해할 수 있는 에러 메시지를 반환하는지
* 기존 Gemini 단독 설정도 깨지지 않는지

10. 구현 후 확인 명령
    아래 명령이 정상 동작해야 한다.

python -m pytest -q

그리고 가능하면 실제 CLI 기준으로 아래 명령들이 기존처럼 실행되어야 한다.

work-agent distill-today
work-agent write-blog "테스트 주제"
work-agent weekly-distill
work-agent resume

최종적으로 원하는 구조는 다음과 같다.

Light:
Gemini Flash-Lite → GPT-4o mini → Ollama

Writer:
Gemini Flash → GPT-4o mini → Kimi

Long Writer:
Kimi → Gemini Flash → GPT-4o mini

Polish:
GPT-4o mini → Gemini Flash

Local Emergency:
Ollama qwen3:8b
