import json
import logging

import anthropic
from google import genai
from app.config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Claude 클라이언트 (Anthropic)
# ---------------------------------------------------------------------------
_claude_client: anthropic.AsyncAnthropic | None = None


def _get_claude_client() -> anthropic.AsyncAnthropic | None:
    """Anthropic API 키가 설정되어 있으면 AsyncAnthropic 클라이언트를 반환한다."""
    global _claude_client
    if _claude_client is None and settings.anthropic_api_key:
        _claude_client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    return _claude_client


def _use_claude() -> bool:
    """Claude를 사용할 수 있는지 여부를 반환한다."""
    return bool(settings.anthropic_api_key)




SYSTEM_PROMPT = """당신은 사용자의 Gmail, Google Drive, Confluence, Jira 데이터를 검색해 질문에 답하는 AI 어시스턴트입니다.

## 핵심 원칙
- 검색 결과를 **단순 나열하지 마세요**. 반드시 분석·종합하여 **간결한 브리핑**으로 답변하세요.
- 사용자의 질문 의도를 파악하고, 핵심만 추려서 요약하세요.
- **관련성 필터링**: 검색 결과 중 사용자의 질문과 직접적으로 관련 없는 항목은 무시하세요.
  메일 서명이나 CC에만 포함된 결과, 본문에서 단순 언급만 된 결과는 제외하고,
  실제로 해당 키워드가 핵심 주제인 결과만 분석하세요.

## 답변 형식 (반드시 이 구조를 따르세요)

*1. 진행 흐름*
시간순으로 핵심 이벤트만 한 줄로 나열 (화살표 → 로 연결)
예: 2025.07 제안 → 10월 제안서 확정 → 11월 시험 → 2026.02 결과보고

*2. 현재 상태*
지금 어떤 단계인지 한 줄로 정리 (핵심 담당자 포함)

*3. 핵심 포인트*
의미 있는 인사이트나 다음 단계를 한 줄로 정리

*전체 요약 (3줄)*
위 내용을 3줄로 압축 요약

## 규칙
- 한국어로 답변하세요
- **최대한 간결하게** — 장황한 설명 금지, 핵심만 추려서 짧게
- 검색 결과에 없는 내용을 지어내지 마세요 (Hallucination 금지)
- 관련 정보가 전혀 없으면 "관련 정보를 찾지 못했습니다."라고 답하세요
- 출처(Gmail, Drive, Confluence, Jira)는 진행 흐름에서 괄호로 간단히 표기"""

