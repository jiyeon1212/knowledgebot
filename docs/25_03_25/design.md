# 설계: 프로젝트 기반 구조화 검색

## 전체 아키텍처

```
[사용자]
    │
    ├── /검색 커맨드 ──→ Slack Modal (폼)
    │                      │
    │                      ▼
    │                  폼 제출
    │                  (프로젝트명, 카테고리, 기간)
    │                      │
    │                      ▼
    │               ┌─────────────────┐
    │               │ 쿼리 변환 레이어 │
    │               │ (query_builder) │
    │               └────────┬────────┘
    │                        │ 플랫폼별 최적화된 쿼리 생성
    │                        ▼
    │               ┌─────────────────────────────┐
    │               │      병렬 검색 (3단계)        │
    │               │ Gmail / Drive / Conf / Jira  │
    │               └────────────┬────────────────┘
    │                            ▼
    │               ┌─────────────────────────┐
    │               │ AI 카테고리 필터링 (4단계) │
    │               └────────────┬────────────┘
    │                            ▼
    │               ┌──────────────────────┐
    │               │   AI 요약 생성 (5단계) │
    │               └────────────┬─────────┘
    │                            ▼
    │                     Slack 응답
    │
    └── DM 자연어 입력 ──→ 기존 흐름 (classify_intent → 검색 → 필터 → 요약)
```

## 1. Slack Modal (폼 UI)

### 슬래시 커맨드 등록

`/검색` 커맨드를 Slack App에 등록하고, `bot.py`에서 Modal을 띄운다.

### Modal 구조

```json
{
  "type": "modal",
  "title": "프로젝트 검색",
  "blocks": [
    {
      "type": "input",
      "block_id": "project_name",
      "label": "프로젝트명",
      "element": {
        "type": "plain_text_input",
        "placeholder": "예: 상호운용 (콤마로 복수 입력: kbtf, k-btf)"
      }
    },
    {
      "type": "input",
      "block_id": "category",
      "label": "카테고리",
      "element": {
        "type": "static_select",
        "options": [
          {"text": "사업", "value": "business"},
          {"text": "개발", "value": "development"}
        ]
      }
    },
    {
      "type": "input",
      "block_id": "period",
      "label": "기간",
      "optional": true,
      "element": {
        "type": "static_select",
        "options": [
          {"text": "전체", "value": "all"},
          {"text": "최근 1개월", "value": "1m"},
          {"text": "최근 3개월", "value": "3m"},
          {"text": "최근 6개월", "value": "6m"}
        ]
      }
    }
  ]
}
```

## 2. 쿼리 변환 레이어 (`app/search/query_builder.py` 신규)

폼 입력을 받아 플랫폼별 검색 파라미터를 생성한다.

### 카테고리별 보조 키워드 매핑

```python
CATEGORY_KEYWORDS = {
    "business": {
        "gmail_keywords": ["제안서", "기안서", "견적서", "계약서", "발주서", "검수서", "사업", "제안"],
        "filter_description": "사업 관련 문서 (제안서, 기안서, 견적서, 계약서, 발주서, 검수서 등)",
    },
    "development": {
        "gmail_keywords": ["API", "SDK", "연동", "가이드", "개발", "테스트", "배포", "설계"],
        "filter_description": "개발 관련 문서 (API, SDK, 연동 가이드, 테스트, 설계 문서 등)",
    },
}
```

### 프로젝트명 파싱 (콤마 → OR)

```python
def parse_project_names(raw: str) -> list[str]:
    """콤마로 구분된 프로젝트명을 리스트로 반환"""
    return [name.strip() for name in raw.split(",") if name.strip()]
```

### 플랫폼별 쿼리 생성

```python
def build_gmail_query(project_names: list[str], category: str, date_from, date_to) -> str:
    """Gmail API용 쿼리 생성"""
    # 프로젝트명 OR
    project_part = " OR ".join(project_names)
    # 카테고리 보조 키워드
    keywords = CATEGORY_KEYWORDS[category]["gmail_keywords"]
    keyword_part = " OR ".join(keywords)
    # 결합: (프로젝트명) AND (보조 키워드)
    query = f"({project_part}) ({keyword_part})"
    # 날짜 필터
    if date_from:
        query += f" after:{date_from.replace('-', '/')}"
    if date_to:
        query += f" before:{date_to.replace('-', '/')}"
    return query


def build_confluence_params(project_names: list[str], date_from, date_to) -> dict:
    """Confluence 검색용 파라미터 생성 — 프로젝트명으로 상위 페이지를 찾은 뒤 하위 조회"""
    return {
        "project_names": project_names,
        "date_from": date_from,
        "date_to": date_to,
    }


def build_drive_params(project_names: list[str], date_from, date_to) -> dict:
    """Drive 검색용 파라미터 생성 — 프로젝트명으로 폴더 찾은 뒤 내부 파일 조회"""
    return {
        "project_names": project_names,
        "date_from": date_from,
        "date_to": date_to,
    }


def build_jira_params(project_names: list[str], date_from, date_to) -> dict:
    """Jira 검색용 파라미터 생성 — 프로젝트명으로 프로젝트 찾은 뒤 이슈 조회"""
    return {
        "project_names": project_names,
        "date_from": date_from,
        "date_to": date_to,
    }
```

