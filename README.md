## Telegram Vocabulary Test Bot (Turkish–Uzbek)

This project is a Telegram bot for Turkish–Uzbek vocabulary training with CEFR levels.

### Roles
- **Admin**: manages teachers, can upload word lists.
- **Teacher**: uploads word lists (Turkish–Uzbek pairs) tied to CEFR levels (A1, A2, B1, etc.).
- **Student**: takes tests where a word is shown in one language and they type the translation.

### High-level features
- Upload word lists from teachers/admins.
- Store words grouped by CEFR level.
- Students can:
  - Choose level (A1, A2, …).
  - Choose direction (TR→UZ or UZ→TR).
  - Answer tests; can skip, choose “no answer”, and see overall result at the end.

### Quick start (development)
1. Create and activate a virtualenv.
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Create a `.env` file:
   ```bash
   BOT_TOKEN=your_telegram_bot_token_here
   ADMIN_IDS=123456789,987654321
   ```
4. **Database setup** (automatic):
   - The database (`bot.db`) is created automatically on first run
   - No manual setup required!
   - If you need to reset/recreate the database:
     ```bash
     python -m src.migrate_db --reset
     ```
5. Run the bot:
   ```bash
   python -m src.main
   ```

### Database
- **Default**: SQLite (`bot.db` file in project root)
- **Auto-created**: Tables are created automatically when the bot starts
- **To change database**: Set `DB_URL` in `.env` (e.g., `DB_URL=postgresql+asyncpg://user:pass@localhost/dbname`)