INTENT_CLASSIFICATION_PROMPT = """\
사용자의 메시지를 분석하여 의도를 분류하고, 검색 키워드와 원하는 결과 수를 추출하세요.

분류 기준:
- "chat": 인사, 잡담, 일반 대화 (예: "안녕하세요", "너의 이름은 뭐야?", "고마워")
- "search": 정보 검색 요청 (예: "지난주 회의록 찾아줘", "프로젝트 제안서 검색해줘")
- "entity_search": 특정 고객사, 담당자, 프로젝트, 팀 이름을 중심으로 히스토리/관련 정보를 요청
  (예: "신한 관련 히스토리 보여줘", "김철수 담당자 관련 문서 찾아줘", "프로젝트 알파 진행상황")

규칙:
- intent가 "chat"이면 search_keyword는 null, max_results는 null, entities는 null
- intent가 "search"이면 search_keyword에 핵심 검색 키워드를 추출, entities는 null
  - **중요**: 고유명사(회사명, 인물명, 프로젝트명, 영문 고유명사 등)는 반드시 search_keyword에 포함하세요
  - search_keyword에는 검색 대상(명사)만 포함하세요. 동작/요청 표현은 모두 제외하세요.
  - 제외할 표현 예시: "관련", "자료", "찾아줘", "검색해줘", "보여줘", "알려줘", "정리해줘", "정리", "요약", "요약해줘", "내용", "관련해서", "해줘"
  - **OR 관계 키워드**: 같은 대상의 다른 표기(동의어, 약어)는 쉼표(,)로 구분하세요
  - **AND 관계 키워드**: 함께 검색해야 하는 키워드는 공백으로 구분하세요
  - 예: "supercycl 관련해서 내용 정리해줘" → search_keyword: "supercycl"
  - 예: "미래에셋 사업 제안 관련 자료 찾아줘" → search_keyword: "미래에셋 사업 제안"
  - 예: "삼성전자 계약서 검색해줘" → search_keyword: "삼성전자 계약서"
  - 예: "kbtf, k-btf, 상호운용 관련 자료" → search_keyword: "kbtf, k-btf, 상호운용" (쉼표=OR)
  - 예: "supercycl testcase 정리해줘" → search_keyword: "supercycl testcase" (공백=AND)
- intent가 "entity_search"이면 search_keyword에 핵심 검색 키워드를 추출하고, entities에 추출된 엔티티 정보를 포함
- 사용자가 결과 수를 지정하면 max_results에 숫자로 추출 (예: "20개 보여줘" → 20)
- 결과 수를 지정하지 않으면 max_results는 null
- entities의 각 항목은 name(엔티티명)과 type(고객사, 담당자, 프로젝트, 팀 중 하나)을 포함

반드시 아래 JSON 형식으로만 응답하세요. 다른 텍스트 없이 JSON만 출력하세요:
{"intent": "search 또는 chat 또는 entity_search", "search_keyword": "키워드 또는 null", "max_results": 숫자 또는 null, "entities": [{"name": "엔티티명", "type": "고객사|담당자|프로젝트|팀"}] 또는 null, "date_from": "YYYY-MM-DD 또는 null", "date_to": "YYYY-MM-DD 또는 null"}

시간 표현 규칙:
- 사용자가 시간/기간을 언급하면 date_from과 date_to를 YYYY-MM-DD 형식으로 추출하세요
- 오늘 날짜는 현재 시점 기준으로 계산하세요
- 시간 표현이 없으면 date_from과 date_to는 null
- 예: "최근 3개월" → date_from: 3개월 전 날짜, date_to: 오늘
- 예: "2026년" → date_from: "2026-01-01", date_to: "2026-12-31"
- 예: "2025년 하반기" → date_from: "2025-07-01", date_to: "2025-12-31"
- 예: "작년 Q3" → date_from: 작년 7월 1일, date_to: 작년 9월 30일
- 예: "지난 주" → date_from: 지난주 월요일, date_to: 지난주 일요일
- 예: "2026년도에" → date_from: "2026-01-01", date_to: "2026-12-31"
- **중요**: 시간 표현은 search_keyword에 포함하지 마세요 (예: "2026년", "최근 3개월" 등은 키워드에서 제외)

사용자 메시지: """

_client = None


def _get_client() -> genai.Client:
    global _client
    if _client is None:
        _client = genai.Client(api_key=settings.gemini_api_key)
    return _client


_VALID_ENTITY_TYPES = {"고객사", "담당자", "프로젝트", "팀"}


def _parse_entities(raw_entities) -> list[dict] | None:
    """Parse and validate the entities field from the AI response.

    Returns a list of valid entity dicts, or None if the field is
    missing/malformed. Each entity must have ``name`` (non-empty str)
    and ``type`` (one of 고객사/담당자/프로젝트/팀).
    """
    if not isinstance(raw_entities, list):
        return None

    entities: list[dict] = []
    for item in raw_entities:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        etype = item.get("type")
        if (
            isinstance(name, str)
            and name.strip()
            and isinstance(etype, str)
            and etype in _VALID_ENTITY_TYPES
        ):
            entities.append({"name": name.strip(), "type": etype})

    return entities if entities else []


