from google import genai
from app.config import settings

SYSTEM_PROMPT = """당신은 사용자의 Gmail과 Google Drive 데이터를 검색해 질문에 답하는 AI 어시스턴트입니다.
검색 결과를 바탕으로 한국어로 간결하고 정확하게 답변하세요.
관련 정보가 없으면 "관련 정보를 찾지 못했습니다."라고 답하세요."""

_client = None


def _get_client() -> genai.Client:
    global _client
    if _client is None:
        _client = genai.Client(api_key=settings.gemini_api_key)
    return _client


async def extract_search_query(user_text: str) -> str:
    """자연어 질문에서 Gmail/Drive 검색에 적합한 키워드를 추출한다."""
    client = _get_client()
    prompt = (
        "사용자가 Gmail과 Google Drive에서 정보를 찾으려고 합니다.\n"
        "아래 자연어 질문에서 검색에 사용할 핵심 키워드만 추출하세요.\n"
        "Gmail 검색 문법(newer_than:7d, from:, subject: 등)을 활용해도 됩니다.\n"
        "검색 키워드만 한 줄로 출력하세요. 설명 없이.\n\n"
        f"질문: {user_text}\n"
        "검색 키워드:"
    )
    response = await client.aio.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt,
    )
    keyword = response.text.strip().strip('"').strip("'")
    return keyword


async def summarize_results(question: str, gmail_results: list[dict], drive_results: list[dict]) -> str:
    client = _get_client()

    context_parts = []
    if gmail_results:
        context_parts.append("=== Gmail 검색 결과 ===")
        for m in gmail_results:
            context_parts.append(f"- 제목: {m['subject']}\n  보낸이: {m['from']}\n  내용 요약: {m['snippet']}")

    if drive_results:
        context_parts.append("\n=== Drive 파일 목록 ===")
        for f in drive_results:
            context_parts.append(f"- {f['name']} (최근 수정: {f['modified']})\n  링크: {f['link']}")

    context = "\n".join(context_parts) if context_parts else "검색 결과 없음"
    prompt = f"{SYSTEM_PROMPT}\n\n[검색 결과]\n{context}\n\n[질문]\n{question}"
    response = await client.aio.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt,
    )
    return response.text
