import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from app.models.user import Base as UserBase
from app.models.oauth_state import OAuthState  # noqa: F401 — Base.metadata에 테이블 등록 트리거
from app.database import get_db

TEST_DB_URL = "sqlite+aiosqlite:///:memory:"


@pytest_asyncio.fixture
async def db_session():
    from app.main import app  # 지연 임포트로 circular import 방지
    engine = create_async_engine(TEST_DB_URL)
    async with engine.begin() as conn:
        await conn.run_sync(UserBase.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        # FastAPI가 테스트 DB 세션을 사용하도록 dependency override
        async def override_get_db():
            yield session
        app.dependency_overrides[get_db] = override_get_db
        yield session
        app.dependency_overrides.clear()
    await engine.dispose()
