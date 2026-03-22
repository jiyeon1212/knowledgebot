from unittest.mock import patch, MagicMock


def test_build_auth_url_returns_google_url():
    from app.auth.google_oauth import build_auth_url
    url, state = build_auth_url()
    assert "accounts.google.com" in url
    assert len(state) >= 32  # 충분히 긴 랜덤 값


def test_build_auth_url_different_states_each_call():
    from app.auth.google_oauth import build_auth_url
    _, s1 = build_auth_url()
    _, s2 = build_auth_url()
    assert s1 != s2


def test_exchange_code_returns_token_dict():
    from app.auth.google_oauth import exchange_code_for_tokens
    mock_flow = MagicMock()
    mock_flow.credentials.token = "access"
    mock_flow.credentials.refresh_token = "refresh"
    mock_flow.credentials.expiry = None

    with patch("app.auth.google_oauth.Flow.from_client_config", return_value=mock_flow):
        result = exchange_code_for_tokens(code="auth_code")
    assert result["access_token"] == "access"
    assert result["refresh_token"] == "refresh"
