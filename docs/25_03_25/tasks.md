# 구현 태스크: 프로젝트 기반 구조화 검색

## 태스크 목록

### Phase 1: 쿼리 변환 레이어
- [x] 1-1. `app/search/query_builder.py` 생성
  - 카테고리별 보조 키워드 매핑 (CATEGORY_KEYWORDS)
  - 프로젝트명 파싱 (콤마 → 리스트)
  - 기간 옵션 → date_from/date_to 변환
  - Gmail 쿼리 생성 함수

### Phase 2: 플랫폼별 프로젝트 기반 검색 함수
- [x] 2-1. `confluence.py` — `search_confluence_by_project` 추가
  - title~"프로젝트명" 으로 상위 페이지 검색
  - ancestor={pageId} 로 하위 페이지 전체 조회
  - 콤마 구분 복수 프로젝트 지원
- [x] 2-2. `drive.py` — `search_drive_by_project` 추가
  - 프로젝트명으로 폴더 검색
  - 폴더 내 파일 전체 조회 (재귀 하위 폴더 포함)
- [x] 2-3. `jira.py` — `search_jira_by_project` 추가
  - 프로젝트명으로 Jira 프로젝트 검색
  - 해당 프로젝트 이슈 전체 조회

### Phase 3: AI 카테고리 필터링
- [x] 3-1. `summarizer.py` — `filter_by_category` 함수 추가
  - 카테고리 필터링 프롬프트 작성
  - 사업/개발 기준으로 문서 필터링

### Phase 4: Slack UI
- [x] 4-1. `bot.py` — `/검색` 슬래시 커맨드 핸들러 + Modal 띄우기
- [x] 4-2. `bot.py` — Modal 제출(view_submission) 핸들러
- [ ] 4-3. Slack App 설정에서 `/검색` 슬래시 커맨드 등록 (수동 작업 필요)

### Phase 5: 핸들러 통합
- [x] 5-1. `handlers.py` — `handle_project_search` 함수 구현
  - 쿼리 변환 → 병렬 검색 → AI 필터링 → AI 요약 → Slack 응답
- [x] 5-2. 기존 DM 자연어 검색(`handle_dm`)은 그대로 유지

### Phase 6: 테스트
- [x] 6-1. query_builder 단위 테스트 (15개 전부 통과)
- [ ] 6-2. E2E 테스트 (Slack App에 슬래시 커맨드 등록 후 실제 테스트 필요)
