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


# ---------------------------------------------------------------------------
# 프로젝트 기반 검색 (폴더 찾기 → 내부 파일 전체 조회)
# ---------------------------------------------------------------------------

async def search_drive_by_project(
    access_token: str,
    project_names: list[str],
    max_results: int = 50,
    date_from: str | None = None,
    date_to: str | None = None,
) -> list[dict]:
    """프로젝트명으로 폴더를 찾고 폴더 내 파일을 전부 조회한다.

    1. name contains '프로젝트명' and mimeType='application/vnd.google-apps.folder'
    2. '폴더ID' in parents 로 재귀적으로 하위 파일/폴더 조회
    """
    service = build_drive_service(access_token)

    def _fetch():
        all_results: list[dict] = []
        seen_ids: set[str] = set()

        for project_name in project_names:
            safe_name = _escape_drive_query(project_name)

            # 1단계: 프로젝트명으로 폴더 검색
            folder_query = (
                f"name contains '{safe_name}' "
                f"and mimeType = 'application/vnd.google-apps.folder' "
                f"and trashed = false"
            )
            folder_resp = service.files().list(
                q=folder_query,
                pageSize=10,
                fields="files(id, name)",
                supportsAllDrives=True,
                includeItemsFromAllDrives=True,
                corpora="allDrives",
            ).execute()

            folder_ids = [f["id"] for f in folder_resp.get("files", [])]

            # 2단계: 각 폴더 내 파일 재귀 조회
            folders_to_scan = list(folder_ids)
            while folders_to_scan:
                folder_id = folders_to_scan.pop(0)
                file_query = f"'{folder_id}' in parents and trashed = false"

                # 날짜 필터
                if date_from:
                    file_query += f" and modifiedTime >= '{date_from}T00:00:00'"
                if date_to:
                    file_query += f" and modifiedTime <= '{date_to}T23:59:59'"

                file_resp = service.files().list(
                    q=file_query,
                    pageSize=100,
                    orderBy="modifiedTime desc",
                    fields="files(id, name, mimeType, modifiedTime, webViewLink)",
                    supportsAllDrives=True,
                    includeItemsFromAllDrives=True,
                    corpora="allDrives",
                ).execute()

                for f in file_resp.get("files", []):
                    if f["id"] in seen_ids:
                        continue
                    seen_ids.add(f["id"])

                    if f.get("mimeType") == "application/vnd.google-apps.folder":
                        # 하위 폴더 → 재귀 탐색 큐에 추가
                        folders_to_scan.append(f["id"])
                    else:
                        all_results.append({
                            "id": f["id"],
                            "name": f["name"],
                            "mime_type": f.get("mimeType", ""),
                            "modified": f.get("modifiedTime", ""),
                            "link": f.get("webViewLink", ""),
                        })

                    if len(all_results) >= max_results:
                        return all_results

        return all_results[:max_results]

    return await asyncio.to_thread(_fetch)
