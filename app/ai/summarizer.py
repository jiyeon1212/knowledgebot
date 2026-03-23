import google.generativeai as genai
from app.config import settings

SYSTEM_PROMPT = """당신은 사용자의 Gmail과 Google Drive 데이터를 검색해 질문에 답하는 AI 어시스턴트입니다.
검색 결과를 바탕으로 한국어로 간결하고 정확하게 답변하세요.
관련 정보가 없으면 "관련 정보를 찾지 못했습니다."라고 답하세요."""


def _get_model() -> genai.GenerativeModel:
    # 임포트 시점이 아닌 첫 호출 시점에 configure — 테스트 환경에서 env var 없이 임포트 가능
    genai.configure(api_key=settings.gemini_api_key)
    return genai.GenerativeModel("gemini-2.0-flash-lite")


async def summarize_results(question: str, gmail_results: list[dict], drive_results: list[dict]) -> str:
    model = _get_model()

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
    response = await model.generate_content_async(prompt)
    return response.text
