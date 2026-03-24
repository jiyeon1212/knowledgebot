"""Unit tests for app.search.result_grouper module."""

from app.search.result_grouper import (
    GroupedResults,
    TimelineItem,
    SOURCE_ICONS,
    _epoch_ms_to_iso,
    normalize_results,
    sort_by_date,
    extract_open_issues,
    extract_contacts,
    group_results,
)


# ---------------------------------------------------------------------------
# _epoch_ms_to_iso
# ---------------------------------------------------------------------------

class TestEpochMsToIso:
    def test_valid_epoch(self):
        # 2024-01-15T00:00:00+00:00 == 1705276800000 ms
        result = _epoch_ms_to_iso("1705276800000")
        assert result.startswith("2024-01-15")

    def test_empty_string(self):
        assert _epoch_ms_to_iso("") == ""

    def test_invalid_value(self):
        assert _epoch_ms_to_iso("not-a-number") == ""


# ---------------------------------------------------------------------------
# normalize_results
# ---------------------------------------------------------------------------

class TestNormalizeResults:
    def test_gmail_mapping(self):
        gmail = [{"date": "1705276800000", "subject": "Hello", "content_summary": "Body", "link": "http://g", "from": "a@b.com"}]
        items = normalize_results(gmail, [], [], [])
        assert len(items) == 1
        item = items[0]
        assert item.source == "gmail"
        assert item.title == "Hello"
        assert item.summary == "Body"
        assert item.link == "http://g"
        assert item.date.startswith("2024-01-15")
        assert item.metadata["from"] == "a@b.com"

    def test_drive_mapping(self):
        drive = [{"modified": "2024-03-01T10:00:00Z", "name": "doc.pdf", "link": "http://d", "mime_type": "application/pdf"}]
        items = normalize_results([], drive, [], [])
        assert len(items) == 1
        assert items[0].source == "drive"
        assert items[0].title == "doc.pdf"
        assert items[0].date == "2024-03-01T10:00:00Z"

    def test_confluence_mapping(self):
        conf = [{"modified": "2024-02-01T00:00:00Z", "title": "Page", "content_summary": "Summary", "link": "http://c", "space_name": "ENG"}]
        items = normalize_results([], [], conf, [])
        assert len(items) == 1
        assert items[0].source == "confluence"
        assert items[0].metadata["space_name"] == "ENG"

    def test_jira_mapping(self):
        jira = [{"updated": "2024-04-01T00:00:00Z", "title": "Bug", "key": "PROJ-1", "status": "진행중", "assignee": "홍길동", "priority": "High", "link": "http://j"}]
        items = normalize_results([], [], [], jira)
        assert len(items) == 1
        item = items[0]
        assert item.source == "jira"
        assert item.metadata["key"] == "PROJ-1"
        assert item.metadata["status"] == "진행중"
        assert item.metadata["assignee"] == "홍길동"

    def test_total_count_matches(self):
        gmail = [{"date": "", "subject": "a", "content_summary": "", "link": "", "from": ""}]
        drive = [{"modified": "", "name": "b", "link": "", "mime_type": ""}]
        conf = [{"modified": "", "title": "c", "content_summary": "", "link": "", "space_name": ""}]
        jira = [{"updated": "", "title": "d", "key": "", "status": "", "assignee": "", "priority": "", "link": ""}]
        items = normalize_results(gmail, drive, conf, jira)
        assert len(items) == 4

    def test_empty_inputs(self):
        items = normalize_results([], [], [], [])
        assert items == []


# ---------------------------------------------------------------------------
# sort_by_date
# ---------------------------------------------------------------------------

