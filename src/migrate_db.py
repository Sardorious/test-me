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
        
        # Add missing columns to existing tables
        print("\nChecking for missing columns...")
        await add_missing_columns()
        
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


async def add_missing_columns() -> None:
    """Add missing columns to existing tables and migrate role column."""
    from sqlalchemy import text
    
    async with engine.begin() as conn:
        # Check database type
        if "postgresql" in settings.db_url.lower():
            # PostgreSQL: Check columns
            check_query = text("""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_name='users' AND column_name IN ('is_blocked', 'is_admin', 'is_teacher', 'is_student', 'role')
            """)
            result = await conn.execute(check_query)
            existing_columns = {row[0] for row in result.fetchall()}
            
            # Add is_blocked if missing
            if 'is_blocked' not in existing_columns:
                print("Adding is_blocked column to users table...")
                await conn.execute(text("ALTER TABLE users ADD COLUMN is_blocked BOOLEAN DEFAULT FALSE NOT NULL"))
                print("✅ Added is_blocked column")
            
            # Migrate role column to boolean flags
            if 'role' in existing_columns and 'is_admin' not in existing_columns:
                print("Migrating role column to boolean flags...")
                # Add new columns
                await conn.execute(text("ALTER TABLE users ADD COLUMN is_admin BOOLEAN DEFAULT FALSE NOT NULL"))
                await conn.execute(text("ALTER TABLE users ADD COLUMN is_teacher BOOLEAN DEFAULT FALSE NOT NULL"))
                await conn.execute(text("ALTER TABLE users ADD COLUMN is_student BOOLEAN DEFAULT TRUE NOT NULL"))
                
                # Migrate data from role enum to boolean flags
                await conn.execute(text("""
                    UPDATE users 
                    SET is_admin = (role = 'admin'),
                        is_teacher = (role = 'teacher'),
                        is_student = (role = 'student')
                """))
                
                print("✅ Migrated role column to boolean flags")
                print("⚠️  Note: Old 'role' column still exists. You can drop it manually if needed.")
            elif 'is_admin' in existing_columns:
                print("✅ Role columns already migrated")
        
        elif "sqlite" in settings.db_url.lower():
            # SQLite: Check columns
            check_query = text("PRAGMA table_info(users)")
            result = await conn.execute(check_query)
            columns = {row[1] for row in result.fetchall()}
            
            # Add is_blocked if missing
            if 'is_blocked' not in columns:
                print("Adding is_blocked column to users table...")
                await conn.execute(text("ALTER TABLE users ADD COLUMN is_blocked BOOLEAN DEFAULT 0 NOT NULL"))
                print("✅ Added is_blocked column")
            
            # Migrate role column to boolean flags
            if 'role' in columns and 'is_admin' not in columns:
                print("Migrating role column to boolean flags...")
                # Add new columns
                await conn.execute(text("ALTER TABLE users ADD COLUMN is_admin BOOLEAN DEFAULT 0 NOT NULL"))
                await conn.execute(text("ALTER TABLE users ADD COLUMN is_teacher BOOLEAN DEFAULT 0 NOT NULL"))
                await conn.execute(text("ALTER TABLE users ADD COLUMN is_student BOOLEAN DEFAULT 1 NOT NULL"))
                
                # Migrate data from role enum to boolean flags
                await conn.execute(text("""
                    UPDATE users 
                    SET is_admin = (role = 'admin'),
                        is_teacher = (role = 'teacher'),
                        is_student = (role = 'student')
                """))
                
                print("✅ Migrated role column to boolean flags")
                print("⚠️  Note: Old 'role' column still exists. You can drop it manually if needed.")
            elif 'is_admin' in columns:
                print("✅ Role columns already migrated")


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

