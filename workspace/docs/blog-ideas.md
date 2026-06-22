# Blog Ideas

블로그로 쓰고 싶은 주제 메모. 상태는 idea / draft_requested / draft_generated / published.

---

- [idea] RAG 시스템 개발/운영 환경 분리 — DB, Qdrant, vLLM을 어떻게 나눴나
  - 왜 분리가 필요했는지(테스트 데이터 오염), 무엇을 나눴는지, Docker Compose 구조

- [idea] 원격 vLLM 연결하며 만난 PowerShell curl 함정
  - `curl`이 `Invoke-WebRequest` alias라 헤더가 안 먹던 문제와 `curl.exe` 해결

- [idea] vLLM 연결 불안정, 재부팅으로 넘긴 이야기와 다음에 할 헬스체크
  - 임시방편(재부팅)과 근본 대응(모니터링) 사이의 판단

- [idea] 사내 규정 RAG 검색 품질 개선 — 하이브리드 검색을 쓴 이유
  - dense만으로 부족했던 규정 용어 검색, sparse 결합