class TestSortByDate:
    def test_descending_order(self):
        items = [
            TimelineItem(date="2024-01-01T00:00:00Z", title="old", source="gmail", summary="", link=""),
            TimelineItem(date="2024-06-01T00:00:00Z", title="new", source="drive", summary="", link=""),
            TimelineItem(date="2024-03-01T00:00:00Z", title="mid", source="jira", summary="", link=""),
        ]
        sorted_items = sort_by_date(items)
        assert [i.title for i in sorted_items] == ["new", "mid", "old"]

    def test_ascending_order(self):
        items = [
            TimelineItem(date="2024-06-01T00:00:00Z", title="new", source="drive", summary="", link=""),
            TimelineItem(date="2024-01-01T00:00:00Z", title="old", source="gmail", summary="", link=""),
        ]
        sorted_items = sort_by_date(items, descending=False)
        assert [i.title for i in sorted_items] == ["old", "new"]

    def test_empty_dates_go_last_descending(self):
        items = [
            TimelineItem(date="", title="no-date", source="gmail", summary="", link=""),
            TimelineItem(date="2024-01-01T00:00:00Z", title="has-date", source="drive", summary="", link=""),
        ]
        sorted_items = sort_by_date(items)
        assert sorted_items[0].title == "has-date"
        assert sorted_items[1].title == "no-date"

    def test_empty_list(self):
        assert sort_by_date([]) == []


# ---------------------------------------------------------------------------
# extract_open_issues
# ---------------------------------------------------------------------------

class TestExtractOpenIssues:
    def test_extracts_non_done_jira(self):
        items = [
            TimelineItem(date="", title="Open", source="jira", summary="", link="", metadata={"status": "진행중"}),
            TimelineItem(date="", title="Done", source="jira", summary="", link="", metadata={"status": "완료"}),
            TimelineItem(date="", title="DoneEn", source="jira", summary="", link="", metadata={"status": "Done"}),
            TimelineItem(date="", title="Email", source="gmail", summary="", link="", metadata={}),
        ]
        open_issues = extract_open_issues(items)
        assert len(open_issues) == 1
        assert open_issues[0].title == "Open"

    def test_case_insensitive_done(self):
        items = [
            TimelineItem(date="", title="A", source="jira", summary="", link="", metadata={"status": "DONE"}),
            TimelineItem(date="", title="B", source="jira", summary="", link="", metadata={"status": "완료"}),
        ]
        assert extract_open_issues(items) == []

    def test_empty_list(self):
        assert extract_open_issues([]) == []


# ---------------------------------------------------------------------------
# extract_contacts
# ---------------------------------------------------------------------------

class TestExtractContacts:
    def test_extracts_gmail_and_jira(self):
        items = [
            TimelineItem(date="", title="", source="gmail", summary="", link="", metadata={"from": "alice@test.com"}),
            TimelineItem(date="", title="", source="jira", summary="", link="", metadata={"assignee": "홍길동"}),
        ]
        contacts = extract_contacts(items)
        assert "alice@test.com" in contacts
        assert "홍길동" in contacts

    def test_deduplication(self):
        items = [
            TimelineItem(date="", title="", source="jira", summary="", link="", metadata={"assignee": "홍길동"}),
            TimelineItem(date="", title="", source="jira", summary="", link="", metadata={"assignee": "홍길동"}),
        ]
        contacts = extract_contacts(items)
        assert contacts == ["홍길동"]

    def test_skips_unassigned(self):
        items = [
            TimelineItem(date="", title="", source="jira", summary="", link="", metadata={"assignee": "미지정"}),
        ]
        assert extract_contacts(items) == []

    def test_empty_list(self):
        assert extract_contacts([]) == []


# ---------------------------------------------------------------------------
# group_results
# ---------------------------------------------------------------------------

class TestGroupResults:
    def test_full_integration(self):
        gmail = [{"date": "1705276800000", "subject": "Mail", "content_summary": "body", "link": "http://g", "from": "a@b.com"}]
        jira = [{"updated": "2024-04-01T00:00:00Z", "title": "Bug", "key": "P-1", "status": "진행중", "assignee": "홍길동", "priority": "High", "link": "http://j"}]
        result = group_results(gmail, [], [], jira)

        assert isinstance(result, GroupedResults)
        assert result.total_count == 2
        assert result.filtered is False
        assert len(result.timeline) == 2
        # newest first
        assert result.timeline[0].source == "jira"
        assert len(result.open_issues) == 1
        assert "홍길동" in result.contacts

    def test_filtered_flag(self):
        result = group_results([], [], [], [], filtered=True)
        assert result.filtered is True


# ---------------------------------------------------------------------------
# SOURCE_ICONS
# ---------------------------------------------------------------------------

class TestSourceIcons:
    def test_all_sources_present(self):
        for src in ("gmail", "drive", "confluence", "jira"):
            assert src in SOURCE_ICONS
            assert len(SOURCE_ICONS[src]) > 0