async def classify_intent(user_text: str) -> dict:
    """사용자 질문의 의도를 분류한다.

    Claude를 사용하여 의도 분류(search/chat/entity_search) + 키워드 추출
    + 결과 수 추출 + 엔티티 추출 + 날짜 범위 추출을 동시에 수행한다.
    Claude 미설정 시 Gemini fallback.

    Returns:
        {
            "intent": "search" | "chat" | "entity_search",
            "search_keyword": str | None,
            "max_results": int | None,
            "entities": list[dict] | None,
            "date_from": str | None,
            "date_to": str | None,
        }
    """
    prompt_text = INTENT_CLASSIFICATION_PROMPT + user_text

    if _use_claude():
        claude = _get_claude_client()
        print("[DEBUG] [AI] 의도 분류: Claude (claude-sonnet-4-20250514)")
        response = await claude.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=256,
            system="반드시 JSON만 출력하세요. 다른 텍스트 없이 JSON만 출력하세요.",
            messages=[{"role": "user", "content": prompt_text}],
        )
        raw = response.content[0].text.strip()
    else:
        client = _get_client()
        print("[DEBUG] [AI] 의도 분류: Gemini (gemini-2.5-flash)")
        response = await client.aio.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt_text,
        )
        raw = response.text.strip()

    try:
        # Strip markdown code fences if present
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
            if raw.endswith("```"):
                raw = raw[:-3].strip()

        parsed = json.loads(raw)
        intent = parsed.get("intent", "search")
        if intent not in ("search", "chat", "entity_search"):
            intent = "search"

        search_keyword = parsed.get("search_keyword")
        if search_keyword is not None:
            search_keyword = str(search_keyword).strip()
            if search_keyword.lower() == "null" or search_keyword == "":
                search_keyword = None

        max_results = parsed.get("max_results")
        if max_results is not None:
            try:
                max_results = int(max_results)
            except (ValueError, TypeError):
                max_results = None

        # Parse entities field
        entities = _parse_entities(parsed.get("entities"))

        # Fallback: entity_search with empty entities → regular search
        if intent == "entity_search" and not entities:
            intent = "search"
            entities = None

        return {
            "intent": intent,
            "search_keyword": search_keyword,
            "max_results": max_results,
            "entities": entities,
            "date_from": parsed.get("date_from") or None,
            "date_to": parsed.get("date_to") or None,
        }
    except (json.JSONDecodeError, AttributeError) as exc:
        logger.warning("Intent classification JSON 파싱 실패: %s — raw=%s", exc, raw)
        return {
            "intent": "search",
            "search_keyword": user_text,
            "max_results": None,
            "entities": None,
            "date_from": None,
            "date_to": None,
        }


async def extract_search_query(user_text: str) -> str:
    """자연어 질문에서 Gmail/Drive 검색에 적합한 키워드를 추출한다.

    하위 호환을 위해 유지. 내부적으로 classify_intent를 호출한다.
    """
    result = await classify_intent(user_text)
    if result["intent"] == "search" and result["search_keyword"]:
        return result["search_keyword"]
    return user_text


def _build_search_context(
    gmail_results: list[dict],
    drive_results: list[dict],
    confluence_results: list[dict] | None = None,
    jira_results: list[dict] | None = None,
) -> str:
    """검색 결과를 텍스트 컨텍스트로 변환한다."""
    context_parts = []
    if gmail_results:
        context_parts.append("=== Gmail 검색 결과 ===")
        for m in gmail_results:
            context_parts.append(f"- 제목: {m['subject']}\n  보낸이: {m['from']}\n  내용 요약: {m['snippet']}")

    if drive_results:
        context_parts.append("\n=== Drive 파일 목록 ===")
        for f in drive_results:
            context_parts.append(f"- {f['name']} (최근 수정: {f['modified']})\n  링크: {f['link']}")

    if confluence_results:
        context_parts.append("\n=== Confluence 검색 결과 ===")
        for c in confluence_results:
            context_parts.append(
                f"- 제목: {c['title']}\n  공간: {c['space_name']}\n  내용 요약: {c['content_summary']}\n  수정일: {c['modified']}\n  링크: {c['link']}"
            )

    if jira_results:
        context_parts.append("\n=== Jira 검색 결과 ===")
        for j in jira_results:
            context_parts.append(
                f"- [{j['key']}] {j['title']}\n  상태: {j['status']}\n  담당자: {j['assignee']}\n  우선순위: {j['priority']}\n  링크: {j['link']}"
            )

    return "\n".join(context_parts) if context_parts else "검색 결과 없음"


async def summarize_results(
    question: str,
    gmail_results: list[dict],
    drive_results: list[dict],
    confluence_results: list[dict] | None = None,
    jira_results: list[dict] | None = None,
    user_id: str | None = None,
) -> str:
    context = _build_search_context(gmail_results, drive_results, confluence_results, jira_results)
    user_message = f"[검색 결과]\n{context}\n\n[질문]\n{question}"

    if _use_claude():
        claude = _get_claude_client()
        messages = [{"role": "user", "content": user_message}]

        print("[DEBUG] [AI] 요약 생성: Claude (claude-sonnet-4-20250514)")
        response = await claude.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=2048,
            system=SYSTEM_PROMPT,
            messages=messages,
        )
        return response.content[0].text

    # Gemini fallback
    print("[DEBUG] [AI] 요약 생성: Gemini (gemini-2.5-flash)")
    client = _get_client()
    prompt = f"{SYSTEM_PROMPT}\n\n{user_message}"
    response = await client.aio.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt,
    )
    return response.text

