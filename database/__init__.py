"""Database engine for VMPM — async SQLAlchemy with SQLite.

STATUS: PREPARED BUT NOT INTEGRATED.
This module defines the async database engine and models for future use.
The current system uses models/knowledge.py (JSON file) for persistence.

To integrate: instantiate DatabaseEngine in the orchestrator and use
TradeRecord/KnowledgeEntry/DailyStats models for persistent storage.
"""

from __future__ import annotations

from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase

logger = structlog.get_logger(__name__)


class Base(DeclarativeBase):
    pass


class DatabaseEngine:
    """Async database engine for trade history and knowledge storage.

    NOTE: Not currently integrated into the trading pipeline.
    Prepared for future use when persistent storage is needed.
    """

    def __init__(self, url: str = "sqlite+aiosqlite:///vmpm.db") -> None:
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
