import os
from pathlib import Path
from logging.config import fileConfig

# .env 파일에서 환경 변수 로드 (alembic CLI는 pydantic settings를 거치지 않으므로 직접 파싱)
_env_file = Path(__file__).parent.parent / ".env"
if _env_file.exists():
    for line in _env_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, val = line.partition("=")
            os.environ.setdefault(key.strip(), val.strip())

from sqlalchemy import engine_from_config
from sqlalchemy import pool

from alembic import context

# model imports to register metadata
from app.models.user import User  # noqa: F401
from app.models.oauth_state import OAuthState  # noqa: F401
from app.database import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

# Alembic은 동기 드라이버 필요 - asyncpg → psycopg2 스킴 변환
url = (
    os.environ["DATABASE_URL"]
    .replace("postgresql+asyncpg://", "postgresql://")
    .replace("?ssl=require", "?sslmode=require")
)
config.set_main_option("sqlalchemy.url", url)


def run_migrations_offline() -> None:
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
