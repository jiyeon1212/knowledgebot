"""프로젝트 기반 구조화 검색을 위한 쿼리 변환 레이어.

DM 입력 포맷:
    #검색 프로젝트명 /카테고리
    #검색 프로젝트명 /카테고리 /기간(자연어)

예시:
    #검색 상호운용 /개발
    #검색 미래에셋, 신한 /사업 /최근 3개월
    #검색 kbtf, k-btf /개발 /2025년 상반기
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

# ---------------------------------------------------------------------------
# 카테고리별 보조 키워드 매핑
# ---------------------------------------------------------------------------

CATEGORY_KEYWORDS: dict[str, dict] = {
    "business": {
        "gmail_keywords": [
            "제안서", "기안서", "견적서", "계약서", "발주서", "검수서",
            "사업", "제안", "수주", "입찰", "RFP", "RFI",
        ],
        "filter_description": (
            "사업 관련 문서 (제안서, 기안서, 견적서, 계약서, 발주서, 검수서, "
            "사업계획, 고객 요구사항, RFP, 입찰, 수주 등)"
        ),
    },
    "development": {
        "gmail_keywords": [
            "API", "SDK", "연동", "가이드", "개발", "테스트",
            "배포", "설계", "아키텍처", "스펙", "명세",
        ],
        "filter_description": (
            "개발 관련 문서 (API, SDK, 연동 가이드, 테스트, 설계 문서, "
            "아키텍처, 스펙, 개발 명세, 배포 등)"
        ),
    },
}


# ---------------------------------------------------------------------------
# 프로젝트명 파싱
# ---------------------------------------------------------------------------

def parse_project_names(raw: str) -> list[str]:
    """콤마로 구분된 프로젝트명을 리스트로 반환한다."""
    return [name.strip() for name in raw.split(",") if name.strip()]


# ---------------------------------------------------------------------------
# 기간 변환
# ---------------------------------------------------------------------------

def resolve_period(period: str | None) -> tuple[str | None, str | None]:
    """기간 옵션을 (date_from, date_to) 튜플로 변환한다.

    Returns:
        (date_from, date_to) — YYYY-MM-DD 형식 또는 None
    """
    if not period or period == "all":
        return None, None

    today = datetime.now(timezone.utc).date()
    date_to = today.isoformat()

    months_map = {"1m": 1, "3m": 3, "6m": 6}
    months = months_map.get(period)
    if months is None:
        return None, None

    # 단순 계산: 월 단위로 빼기
    year = today.year
    month = today.month - months
    while month <= 0:
        month += 12
        year -= 1
    day = min(today.day, 28)  # 월말 안전 처리
    date_from = f"{year:04d}-{month:02d}-{day:02d}"

    return date_from, date_to


# ---------------------------------------------------------------------------
# 플랫폼별 쿼리 생성
# ---------------------------------------------------------------------------

def build_gmail_query(
    project_names: list[str],
    category: str,
    date_from: str | None = None,
    date_to: str | None = None,
) -> str:
    """Gmail API용 쿼리 문자열을 생성한다.

    구조: (프로젝트명1 OR 프로젝트명2) (보조키워드1 OR 보조키워드2 ...)
    """
    # 프로젝트명 OR 결합
    if len(project_names) == 1:
        project_part = project_names[0]
    else:
        project_part = "(" + " OR ".join(project_names) + ")"

    # 카테고리 보조 키워드
    keywords = CATEGORY_KEYWORDS.get(category, {}).get("gmail_keywords", [])
    if keywords:
        keyword_part = "(" + " OR ".join(keywords) + ")"
        query = f"{project_part} {keyword_part}"
    else:
        query = project_part

    # 날짜 필터
    if date_from:
        query += f" after:{date_from.replace('-', '/')}"
    if date_to:
        query += f" before:{date_to.replace('-', '/')}"

    return query


# ---------------------------------------------------------------------------
# DM 포맷 파싱
# ---------------------------------------------------------------------------

# 카테고리 한글 → 영문 매핑
_CATEGORY_MAP: dict[str, str] = {
    "사업": "business",
    "개발": "development",
}

_SEARCH_PREFIX = "#검색"


def is_project_search(text: str) -> bool:
    """메시지가 #검색 포맷인지 확인한다."""
    return text.strip().startswith(_SEARCH_PREFIX)


def parse_search_command(text: str) -> dict | None:
    """#검색 포맷의 메시지를 파싱한다.

    포맷: #검색 프로젝트명 /카테고리 [/기간]

    Returns:
        {
            "project_names": list[str],
            "category": "business" | "development",
            "period_text": str | None,   # AI에게 넘길 기간 자연어 텍스트
        }
        파싱 실패 시 None
    """
    text = text.strip()
    if not text.startswith(_SEARCH_PREFIX):
        return None

    # "#검색" 제거
    body = text[len(_SEARCH_PREFIX):].strip()
    if not body:
        return None

    # /로 시작하는 부분들을 분리
    # 예: "상호운용, kbtf /개발 /최근 3개월"
    #   → parts = ["상호운용, kbtf ", "개발 ", "최근 3개월"]
    segments = re.split(r"\s*/\s*", body)

    if len(segments) < 2:
        # 최소한 프로젝트명 + 카테고리가 필요
        return None

    # 첫 번째: 프로젝트명
    project_raw = segments[0].strip()
    if not project_raw:
        return None

    # 두 번째: 카테고리
    category_raw = segments[1].strip()
    category = _CATEGORY_MAP.get(category_raw)
    if category is None:
        return None

    # 세 번째 이후: 기간 (선택사항, 자연어)
    period_text = None
    if len(segments) >= 3:
        period_text = segments[2].strip() or None

    return {
        "project_names": parse_project_names(project_raw),
        "category": category,
        "period_text": period_text,
    }