ENTITY_SUMMARY_PROMPT = """\
당신은 엔티티 중심으로 검색 결과를 요약하는 AI 어시스턴트입니다.

아래 검색 결과를 분석하여 "{entity_name}" ({entity_type})에 대한 요약문을 작성하세요.

요약문에 반드시 포함할 내용:
1. **주요 이벤트**: 시간순으로 핵심 이벤트를 정리 (최대 5개)
2. **관련 담당자**: 검색 결과에 등장하는 담당자 목록
3. **미결 사항 수**: Jira에서 상태가 완료/done이 아닌 이슈 수

규칙:
- 한국어로 작성하세요
- 간결하게 요약하세요 (최대 500자)
- 검색 결과에 없는 내용을 지어내지 마세요
- 검색 결과가 없으면 "관련 정보를 찾지 못했습니다."라고 답하세요
"""


async def summarize_entity_results(
    entity_name: str,
    entity_type: str,
    gmail_results: list[dict],
    drive_results: list[dict],
    confluence_results: list[dict],
    jira_results: list[dict],
    user_id: str | None = None,
) -> str:
    """엔티티 중심으로 검색 결과를 요약한다.

    요약문에 포함할 내용:
    - 주요 이벤트 타임라인
    - 관련 담당자 목록
    - 미결 사항 수 (Jira 오픈 이슈)
    """
    context_parts: list[str] = []

    if gmail_results:
        context_parts.append("=== Gmail 검색 결과 ===")
        for m in gmail_results:
            context_parts.append(
                f"- 제목: {m.get('subject', '')}\n  보낸이: {m.get('from', '')}\n  내용 요약: {m.get('snippet', '')}"
            )

    if drive_results:
        context_parts.append("\n=== Drive 파일 목록 ===")
        for f in drive_results:
            context_parts.append(
                f"- {f.get('name', '')} (최근 수정: {f.get('modified', '')})"
            )

    if confluence_results:
        context_parts.append("\n=== Confluence 검색 결과 ===")
        for c in confluence_results:
            context_parts.append(
                f"- 제목: {c.get('title', '')}\n  내용 요약: {c.get('content_summary', '')}\n  수정일: {c.get('modified', '')}"
            )

    if jira_results:
        context_parts.append("\n=== Jira 검색 결과 ===")
        for j in jira_results:
            context_parts.append(
                f"- [{j.get('key', '')}] {j.get('title', '')}\n  상태: {j.get('status', '')}\n  담당자: {j.get('assignee', '')}\n  우선순위: {j.get('priority', '')}"
            )

    context = "\n".join(context_parts) if context_parts else "검색 결과 없음"

    system_prompt = ENTITY_SUMMARY_PROMPT.format(
        entity_name=entity_name,
        entity_type=entity_type,
    )
    user_message = f"[검색 결과]\n{context}"

    if _use_claude():
        claude = _get_claude_client()
        messages = [{"role": "user", "content": user_message}]

        print("[DEBUG] [AI] 엔티티 요약: Claude (claude-sonnet-4-20250514)")
        response = await claude.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=2048,
            system=system_prompt,
            messages=messages,
        )
        return response.content[0].text

    # Gemini fallback
    print("[DEBUG] [AI] 엔티티 요약: Gemini (gemini-2.5-flash)")
    client = _get_client()
    prompt = system_prompt + f"\n\n{user_message}"
    response = await client.aio.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt,
    )
    return response.text




# ---------------------------------------------------------------------------
# AI 관련성 필터링 (방법 1)
# ---------------------------------------------------------------------------

