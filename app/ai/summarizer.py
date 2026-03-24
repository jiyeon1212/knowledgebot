from google import genai
from app.config import settings

SYSTEM_PROMPT = """당신은 사용자의 Gmail과 Google Drive 데이터를 검색해 질문에 답하는 AI 어시스턴트입니다.

## 답변 규칙
1. 한국어로 답변하세요.
2. 검색 결과를 아래 형식으로 정리하세요:
   - Gmail 메일이 있으면: 제목, 보낸이, 핵심 내용을 항목별로 정리
   - Drive 파일이 있으면: 파일명과 링크를 반드시 포함
3. Drive 파일의 링크는 절대 생략하지 마세요. 반드시 원본 링크를 포함하세요.
4. 관련 정보가 없으면 "관련 정보를 찾지 못했습니다."라고 답하세요.

## 답변 형식 예시
📧 **Gmail 검색 결과**
• [메일 제목] - 보낸이
  내용 요약

📁 **Drive 파일**
• [파일명](링크)
  최근 수정: 날짜"""

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
        "아래 자연어 질문에서 검색할 핵심 주제 키워드를 추출하세요.\n"
        "반드시 질문의 핵심 주제어(명사)를 포함해야 합니다.\n"
        "날짜 필터(newer_than 등)만 단독으로 출력하지 마세요.\n"
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
