# Project Context

블로그/포트폴리오의 배경이 되는 프로젝트 개요. 사실 위주로 적는다.

---

## XCoreChat — 사내 규정 RAG 시스템

사내 규정/문서를 질의하면 근거와 함께 답변하는 온프레미스 RAG 챗봇.

### 스택
- Backend: FastAPI
- Frontend: React
- Vector DB: Qdrant
- RDB: PostgreSQL
- LLM: 온프레미스 vLLM (OpenAI-compatible 엔드포인트)
- Embedding: BGE-m3

### 구조 특징
- 전 구간 온프레미스. 외부 API로 데이터가 나가지 않는 것이 요구사항.
- 하이브리드 검색: dense(BGE-m3) + sparse 결합으로 규정 용어 검색 품질 보완.
- 문서 관리 기능: 규정 문서 업로드/버전 관리.
- 관리자 기능: 사용 로그, 답변 품질 모니터링.
- 개발/운영 환경 분리: DB·Qdrant·LLM 엔드포인트를 환경별로 분기.

### 현재 관심사
- 개발/운영 데이터 격리
- 원격 vLLM 연결 안정성
- 검색 품질(특히 규정 고유 용어) 개선
