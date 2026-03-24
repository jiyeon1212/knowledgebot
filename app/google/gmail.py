import asyncio
import base64

from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials


def build_gmail_service(access_token: str):
    creds = Credentials(token=access_token)
    return build("gmail", "v1", credentials=creds)


def _extract_body_text(payload: dict) -> str:
    """Recursively extract plain text body from Gmail message payload."""
    mime_type = payload.get("mimeType", "")

    # Direct text/plain part
    if mime_type == "text/plain" and "body" in payload:
        data = payload["body"].get("data", "")
        if data:
            return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")

    # Multipart: recurse into parts
    parts = payload.get("parts", [])
    for part in parts:
        text = _extract_body_text(part)
        if text:
            return text

    return ""


def _extract_content_summary(detail: dict, max_length: int = 200) -> str:
    """Extract a content summary (~200 chars, 3-4 lines) from the email body.

    Falls back to snippet if body text is not available.
    """
    payload = detail.get("payload", {})
    body_text = _extract_body_text(payload)

    if not body_text:
        # Fallback to snippet
        body_text = detail.get("snippet", "")

    # Clean up whitespace and truncate
    body_text = body_text.strip()
    if len(body_text) > max_length:
        body_text = body_text[:max_length].rstrip() + "..."

    return body_text


async def search_gmail(access_token: str, query: str, max_results: int = 10) -> list[dict]:
    service = build_gmail_service(access_token)

    def _fetch():
        print(f"[DEBUG] Gmail API query: '{query}', token: {access_token[:20]}...", flush=True)
        resp = service.users().messages().list(userId="me", q=query, maxResults=max_results).execute()
        print(f"[DEBUG] Gmail API raw response keys: {list(resp.keys())}, count: {len(resp.get('messages', []))}", flush=True)
        messages = resp.get("messages", [])
        results = []
        for msg in messages:
            detail = service.users().messages().get(
                userId="me", id=msg["id"], format="full"
            ).execute()
            headers = {h["name"]: h["value"] for h in detail.get("payload", {}).get("headers", [])}

            # Extract content summary from body text
            content_summary = _extract_content_summary(detail)

            # Generate Gmail web link
            link = f"https://mail.google.com/mail/u/0/#inbox/{msg['id']}"

            # internalDate: epoch ms → ISO 8601 변환
            internal_date = detail.get("internalDate", "")

            results.append({
                "id": msg["id"],
                "subject": headers.get("Subject", "(제목 없음)"),
                "from": headers.get("From", ""),
                "snippet": detail.get("snippet", ""),
                "content_summary": content_summary,
                "date": internal_date,
                "link": link,
            })
        return results

    return await asyncio.to_thread(_fetch)
