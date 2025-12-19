from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from .config import settings


class Base(DeclarativeBase):
    pass


engine: AsyncEngine = create_async_engine(settings.db_url, echo=False, future=True)
SessionLocal = async_sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with SessionLocal() as session:
        yield session


async def init_db() -> None:
    from . import models  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    # Run migrations after creating tables
    # Import here to avoid circular import
    try:
        from .migrate_db import migrate_to_unit_structure
        async with engine.begin() as conn:
            # Determine database type
            db_url = settings.db_url.lower()
            if "postgresql" in db_url:
                db_type = "postgresql"
            else:
                db_type = "sqlite"
            await migrate_to_unit_structure(conn, db_type)
    except Exception as e:
        # Migration errors shouldn't prevent bot from starting
        # But log them for debugging
        import sys
        print(f"⚠️  Migration warning: {e}", file=sys.stderr)


