import asyncio
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials


def build_gmail_service(access_token: str):
    creds = Credentials(token=access_token)
    return build("gmail", "v1", credentials=creds)


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
                userId="me", id=msg["id"], format="metadata"
            ).execute()
            headers = {h["name"]: h["value"] for h in detail.get("payload", {}).get("headers", [])}
            results.append({
                "id": msg["id"],
                "subject": headers.get("Subject", "(제목 없음)"),
                "from": headers.get("From", ""),
                "snippet": detail.get("snippet", ""),
            })
        return results

    return await asyncio.to_thread(_fetch)
