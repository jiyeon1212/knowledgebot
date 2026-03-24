"""엔티티 검색 핸들러 단위 테스트."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.search.entity_search import (
    handle_entity_search,
    execute_entity_search,
    find_similar_entities,
    _filter_recent_results,
)


# ---------------------------------------------------------------------------
# handle_entity_search tests
# ---------------------------------------------------------------------------


class TestHandleEntitySearch:
    """handle_entity_search 함수 테스트."""

    async def test_multiple_entities_shows_candidates(self):
        """엔티티 후보가 2개 이상이면 format_entity_candidates로 Slack 버튼을 표시한다."""
        mock_say = AsyncMock()
        entities = [
            {"name": "신한은행", "type": "고객사"},
            {"name": "신한캐피탈", "type": "고객사"},
        ]

        with patch(
            "app.search.entity_search.format_entity_candidates",
            return_value=[{"type": "actions", "elements": []}],
        ) as mock_format:
            await handle_entity_search(
                user_id="U_TEST",
                entities=entities,
                original_text="신한 관련 히스토리",
                say=mock_say,
            )

        mock_format.assert_called_once_with(entities, "신한 관련 히스토리")
        mock_say.assert_called_once()
        call_kwargs = mock_say.call_args[1]
        assert "blocks" in call_kwargs

    async def test_single_entity_calls_execute(self):
        """엔티티 후보가 1개이면 execute_entity_search를 즉시 호출한다."""
        mock_say = AsyncMock()
        entities = [{"name": "신한은행", "type": "고객사"}]

        with patch(
            "app.search.entity_search.execute_entity_search",
            new_callable=AsyncMock,
        ) as mock_execute:
            await handle_entity_search(
                user_id="U_TEST",
                entities=entities,
                original_text="신한은행 히스토리",
                say=mock_say,
            )

        mock_execute.assert_called_once_with(
            user_id="U_TEST",
            entity_name="신한은행",
            entity_type="고객사",
            say=mock_say,
        )


# ---------------------------------------------------------------------------
# execute_entity_search tests
# ---------------------------------------------------------------------------


def _mock_db_with_users(google_user=None, atlassian_user=None):
    """Create a mock DB session that returns the given users."""
    mock_db = AsyncMock()
    google_result = MagicMock()
    google_result.scalar_one_or_none = MagicMock(return_value=google_user)
    atlassian_result = MagicMock()
    atlassian_result.scalar_one_or_none = MagicMock(return_value=atlassian_user)
    mock_db.execute = AsyncMock(side_effect=[google_result, atlassian_result])
    return mock_db


class TestExecuteEntitySearch:
    """execute_entity_search 함수 테스트."""

    async def test_no_accounts_shows_connect_message(self):
        """계정 미연결 시 연결 안내 메시지를 표시한다."""
        mock_say = AsyncMock()
        mock_db = _mock_db_with_users(google_user=None, atlassian_user=None)

        with patch("app.search.entity_search.AsyncSessionLocal") as mock_session_cls:
            mock_session_cls.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_session_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            await execute_entity_search(
                user_id="U_NEW",
                entity_name="신한은행",
                entity_type="고객사",
                say=mock_say,
            )

        # First call is the "searching..." message, second is the connect message
        assert mock_say.call_count == 2
        last_call_args = mock_say.call_args[0][0]
        assert "연결" in last_call_args

    async def test_platform_errors_return_empty_lists(self):
        """개별 플랫폼 오류 시 빈 리스트로 처리하고 나머지 결과를 반환한다."""
        mock_say = AsyncMock()
        mock_google_user = MagicMock()
        mock_db = _mock_db_with_users(google_user=mock_google_user, atlassian_user=None)

        with (
            patch("app.search.entity_search.AsyncSessionLocal") as mock_session_cls,
            patch("app.search.entity_search.get_valid_access_token", AsyncMock(return_value="token")),
            patch("app.search.entity_search.search_gmail", AsyncMock(side_effect=Exception("Gmail error"))),
            patch("app.search.entity_search.search_drive", AsyncMock(return_value=[
                {"name": "doc.pdf", "modified": "2025-01-01T00:00:00Z", "link": "https://drive.google.com/1"}
            ])),
            patch("app.search.entity_search.group_results") as mock_group,
            patch("app.search.entity_search.summarize_entity_results", AsyncMock(return_value="요약")),
            patch("app.search.entity_search.format_entity_timeline", return_value=[{"type": "section"}]),
        ):
            mock_session_cls.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_session_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            mock_group.return_value = MagicMock(
                timeline=[], open_issues=[], contacts=[], total_count=1, filtered=False
            )

            await execute_entity_search(
                user_id="U_TEST",
                entity_name="테스트",
                entity_type="프로젝트",
                say=mock_say,
            )

        # group_results should be called with gmail_results=[] (error) and drive_results with data
        mock_group.assert_called_once()
        call_kwargs = mock_group.call_args[1]
        assert call_kwargs["gmail_results"] == []
        assert len(call_kwargs["drive_results"]) == 1

    async def test_zero_results_calls_find_similar(self):
        """검색 결과 0건 시 find_similar_entities를 호출한다."""
        mock_say = AsyncMock()
        mock_google_user = MagicMock()
        mock_db = _mock_db_with_users(google_user=mock_google_user, atlassian_user=None)

        with (
            patch("app.search.entity_search.AsyncSessionLocal") as mock_session_cls,
            patch("app.search.entity_search.get_valid_access_token", AsyncMock(return_value="token")),
            patch("app.search.entity_search.search_gmail", AsyncMock(return_value=[])),
            patch("app.search.entity_search.search_drive", AsyncMock(return_value=[])),
            patch("app.search.entity_search.find_similar_entities", AsyncMock(return_value=[])) as mock_find,
        ):
            mock_session_cls.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_session_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            await execute_entity_search(
                user_id="U_TEST",
                entity_name="없는엔티티",
                entity_type="고객사",
                say=mock_say,
            )

        mock_find.assert_called_once()
        # Last say call should be the "no results" message
        last_msg = mock_say.call_args[0][0]
        assert "찾을 수 없습니다" in last_msg


# ---------------------------------------------------------------------------
# _filter_recent_results tests
# ---------------------------------------------------------------------------


class TestFilterRecentResults:
    """_filter_recent_results 함수 테스트."""

    def test_filters_old_results(self):
        """cutoff 이전 결과를 필터링한다."""
        from datetime import datetime, timezone

        cutoff = datetime(2025, 1, 1, tzinfo=timezone.utc)
        results = [
            {"date": "2025-06-01T00:00:00+00:00", "title": "recent"},
            {"date": "2024-06-01T00:00:00+00:00", "title": "old"},
        ]
        filtered = _filter_recent_results(results, "date", cutoff)
        assert len(filtered) == 1
        assert filtered[0]["title"] == "recent"

    def test_keeps_items_without_date(self):
        """날짜 없는 항목은 유지한다."""
        from datetime import datetime, timezone

        cutoff = datetime(2025, 1, 1, tzinfo=timezone.utc)
        results = [
            {"title": "no date"},
            {"date": "", "title": "empty date"},
        ]
        filtered = _filter_recent_results(results, "date", cutoff)
        assert len(filtered) == 2


# ---------------------------------------------------------------------------
# find_similar_entities tests
# ---------------------------------------------------------------------------


class TestFindSimilarEntities:
    """find_similar_entities 함수 테스트."""

    async def test_returns_max_5_entities(self):
        """최대 5개까지만 반환한다."""
        mock_response = MagicMock()
        mock_response.text = '[{"name": "A", "type": "고객사"}, {"name": "B", "type": "담당자"}, {"name": "C", "type": "프로젝트"}, {"name": "D", "type": "팀"}, {"name": "E", "type": "고객사"}, {"name": "F", "type": "담당자"}]'

        mock_client = MagicMock()
        mock_client.aio.models.generate_content = AsyncMock(return_value=mock_response)

        with patch("app.search.entity_search._get_client", return_value=mock_client):
            result = await find_similar_entities("테스트", [])

        assert len(result) <= 5

    async def test_returns_empty_on_error(self):
        """오류 발생 시 빈 리스트를 반환한다."""
        mock_client = MagicMock()
        mock_client.aio.models.generate_content = AsyncMock(side_effect=Exception("API error"))

        with patch("app.search.entity_search._get_client", return_value=mock_client):
            result = await find_similar_entities("테스트", [])

        assert result == []

    async def test_handles_invalid_json(self):
        """잘못된 JSON 응답 시 빈 리스트를 반환한다."""
        mock_response = MagicMock()
        mock_response.text = "not valid json"

        mock_client = MagicMock()
        mock_client.aio.models.generate_content = AsyncMock(return_value=mock_response)

        with patch("app.search.entity_search._get_client", return_value=mock_client):
            result = await find_similar_entities("테스트", [])

        assert result == []
