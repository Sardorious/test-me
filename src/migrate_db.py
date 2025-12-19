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
    from .models import Unit, WordList
    
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
                # Cast enum to text for comparison in PostgreSQL
                await conn.execute(text("""
                    UPDATE users 
                    SET is_admin = (role::text = 'admin'),
                        is_teacher = (role::text = 'teacher'),
                        is_student = (role::text = 'student')
                """))
                
                # Make role column nullable so new inserts don't require it
                print("Making role column nullable...")
                try:
                    await conn.execute(text("ALTER TABLE users ALTER COLUMN role DROP NOT NULL"))
                    print("✅ Made role column nullable")
                except Exception as e:
                    print(f"⚠️  Could not make role column nullable: {e}")
                    print("   You may need to manually alter the column or drop it.")
                
                print("✅ Migrated role column to boolean flags")
                print("⚠️  Note: Old 'role' column still exists but is now nullable. You can drop it manually if needed.")
            elif 'is_admin' in existing_columns:
                print("✅ Role columns already migrated")
                # Check if role column is still NOT NULL and make it nullable
                if 'role' in existing_columns:
                    print("Checking if role column needs to be made nullable...")
                    try:
                        await conn.execute(text("ALTER TABLE users ALTER COLUMN role DROP NOT NULL"))
                        print("✅ Made role column nullable")
                    except Exception as e:
                        # Column might already be nullable or error occurred
                        print(f"   Role column status check: {str(e)[:100]}")
            
            # Migrate to Unit-based structure
            await migrate_to_unit_structure(conn, "postgresql")
        
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
                # Cast enum to text for comparison in PostgreSQL
                await conn.execute(text("""
                    UPDATE users 
                    SET is_admin = (role::text = 'admin'),
                        is_teacher = (role::text = 'teacher'),
                        is_student = (role::text = 'student')
                """))
                
                print("✅ Migrated role column to boolean flags")
                print("⚠️  Note: Old 'role' column still exists. You can drop it manually if needed.")
            elif 'is_admin' in columns:
                print("✅ Role columns already migrated")
            
            # Migrate to Unit-based structure
            await migrate_to_unit_structure(conn, "sqlite")


async def migrate_to_unit_structure(conn, db_type: str) -> None:
    """Migrate existing WordList structure to use Units."""
    from sqlalchemy import text
    from .db import Base
    
    print("\n📦 Checking Unit-based structure...")
    
    # First, ensure units table exists by creating it
    await conn.run_sync(lambda sync_conn: Base.metadata.create_all(sync_conn, checkfirst=True))
    
    # Check if word_lists has unit_id column
    if db_type == "postgresql":
        check_unit_id = text("""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name='word_lists' AND column_name='unit_id'
        """)
    else:
        check_unit_id = text("PRAGMA table_info(word_lists)")
    
    result = await conn.execute(check_unit_id)
    if db_type == "postgresql":
        has_unit_id = 'unit_id' in {row[0] for row in result.fetchall()}
    else:
        columns = {row[1] for row in result.fetchall()}
        has_unit_id = 'unit_id' in columns
    
    if not has_unit_id:
        print("Adding unit_id column to word_lists table...")
        
        # Add unit_id column
        try:
            if db_type == "postgresql":
                await conn.execute(text("ALTER TABLE word_lists ADD COLUMN unit_id INTEGER"))
            else:
                await conn.execute(text("ALTER TABLE word_lists ADD COLUMN unit_id INTEGER"))
            print("✅ Added unit_id column")
        except Exception as e:
            print(f"⚠️  Could not add unit_id column: {e}")
            # Column might already exist or there's another issue
            return
        
        # Check if word_lists has cefr_level column (old structure)
        if db_type == "postgresql":
            check_cefr = text("""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_name='word_lists' AND column_name='cefr_level'
            """)
        else:
            check_cefr = text("PRAGMA table_info(word_lists)")
        
        result = await conn.execute(check_cefr)
        if db_type == "postgresql":
            has_cefr = 'cefr_level' in {row[0] for row in result.fetchall()}
        else:
            columns = {row[1] for row in result.fetchall()}
            has_cefr = 'cefr_level' in columns
        
        if has_cefr:
            print("Migrating existing WordLists to Units...")
            
            # Get all unique CEFR levels from word_lists
            get_levels = text("SELECT DISTINCT cefr_level FROM word_lists WHERE cefr_level IS NOT NULL")
            levels_result = await conn.execute(get_levels)
            levels = [row[0] for row in levels_result.fetchall()]
            
            if not levels:
                print("⚠️  No CEFR levels found in word_lists. Migration skipped.")
                return
            
            # Create default Unit 1 for each CEFR level
            for level in levels:
                # Check if unit already exists
                check_unit = text("""
                    SELECT id FROM units 
                    WHERE cefr_level = :level AND unit_number = 1
                """)
                
                unit_check = await conn.execute(check_unit.bindparams(level=level))
                existing_unit = unit_check.fetchone()
                
                if not existing_unit:
                    # Create Unit 1 for this level
                    if db_type == "postgresql":
                        create_unit = text("""
                            INSERT INTO units (name, cefr_level, unit_number, created_at)
                            VALUES (:name, :level, 1, CURRENT_TIMESTAMP)
                            RETURNING id
                        """)
                        result = await conn.execute(create_unit.bindparams(name=f"Unit 1", level=level))
                        unit_id = result.scalar()
                    else:
                        create_unit = text("""
                            INSERT INTO units (name, cefr_level, unit_number, created_at)
                            VALUES (:name, :level, 1, datetime('now'))
                        """)
                        await conn.execute(create_unit.bindparams(name=f"Unit 1", level=level))
                        
                        # Get the created unit ID
                        get_unit_id = text("""
                            SELECT id FROM units 
                            WHERE cefr_level = :level AND unit_number = 1
                        """)
                        unit_result = await conn.execute(get_unit_id.bindparams(level=level))
                        unit_id = unit_result.scalar()
                    
                    # Update word_lists to use this unit
                    update_lists = text("""
                        UPDATE word_lists 
                        SET unit_id = :unit_id 
                        WHERE cefr_level = :level
                    """)
                    
                    update_result = await conn.execute(update_lists.bindparams(unit_id=unit_id, level=level))
                    affected_rows = update_result.rowcount
                    print(f"  ✅ Created Unit 1 for {level} and migrated {affected_rows} word lists")
            
            print("✅ Unit migration complete!")
        else:
            print("⚠️  word_lists table doesn't have cefr_level column. New structure already in place.")
    else:
        print("✅ Unit structure already migrated (unit_id column exists)")


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