_RELEVANCE_FILTER_PROMPT = """\
아래 검색 결과 목록에서 "{keyword}" 키워드와 **직접적으로 관련된 항목만** 골라주세요.

판단 기준:
- 제목이나 핵심 내용이 "{keyword}"에 대한 것이면 관련 있음 (O)
- 메일 서명, CC/BCC에만 포함되거나, 본문에서 단순 언급만 된 경우는 관련 없음 (X)
- 파일명이나 페이지 제목에 "{keyword}"가 포함되어 있으면 관련 있음 (O)
- Jira 이슈 제목이나 설명이 "{keyword}"에 대한 것이면 관련 있음 (O)

반드시 아래 JSON 형식으로만 응답하세요. 다른 텍스트 없이 JSON만 출력하세요:
{{"relevant_indices": [0, 2, 5]}}

관련 있는 항목의 인덱스(0부터 시작)를 배열로 반환하세요.
관련 있는 항목이 하나도 없으면 빈 배열을 반환하세요: {{"relevant_indices": []}}
"""


async def filter_irrelevant_results(
    keyword: str,
    results: list[dict],
    source_type: str,
) -> list[dict]:
    """AI를 사용하여 검색 결과에서 관련 없는 항목을 필터링한다.

    Parameters:
        keyword: 검색 키워드
        results: 플랫폼 검색 결과 리스트
        source_type: "gmail" | "drive" | "confluence" | "jira"

    Returns:
        관련 있는 결과만 포함된 리스트
    """
    if not results:
        return results

    # 결과가 3개 이하면 필터링 불필요 (비용 절감)
    if len(results) <= 3:
        return results

    client = _get_client()

    # 결과를 간략한 텍스트로 변환
    items_text: list[str] = []
    for i, r in enumerate(results):
        if source_type == "gmail":
            items_text.append(
                f"[{i}] 제목: {r.get('subject', '')}, 보낸이: {r.get('from', '')}, "
                f"내용: {r.get('content_summary', r.get('snippet', ''))[:100]}"
            )
        elif source_type == "drive":
            items_text.append(f"[{i}] 파일명: {r.get('name', '')}")
        elif source_type == "confluence":
            items_text.append(
                f"[{i}] 제목: {r.get('title', '')}, "
                f"내용: {r.get('content_summary', '')[:100]}"
            )
        elif source_type == "jira":
            items_text.append(
                f"[{i}] [{r.get('key', '')}] {r.get('title', '')}, "
                f"상태: {r.get('status', '')}"
            )

    prompt = _RELEVANCE_FILTER_PROMPT.format(keyword=keyword) + "\n\n" + "\n".join(items_text)

    try:
        print(f"[DEBUG] [AI] 관련성 필터링 ({source_type}): Gemini (gemini-2.5-flash)")
        response = await client.aio.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
        )
        raw = response.text.strip()
        # Strip markdown code fences if present
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
            if raw.endswith("```"):
                raw = raw[:-3].strip()

        parsed = json.loads(raw)
        indices = parsed.get("relevant_indices", [])

        if not isinstance(indices, list):
            return results

        filtered = [results[i] for i in indices if isinstance(i, int) and 0 <= i < len(results)]

        logger.info(
            "AI 관련성 필터링: %s %d건 → %d건 (keyword=%s)",
            source_type, len(results), len(filtered), keyword,
        )
        return filtered

    except Exception:
        logger.exception("AI 관련성 필터링 실패 (keyword=%s, source=%s) — 원본 결과 유지", keyword, source_type)
        return results


# ---------------------------------------------------------------------------
# AI 카테고리 필터링 (프로젝트 기반 검색용)
# ---------------------------------------------------------------------------

_CATEGORY_FILTER_PROMPT = """\
아래 문서 목록에서 **{category_description}**에 해당하는 문서만 골라주세요.

판단 기준:
- "사업 관련": 제안서, 기안서, 견적서, 계약서, 발주서, 검수서, 사업계획, 고객 요구사항, \
RFP, 입찰, 수주, 회의록(사업 논의), 고객 미팅, 프로젝트 관리 문서 등
- "개발 관련": API 문서, SDK 가이드, 연동 가이드, 설계 문서, 테스트 케이스, 개발 명세, \
코드 리뷰, 아키텍처, 스펙, 배포, 인프라, 기술 검토 등

제목이나 내용 요약을 보고 판단하세요.
양쪽 모두에 해당할 수 있는 문서(예: 프로젝트 일정, 킥오프 회의록)는 포함시키세요.
판단이 어려운 경우에도 포함시키세요.

반드시 아래 JSON 형식으로만 응답하세요. 다른 텍스트 없이 JSON만 출력하세요:
{{"relevant_indices": [0, 2, 5]}}

관련 있는 항목의 인덱스(0부터 시작)를 배열로 반환하세요.
모든 항목이 관련 있으면 전체 인덱스를 반환하세요.
"""


