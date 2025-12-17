import os
from dataclasses import dataclass

from dotenv import load_dotenv


load_dotenv()


@dataclass
class Settings:
    bot_token: str
    admin_ids: list[int]
    db_url: str = "sqlite+aiosqlite:///./bot.db"


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
    db_url = os.getenv("DB_URL", "sqlite+aiosqlite:///./bot.db")

    return Settings(bot_token=token, admin_ids=admin_ids, db_url=db_url)


settings = get_settings()


