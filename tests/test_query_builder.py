"""query_builder 단위 테스트."""

import pytest
from app.search.query_builder import (
    parse_project_names,
    resolve_period,
    build_gmail_query,
    is_project_search,
    parse_search_command,
)


class TestParseProjectNames:
    def test_single_name(self):
        assert parse_project_names("상호운용") == ["상호운용"]

    def test_multiple_names(self):
        assert parse_project_names("kbtf, k-btf") == ["kbtf", "k-btf"]

    def test_whitespace_handling(self):
        assert parse_project_names("  미래에셋 , 신한  ") == ["미래에셋", "신한"]

    def test_empty_string(self):
        assert parse_project_names("") == []

    def test_trailing_comma(self):
        assert parse_project_names("상호운용,") == ["상호운용"]


class TestResolvePeriod:
    def test_all(self):
        assert resolve_period("all") == (None, None)

    def test_none(self):
        assert resolve_period(None) == (None, None)

    def test_1m(self):
        date_from, date_to = resolve_period("1m")
        assert date_from is not None
        assert date_to is not None
        # date_from은 date_to보다 이전이어야 함
        assert date_from < date_to

    def test_3m(self):
        date_from, date_to = resolve_period("3m")
        assert date_from is not None
        assert date_from < date_to

    def test_6m(self):
        date_from, date_to = resolve_period("6m")
        assert date_from is not None
        assert date_from < date_to

    def test_invalid_period(self):
        assert resolve_period("invalid") == (None, None)


class TestBuildGmailQuery:
    def test_single_project_business(self):
        query = build_gmail_query(["미래에셋"], "business")
        assert "미래에셋" in query
        assert "제안서" in query
        assert "OR" in query

    def test_multiple_projects(self):
        query = build_gmail_query(["kbtf", "k-btf"], "development")
        assert "kbtf" in query
        assert "k-btf" in query
        assert "API" in query

    def test_with_dates(self):
        query = build_gmail_query(
            ["상호운용"], "business",
            date_from="2025-01-01", date_to="2025-06-30",
        )
        assert "after:2025/01/01" in query
        assert "before:2025/06/30" in query

    def test_unknown_category(self):
        query = build_gmail_query(["테스트"], "unknown")
        assert query == "테스트"


class TestIsProjectSearch:
    def test_valid(self):
        assert is_project_search("#검색 상호운용 /개발") is True

    def test_with_whitespace(self):
        assert is_project_search("  #검색 상호운용 /개발  ") is True

    def test_not_search(self):
        assert is_project_search("상호운용 관련 자료 찾아줘") is False

    def test_empty(self):
        assert is_project_search("") is False


class TestParseSearchCommand:
    def test_basic(self):
        result = parse_search_command("#검색 상호운용 /개발")
        assert result is not None
        assert result["project_names"] == ["상호운용"]
        assert result["category"] == "development"
        assert result["period_text"] is None

    def test_business_category(self):
        result = parse_search_command("#검색 미래에셋 /사업")
        assert result["category"] == "business"

    def test_multiple_projects(self):
        result = parse_search_command("#검색 kbtf, k-btf /개발")
        assert result["project_names"] == ["kbtf", "k-btf"]

    def test_with_period(self):
        result = parse_search_command("#검색 상호운용 /개발 /최근 3개월")
        assert result["period_text"] == "최근 3개월"

    def test_with_period_year(self):
        result = parse_search_command("#검색 미래에셋, 신한 /사업 /2025년 상반기")
        assert result["project_names"] == ["미래에셋", "신한"]
        assert result["category"] == "business"
        assert result["period_text"] == "2025년 상반기"

    def test_missing_category(self):
        result = parse_search_command("#검색 상호운용")
        assert result is None

    def test_invalid_category(self):
        result = parse_search_command("#검색 상호운용 /마케팅")
        assert result is None

    def test_empty_project(self):
        result = parse_search_command("#검색 /개발")
        assert result is None

    def test_not_search_format(self):
        result = parse_search_command("상호운용 관련 자료 찾아줘")
        assert result is None