async def filter_by_category(
    category: str,
    category_description: str,
    results: list[dict],
    source_type: str,
) -> list[dict]:
    """AI를 사용하여 카테고리(사업/개발)에 맞는 문서만 필터링한다.

    Parameters:
        category: "business" | "development"
        category_description: 카테고리 설명 문자열
        results: 플랫폼 검색 결과 리스트
        source_type: "gmail" | "drive" | "confluence" | "jira"

    Returns:
        카테고리에 맞는 결과만 포함된 리스트
    """
    if not results:
        return results

    # 결과가 3개 이하면 필터링 불필요
    if len(results) <= 3:
        return results

    # 결과를 간략한 텍스트로 변환
    items_text: list[str] = []
    for i, r in enumerate(results):
        if source_type == "gmail":
            items_text.append(
                f"[{i}] 제목: {r.get('subject', '')}, 보낸이: {r.get('from', '')}, "
                f"내용: {r.get('content_summary', r.get('snippet', ''))[:100]}"
            )
        elif source_type == "drive":
            items_text.append(f"[{i}] 파일명: {r.get('name', '')}")
        elif source_type == "confluence":
            items_text.append(
                f"[{i}] 제목: {r.get('title', '')}, "
                f"내용: {r.get('content_summary', '')[:100]}"
            )
        elif source_type == "jira":
            items_text.append(
                f"[{i}] [{r.get('key', '')}] {r.get('title', '')}, "
                f"상태: {r.get('status', '')}"
            )

    prompt = (
        _CATEGORY_FILTER_PROMPT.format(category_description=category_description)
        + "\n\n"
        + "\n".join(items_text)
    )

    try:
        if _use_claude():
            claude = _get_claude_client()
            print(f"[DEBUG] [AI] 카테고리 필터링 ({source_type}): Claude")
            response = await claude.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=256,
                system="반드시 JSON만 출력하세요. 다른 텍스트 없이 JSON만 출력하세요.",
                messages=[{"role": "user", "content": prompt}],
            )
            raw = response.content[0].text.strip()
        else:
            client = _get_client()
            print(f"[DEBUG] [AI] 카테고리 필터링 ({source_type}): Gemini")
            response = await client.aio.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt,
            )
            raw = response.text.strip()

        # Strip markdown code fences if present
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
            if raw.endswith("```"):
                raw = raw[:-3].strip()

        parsed = json.loads(raw)
        indices = parsed.get("relevant_indices", [])

        if not isinstance(indices, list):
            return results

        filtered = [results[i] for i in indices if isinstance(i, int) and 0 <= i < len(results)]

        logger.info(
            "AI 카테고리 필터링: %s %d건 → %d건 (category=%s)",
            source_type, len(results), len(filtered), category,
        )
        return filtered

    except Exception:
        logger.exception(
            "AI 카테고리 필터링 실패 (category=%s, source=%s) — 원본 결과 유지",
            category, source_type,
        )
        return results


CHAT_SYSTEM_PROMPT = """당신은 친절한 한국어 AI 어시스턴트입니다.
사용자와 자연스럽게 대화하세요. 간결하고 친근하게 답변하세요."""


async def generate_chat_response(user_text: str, user_id: str | None = None) -> str:
    """일반 대화 의도에 대해 AI 직접 대화 응답을 생성한다.

    Claude가 설정되어 있으면 Claude를 사용하고, 아니면 Gemini fallback.
    user_id가 주어지면 멀티턴 대화 히스토리를 활용한다.
    """
    if _use_claude():
        claude = _get_claude_client()
        messages = [{"role": "user", "content": user_text}]

        print("[DEBUG] [AI] 채팅 응답: Claude (claude-sonnet-4-20250514)")
        response = await claude.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1024,
            system=CHAT_SYSTEM_PROMPT,
            messages=messages,
        )
        return response.content[0].text

    # Gemini fallback
    print("[DEBUG] [AI] 채팅 응답: Gemini (gemini-2.5-flash)")
    client = _get_client()
    prompt = f"{CHAT_SYSTEM_PROMPT}\n\n사용자: {user_text}"
    response = await client.aio.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt,
    )
    return response.text
