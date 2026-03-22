from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    slack_bot_token: str
    slack_app_token: str
    google_client_id: str
    google_client_secret: str
    google_redirect_uri: str
    gemini_api_key: str
    database_url: str
    fernet_key: str
    app_base_url: str

    class Config:
        env_file = ".env"


settings = Settings()
