"""
Database migration/reset script.

This script will:
- Drop all existing tables (if they exist)
- Create all tables with the latest schema

WARNING: This will DELETE all existing data!
Only run this if you're okay with losing existing data.
"""
import asyncio
import sys

from sqlalchemy.exc import OperationalError

from .db import Base, engine, init_db
from . import models  # noqa: F401
from .config import settings


def print_db_info() -> None:
    """Print current database configuration."""
    db_url = settings.db_url
    if "postgresql" in db_url:
        print(f"📊 Database: PostgreSQL")
        print(f"   Connection: {db_url.split('@')[1] if '@' in db_url else 'N/A'}")
    elif "sqlite" in db_url:
        print(f"📊 Database: SQLite")
        print(f"   File: {db_url.split('///')[-1] if '///' in db_url else 'N/A'}")
    else:
        print(f"📊 Database: {db_url.split('+')[0] if '+' in db_url else 'Unknown'}")


async def reset_database() -> None:
    """Drop all tables and recreate them with the latest schema."""
    print_db_info()
    print("\n⚠️  WARNING: This will delete all existing data!")
    print("Dropping all tables...")
    
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
        
        print("Creating new tables...")
        await init_db()
        
        print("✅ Database reset complete!")
    except Exception as e:
        print(f"\n❌ Error: {e}")
        if "postgresql" in settings.db_url.lower():
            print("\n💡 PostgreSQL connection failed. Possible issues:")
            print("   1. PostgreSQL is not installed or not running")
            print("   2. Database doesn't exist - create it first:")
            print("      sudo -u postgres psql")
            print("      CREATE DATABASE telegram_bot;")
            print("   3. Wrong credentials in DB_URL")
            print("   4. Use SQLite instead - set in .env:")
            print("      DB_URL=sqlite+aiosqlite:///./bot.db")
        elif "sqlite" in settings.db_url.lower():
            print("\n💡 SQLite error. Check file permissions.")
        sys.exit(1)


async def create_tables_only() -> None:
    """Create tables if they don't exist (safe, won't delete data)."""
    print_db_info()
    print("\nCreating tables (if they don't exist)...")
    
    try:
        await init_db()
        print("✅ Done!")
    except Exception as e:
        print(f"\n❌ Error: {e}")
        if "postgresql" in settings.db_url.lower():
            print("\n💡 PostgreSQL connection failed. Possible issues:")
            print("   1. PostgreSQL is not installed or not running")
            print("   2. Database doesn't exist - create it first:")
            print("      sudo -u postgres psql")
            print("      CREATE DATABASE telegram_bot;")
            print("   3. Wrong credentials in DB_URL")
            print("   4. Use SQLite instead - set in .env:")
            print("      DB_URL=sqlite+aiosqlite:///./bot.db")
        elif "sqlite" in settings.db_url.lower():
            print("\n💡 SQLite error. Check file permissions.")
        sys.exit(1)


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

