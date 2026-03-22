import asyncio
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials


def build_drive_service(access_token: str):
    creds = Credentials(token=access_token)
    return build("drive", "v3", credentials=creds)


def _escape_drive_query(query: str) -> str:
    """Drive API 쿼리 문자열의 단따옴표를 이스케이프한다."""
    return query.replace("\\", "\\\\").replace("'", "\\'")


async def search_drive(access_token: str, query: str, max_results: int = 10) -> list[dict]:
    service = build_drive_service(access_token)

    def _fetch():
        safe_query = _escape_drive_query(query)
        drive_query = f"fullText contains '{safe_query}' and trashed = false"
        resp = service.files().list(
            q=drive_query,
            pageSize=max_results,
            fields="files(id, name, mimeType, modifiedTime, webViewLink)",
        ).execute()
        return [
            {
                "id": f["id"],
                "name": f["name"],
                "mime_type": f.get("mimeType", ""),
                "modified": f.get("modifiedTime", ""),
                "link": f.get("webViewLink", ""),
            }
            for f in resp.get("files", [])
        ]

    return await asyncio.to_thread(_fetch)
