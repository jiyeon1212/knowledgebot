"""Block Kit Formatter 단위 테스트."""

from app.slack.block_kit import format_search_response


# ---------------------------------------------------------------------------
# 헬퍼: 블록 배열에서 특정 소스 헤더의 인덱스를 찾는다.
# ---------------------------------------------------------------------------

def _find_header(blocks, keyword):
    """blocks 에서 keyword 를 포함하는 section 블록의 인덱스를 반환한다."""
    for i, b in enumerate(blocks):
        if b.get("type") == "section" and keyword in b.get("text", {}).get("text", ""):
            return i
    return None


# ---------------------------------------------------------------------------
# 기본 구조 테스트
# ---------------------------------------------------------------------------

def test_summary_header_and_text():
    """요약 헤더('AI 요약')와 요약 텍스트가 첫 블록들에 표시된다."""
    blocks = format_search_response("요약 텍스트", [], [], [], [])
    assert "AI 요약" in blocks[0]["text"]["text"]
    assert blocks[1]["text"]["text"] == "요약 텍스트"


def test_long_summary_split():
    """3000자 초과 요약은 여러 section 블록으로 분할된다."""
    long_text = "가" * 5000
    blocks = format_search_response(long_text, [], [], [], [])
    # 첫 블록은 AI 요약 헤더
    assert "AI 요약" in blocks[0]["text"]["text"]
    # 요약 블록이 2개 이상이어야 함
    summary_blocks = []
    for b in blocks[1:]:
        if b.get("type") == "section" and b.get("text", {}).get("text", "").startswith("가"):
            summary_blocks.append(b)
        else:
            break
    assert len(summary_blocks) >= 2
    # 각 블록이 3000자 이하
    for sb in summary_blocks:
        assert len(sb["text"]["text"]) <= 3000


def test_all_sources_shown_even_when_empty():
    """결과가 0건이어도 4개 소스 헤더가 모두 표시된다."""
    blocks = format_search_response("요약", [], [], [], [])
    text_all = " ".join(b.get("text", {}).get("text", "") for b in blocks if b.get("type") == "section")
    assert "Gmail 검색 결과 (0건)" in text_all
    assert "Drive 검색 결과 (0건)" in text_all
    assert "Confluence 검색 결과 (0건)" in text_all
    assert "Jira 검색 결과 (0건)" in text_all


# ---------------------------------------------------------------------------
# Gmail
# ---------------------------------------------------------------------------

def test_gmail_results_section():
    """Gmail 결과가 있으면 헤더 + 항목 블록이 추가된다."""
    gmail = [
        {"subject": "회의록", "from": "alice@test.com", "content_summary": "내용 요약", "link": "https://mail.google.com/mail/u/0/#inbox/123"},
        {"subject": "보고서", "from": "bob@test.com", "link": "https://mail.google.com/mail/u/0/#inbox/456"},
    ]
    blocks = format_search_response("요약", gmail, [], [], [])
    idx = _find_header(blocks, "Gmail 검색 결과")
    assert idx is not None
    assert "(2건)" in blocks[idx]["text"]["text"]
    item = blocks[idx + 1]
    assert "회의록" in item["text"]["text"]
    assert "보낸이: alice@test.com" in item["text"]["text"]
    assert item["accessory"]["type"] == "button"
    assert item["accessory"]["text"]["text"] == "메일 열기"


# ---------------------------------------------------------------------------
# Drive
# ---------------------------------------------------------------------------

def test_drive_results_section():
    """Drive 결과가 있으면 헤더 + 항목 블록이 추가된다."""
    drive = [{"name": "설계문서.pdf", "modified": "2024-01-15", "link": "https://drive.google.com/file/d/abc"}]
    blocks = format_search_response("요약", [], drive, [], [])
    idx = _find_header(blocks, "Drive 검색 결과")
    assert idx is not None
    assert "(1건)" in blocks[idx]["text"]["text"]
    item = blocks[idx + 1]
    assert "설계문서.pdf" in item["text"]["text"]
    assert "수정일: 2024.01.15" in item["text"]["text"]
    assert item["accessory"]["text"]["text"] == "파일 열기"


# ---------------------------------------------------------------------------
# Confluence
# ---------------------------------------------------------------------------

def test_confluence_results_section():
    """Confluence 결과가 있으면 헤더 + 항목 블록이 추가된다."""
    confluence = [{"title": "API 가이드", "space_name": "DEV", "content_summary": "API 사용법", "modified": "2024-01-10", "link": "https://mysite.atlassian.net/wiki/page/1"}]
    blocks = format_search_response("요약", [], [], confluence, [])
    idx = _find_header(blocks, "Confluence 검색 결과")
    assert idx is not None
    assert "(1건)" in blocks[idx]["text"]["text"]
    item = blocks[idx + 1]
    assert "API 가이드" in item["text"]["text"]
    assert "DEV" in item["text"]["text"]
    assert item["accessory"]["text"]["text"] == "페이지 열기"


