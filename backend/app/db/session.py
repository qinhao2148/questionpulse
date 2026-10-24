from collections.abc import AsyncIterator

from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import get_settings

settings = get_settings()
engine = create_async_engine(settings.database_url, pool_pre_ping=True)
async_session_factory = async_sessionmaker(engine, expire_on_commit=False)


def _build_sync_database_url(url: str) -> str:
    # The ingestion worker is synchronous (parsing + embedding are blocking),
    # so it talks to MySQL through the pymysql driver instead of asyncmy.
    if url.startswith("mysql+asyncmy://"):
        return "mysql+pymysql://" + url.split("://", 1)[1]
    if url.startswith("sqlite+aiosqlite://"):
        return "sqlite+pysqlite://" + url.split("://", 1)[1]
    return url


_sync_engine = create_engine(
    _build_sync_database_url(settings.database_url),
    pool_pre_ping=True,
)
sync_session_factory = sessionmaker(bind=_sync_engine, expire_on_commit=False)


async def get_db() -> AsyncIterator[AsyncSession]:
    async with async_session_factory() as session:
        yield session


async def dispose_engine() -> None:
    await engine.dispose()
    _sync_engine.dispose()
