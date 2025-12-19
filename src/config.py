import os
from dataclasses import dataclass

from dotenv import load_dotenv


load_dotenv()


@dataclass
class Settings:
    bot_token: str
    admin_ids: list[int]
    db_url: str = "sqlite+aiosqlite:///./bot.db"
    google_sheets_credentials_path: str | None = None
    google_sheets_api_key: str | None = None


def get_settings() -> Settings:
    token = os.getenv("BOT_TOKEN", "")
    if not token:
        raise RuntimeError("BOT_TOKEN is not set in environment or .env")

    raw_admins = os.getenv("ADMIN_IDS", "")
    admin_ids: list[int] = []
    for item in raw_admins.split(","):
        item = item.strip()
        if not item:
            continue
        try:
            admin_ids.append(int(item))
        except ValueError:
            continue

    # Allow custom DB URL via environment variable
    # Default: SQLite (no setup required)
    # For PostgreSQL: DB_URL=postgresql+asyncpg://user:password@localhost:5432/dbname
    db_url = os.getenv("DB_URL", "sqlite+aiosqlite:///./bot.db")
    
    # Google Sheets service account credentials path (optional)
    # Path to JSON key file for Google Sheets API
    google_sheets_credentials_path = os.getenv("GOOGLE_SHEETS_CREDENTIALS_PATH", None)
    
    # Google Sheets API key (optional, for public sheets)
    # Get from: https://console.cloud.google.com/apis/credentials
    google_sheets_api_key = os.getenv("GOOGLE_SHEETS_API_KEY", None)

    return Settings(
        bot_token=token,
        admin_ids=admin_ids,
        db_url=db_url,
        google_sheets_credentials_path=google_sheets_credentials_path,
        google_sheets_api_key=google_sheets_api_key
    )


settings = get_settings()


