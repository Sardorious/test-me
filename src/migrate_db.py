"""
Database migration/reset script.

This script will:
- Drop all existing tables (if they exist)
- Create all tables with the latest schema

WARNING: This will DELETE all existing data!
Only run this if you're okay with losing existing data.
"""
import asyncio

from .db import Base, engine, init_db
from . import models  # noqa: F401


async def reset_database() -> None:
    """Drop all tables and recreate them with the latest schema."""
    print("⚠️  WARNING: This will delete all existing data!")
    print("Dropping all tables...")
    
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    
    print("Creating new tables...")
    await init_db()
    
    print("✅ Database reset complete!")


async def create_tables_only() -> None:
    """Create tables if they don't exist (safe, won't delete data)."""
    print("Creating tables (if they don't exist)...")
    await init_db()
    print("✅ Done!")


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == "--reset":
        print("Resetting database...")
        asyncio.run(reset_database())
    else:
        print("Creating tables (safe mode)...")
        asyncio.run(create_tables_only())
        print("\nTo reset database (delete all data), run:")
        print("  python -m src.migrate_db --reset")

