from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    slack_bot_token: str
    slack_app_token: str
    google_client_id: str
    google_client_secret: str
    google_redirect_uri: str
    database_url: str
    fernet_key: str
    app_base_url: str
    anthropic_api_key: str

    # Atlassian OAuth (빈 문자열이면 Atlassian 기능 비활성화)
    atlassian_client_id: str = ""
    atlassian_client_secret: str = ""
    atlassian_redirect_uri: str = ""


settings = Settings()