# ---------------------------------------------------------------------------
# Jira
# ---------------------------------------------------------------------------

def test_jira_results_section():
    """Jira 결과가 있으면 헤더 + 항목 블록이 추가된다."""
    jira = [{"key": "PROJ-123", "title": "버그 수정", "status": "진행 중", "assignee": "홍길동", "priority": "High", "link": "https://mysite.atlassian.net/browse/PROJ-123"}]
    blocks = format_search_response("요약", [], [], [], jira)
    idx = _find_header(blocks, "Jira 검색 결과")
    assert idx is not None
    assert "(1건)" in blocks[idx]["text"]["text"]
    item = blocks[idx + 1]
    assert "[PROJ-123] 버그 수정" in item["text"]["text"]
    assert "🟡" in item["text"]["text"]
    assert "담당자: 홍길동" in item["text"]["text"]
    assert "우선순위: High" in item["text"]["text"]
    assert item["accessory"]["text"]["text"] == "이슈 열기"


def test_jira_status_emojis():
    """Jira 상태별 올바른 이모지가 표시된다."""
    statuses = [
        ("완료", "🟢"), ("Done", "🟢"),
        ("진행중", "🟡"), ("In Progress", "🟡"),
        ("할일", "🔴"), ("To Do", "🔴"),
        ("기타상태", "⚪"),
    ]
    for status_text, expected_emoji in statuses:
        jira = [{"key": "T-1", "title": "테스트", "status": status_text}]
        blocks = format_search_response("요약", [], [], [], jira)
        idx = _find_header(blocks, "Jira 검색 결과")
        item = blocks[idx + 1]
        assert expected_emoji in item["text"]["text"], f"status={status_text!r} should have {expected_emoji}"


# ---------------------------------------------------------------------------
# Divider 구분
# ---------------------------------------------------------------------------

def test_all_sources_with_dividers():
    """CP-5: 4개 소스 모두 결과가 있으면 각 소스가 divider로 구분된다."""
    gmail = [{"subject": "메일1", "from": "a@b.com"}, {"subject": "메일2", "from": "c@d.com"}]
    drive = [{"name": "파일1"}]
    confluence = [{"title": "페이지1"}]
    jira = [{"key": "T-1", "title": "이슈1"}]

    blocks = format_search_response("요약", gmail, drive, confluence, jira)
    dividers = [b for b in blocks if b["type"] == "divider"]
    assert len(dividers) == 4  # 소스 4개 → divider 4개


# ---------------------------------------------------------------------------
# 연결 버튼
# ---------------------------------------------------------------------------

def test_connect_google_button():
    """Google 미연결 시 연결 안내 버튼이 추가된다."""
    blocks = format_search_response(
        "요약", [], [], [], [],
        connect_google=True,
        google_auth_url="https://accounts.google.com/o/oauth2/auth?...",
    )
    actions = [b for b in blocks if b["type"] == "actions"]
    assert len(actions) == 1
    assert actions[0]["elements"][0]["action_id"] == "google_oauth_login"


def test_connect_atlassian_button():
    """CP-9: Atlassian 미연결 시 연결 안내 버튼이 추가된다."""
    blocks = format_search_response(
        "요약", [], [], [], [],
        connect_atlassian=True,
        atlassian_auth_url="https://auth.atlassian.com/authorize?...",
    )
    actions = [b for b in blocks if b["type"] == "actions"]
    assert len(actions) == 1
    assert actions[0]["elements"][0]["action_id"] == "atlassian_oauth_login"


def test_connect_buttons_without_urls_are_skipped():
    """URL이 없으면 연결 버튼이 추가되지 않는다."""
    blocks = format_search_response(
        "요약", [], [], [], [],
        connect_google=True,
        connect_atlassian=True,
    )
    actions = [b for b in blocks if b["type"] == "actions"]
    assert len(actions) == 0


def test_both_connect_buttons():
    """두 서비스 모두 미연결 시 두 개의 연결 버튼이 추가된다."""
    blocks = format_search_response(
        "요약", [], [], [], [],
        connect_google=True,
        connect_atlassian=True,
        google_auth_url="https://google.com/auth",
        atlassian_auth_url="https://atlassian.com/auth",
    )
    actions = [b for b in blocks if b["type"] == "actions"]
    assert len(actions) == 2


def test_no_accessory_when_no_link():
    """링크가 없는 항목에는 accessory 버튼이 없다."""
    gmail = [{"subject": "제목", "from": "a@b.com"}]
    blocks = format_search_response("요약", gmail, [], [], [])
    idx = _find_header(blocks, "Gmail 검색 결과")
    item = blocks[idx + 1]
    assert "accessory" not in item