### 기간 변환

```python
def resolve_period(period: str) -> tuple[str | None, str | None]:
    """기간 옵션을 date_from, date_to로 변환"""
    if period == "all" or not period:
        return None, None
    # "1m" → 1개월 전 ~ 오늘
    # "3m" → 3개월 전 ~ 오늘
    # "6m" → 6개월 전 ~ 오늘
```

## 3. 플랫폼별 검색 변경

### Confluence (`app/atlassian/confluence.py`)

기존 `search_confluence(query)` 외에 새 함수 추가:

```python
async def search_confluence_by_project(
    access_token: str,
    cloud_id: str,
    project_names: list[str],
    max_results: int = 50,
    date_from: str | None = None,
    date_to: str | None = None,
) -> list[dict]:
    """프로젝트명으로 상위 페이지를 찾고 하위 페이지를 전부 조회한다.

    1. title~"프로젝트명" 으로 상위 페이지 검색
    2. ancestor={pageId} 로 모든 하위 페이지 조회
    3. 콤마로 구분된 여러 프로젝트명은 각각 검색 후 합침
    """
```

### Drive (`app/google/drive.py`)

새 함수 추가:

```python
async def search_drive_by_project(
    access_token: str,
    project_names: list[str],
    max_results: int = 50,
    date_from: str | None = None,
    date_to: str | None = None,
) -> list[dict]:
    """프로젝트명으로 폴더를 찾고 폴더 내 파일을 전부 조회한다.

    1. name contains '프로젝트명' and mimeType='application/vnd.google-apps.folder'
    2. '폴더ID' in parents 로 내부 파일 조회 (재귀적으로 하위 폴더 포함)
    """
```

### Jira (`app/atlassian/jira.py`)

새 함수 추가:

```python
async def search_jira_by_project(
    access_token: str,
    cloud_id: str,
    project_names: list[str],
    max_results: int = 50,
    date_from: str | None = None,
    date_to: str | None = None,
) -> list[dict]:
    """프로젝트명으로 Jira 프로젝트를 찾고 이슈를 전부 조회한다.

    1. /rest/api/3/project/search 로 프로젝트명 검색
    2. project = "KEY" 로 이슈 조회
    """
```

### Gmail (`app/google/gmail.py`)

기존 `search_gmail` 함수를 그대로 사용하되, 쿼리 변환 레이어에서 생성한 최적화된 쿼리를 전달한다.

## 4. AI 카테고리 필터링 (`app/ai/summarizer.py`)

기존 `filter_irrelevant_results`와 별도로 카테고리 필터링 함수 추가:

```python
CATEGORY_FILTER_PROMPT = """\
아래 문서 목록에서 "{category_description}" 에 해당하는 문서만 골라주세요.

판단 기준:
- 사업: 제안서, 기안서, 견적서, 계약서, 발주서, 검수서, 사업계획, 고객 요구사항, RFP 등
- 개발: API 문서, SDK 가이드, 연동 가이드, 설계 문서, 테스트 케이스, 개발 명세, 코드 리뷰 등

제목이나 내용 요약을 보고 판단하세요.
문서의 실제 내용이 해당 카테고리에 속하면 관련 있음 (O)
관련 없으면 (X)

반드시 아래 JSON 형식으로만 응답하세요:
{{"relevant_indices": [0, 2, 5]}}
"""

async def filter_by_category(
    category: str,
    results: list[dict],
    source_type: str,
) -> list[dict]:
    """AI를 사용하여 카테고리에 맞는 문서만 필터링한다."""
```

## 5. 핸들러 흐름 (`app/slack/handlers.py`)

### 새 핸들러 추가: `handle_project_search`

```python
async def handle_project_search(
    user_id: str,
    project_names: list[str],
    category: str,
    date_from: str | None,
    date_to: str | None,
    say,
) -> None:
    """폼 기반 프로젝트 검색을 처리한다.

    흐름:
    1. 쿼리 변환 레이어로 플랫폼별 파라미터 생성
    2. 병렬로 Gmail/Drive/Confluence/Jira 검색
    3. AI 카테고리 필터링
    4. AI 요약 생성
    5. Slack 응답
    """
```

## 변경 파일 요약

| 파일 | 변경 유형 | 내용 |
|---|---|---|
| `app/search/query_builder.py` | **신규** | 쿼리 변환 레이어 |
| `app/slack/bot.py` | 수정 | `/검색` 슬래시 커맨드 + Modal 등록 |
| `app/slack/handlers.py` | 수정 | `handle_project_search` 핸들러 추가 |
| `app/atlassian/confluence.py` | 수정 | `search_confluence_by_project` 함수 추가 |
| `app/google/drive.py` | 수정 | `search_drive_by_project` 함수 추가 |
| `app/atlassian/jira.py` | 수정 | `search_jira_by_project` 함수 추가 |
| `app/google/gmail.py` | 변경 없음 | 기존 함수 재사용 (쿼리만 변경) |
| `app/ai/summarizer.py` | 수정 | `filter_by_category` 함수 추가 |
