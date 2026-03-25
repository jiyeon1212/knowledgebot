import asyncio
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials


def build_drive_service(access_token: str):
    creds = Credentials(token=access_token)
    return build("drive", "v3", credentials=creds)


def _escape_drive_query(query: str) -> str:
    """Drive API 쿼리 문자열의 단따옴표를 이스케이프한다."""
    return query.replace("\\", "\\\\").replace("'", "\\'")


async def search_drive(access_token: str, query: str, max_results: int = 10, date_from: str | None = None, date_to: str | None = None) -> list[dict]:
    service = build_drive_service(access_token)

    def _fetch():
        safe_query = _escape_drive_query(query)
        words = safe_query.split()

        # fullText contains는 파일명 + 본문 모두 검색
        # 단어별 OR로 검색 + _로 연결된 변형도 추가 (supercycl_testcase 등)
        if words:
            search_terms = set(words)
            # _로 연결된 변형 추가: ["supercycl", "testcase"] → "supercycl_testcase"
            if len(words) >= 2:
                search_terms.add("_".join(words))
            # 각 단어에 _가 포함되어 있으면 분리해서 추가
            for w in words:
                if "_" in w:
                    search_terms.update(w.split("_"))
            conditions = " or ".join(f"fullText contains '{t}'" for t in search_terms)
            drive_query = f"({conditions}) and trashed = false"
        else:
            drive_query = f"fullText contains '{safe_query}' and trashed = false"

        # 날짜 필터 적용 (Drive: modifiedTime >= 'YYYY-MM-DDT00:00:00')
        if date_from:
            drive_query += f" and modifiedTime >= '{date_from}T00:00:00'"
        if date_to:
            drive_query += f" and modifiedTime <= '{date_to}T23:59:59'"
        print(f"[DEBUG] Drive API query: '{drive_query}'")
        resp = service.files().list(
            q=drive_query,
            pageSize=max_results,
            orderBy="modifiedTime desc",
            fields="files(id, name, mimeType, modifiedTime, webViewLink)",
            supportsAllDrives=True,
            includeItemsFromAllDrives=True,
            corpora="allDrives",
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
