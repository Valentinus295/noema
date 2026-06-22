"""Database engine for Noema.

Optional SQLAlchemy with SQLite for legacy models.
DuckDB journal (database/journal.py) is the primary trade log.
"""

from __future__ import annotations

from typing import Any

import structlog

logger = structlog.get_logger(__name__)

try:
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
    from sqlalchemy.orm import DeclarativeBase

    class Base(DeclarativeBase):
        pass

    _HAS_SQLALCHEMY = True
except ImportError:
    Base = type("Base", (), {})  # type: ignore[misc,assignment]
    _HAS_SQLALCHEMY = False
    logger.debug("sqlalchemy_not_available")


class DatabaseEngine:
    """Async database engine for trade history and knowledge storage.

    NOTE: Not currently integrated into the trading pipeline.
    Prepared for future use when persistent storage is needed.
    """

    def __init__(self, url: str = "sqlite+aiosqlite:///noema.db") -> None:
        if not _HAS_SQLALCHEMY:
            raise ImportError("SQLAlchemy is required for DatabaseEngine. Install with: pip install sqlalchemy aiosqlite")
        self.url = url
        self.engine = create_async_engine(url, echo=False)
        self.session_factory = async_sessionmaker(self.engine, class_=AsyncSession, expire_on_commit=False)

    async def initialize(self) -> None:
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self._logger = logger.bind(component="database")
        self._logger.info("database_initialized", url=self.url)

    async def get_session(self) -> AsyncSession:
        return self.session_factory()

    async def shutdown(self) -> None:
        await self.engine.dispose()
