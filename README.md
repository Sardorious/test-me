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

#### For Windows:
1. Create and activate a virtualenv:
   ```bash
   python -m venv venv
   .\venv\Scripts\activate
   ```
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

#### For Debian/Ubuntu/Linux:
1. Install Python and venv (if not already installed):
   ```bash
   sudo apt update
   sudo apt install python3 python3-venv python3-pip
   ```
2. Create and activate a virtualenv:
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   ```
3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
   **Note**: On Debian/Ubuntu, you may get an "externally-managed-environment" error if you try to install packages system-wide. Always use a virtual environment as shown above.

#### Common steps (after virtualenv setup):
3. **Get your Telegram Chat ID** (for `ADMIN_IDS`):
   - **Method 1** (Easiest): Send a message to [@userinfobot](https://t.me/userinfobot) - it will reply with your user ID
   - **Method 2**: Send a message to [@getidsbot](https://t.me/getidsbot) - it will show your user ID
   - **Method 3**: Send a message to [@RawDataBot](https://t.me/RawDataBot) - it will show detailed info including your ID
   - **Method 4**: Start your bot temporarily and send it `/start` - check the bot logs/console output for your user ID
   
   Your user ID is a number like `123456789`. For multiple admins, separate them with commas: `123456789,987654321`

4. Create a `.env` file (copy from `env.example`):
   ```bash
   # Copy the example file
   cp env.example .env
   
   # Or create manually with:
   BOT_TOKEN=your_telegram_bot_token_here
   ADMIN_IDS=123456789,987654321
   DB_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/telegram_bot
   ```
   **Note**: `DB_URL` is optional - defaults to PostgreSQL if not set. See `env.example` for other database options.
5. **Database setup**:
   - **PostgreSQL**: Create the database first (see Database Configuration section below)
   - Tables are created automatically when the bot starts
   - If you need to reset/recreate the database:
     ```bash
     # Windows
     python -m src.migrate_db --reset
     
     # Linux/Debian
     python3 -m src.migrate_db --reset
     ```
6. Run the bot:
   ```bash
   # Windows
   python -m src.main
   
   # Linux/Debian
   python3 -m src.main
   ```

### Database Configuration

#### PostgreSQL Setup (Default)

1. **Install PostgreSQL**:
   ```bash
   # Debian/Ubuntu
   sudo apt update
   sudo apt install postgresql postgresql-contrib
   
   # Start PostgreSQL service
   sudo systemctl start postgresql
   sudo systemctl enable postgresql
   ```

2. **Create Database and User**:
   ```bash
   # Switch to postgres user
   sudo -u postgres psql
   
   # In PostgreSQL prompt:
   CREATE DATABASE telegram_bot;
   CREATE USER telegram_user WITH PASSWORD 'your_password';
   GRANT ALL PRIVILEGES ON DATABASE telegram_bot TO telegram_user;
   \q
   ```

3. **Configure `.env`**:
   ```bash
   DB_URL=postgresql+asyncpg://telegram_user:your_password@localhost:5432/telegram_bot
   ```

#### Database Options

- **PostgreSQL (default)**: `DB_URL=postgresql+asyncpg://user:password@localhost:5432/dbname`
- **SQLite (alternative)**: `DB_URL=sqlite+aiosqlite:///./bot.db`
- **MySQL (alternative)**: `DB_URL=mysql+aiomysql://user:password@localhost:3306/dbname`

**Notes**:
- Tables are created automatically when the bot starts
- If `DB_URL` is not set in `.env`, it defaults to PostgreSQL
- For SQLite, no database server setup is needed (uses local file)

### Getting Your Telegram Chat ID

To configure `ADMIN_IDS` in your `.env` file, you need to know your Telegram user ID. Here are the easiest methods:

#### Method 1: Using @userinfobot (Recommended)
1. Open Telegram and search for [@userinfobot](https://t.me/userinfobot)
2. Start a chat with the bot
3. Send any message (e.g., `/start`)
4. The bot will reply with your user ID (a number like `123456789`)

#### Method 2: Using @getidsbot
1. Search for [@getidsbot](https://t.me/getidsbot) on Telegram
2. Start the bot and send any message
3. It will display your user ID

#### Method 3: Using @RawDataBot
1. Search for [@RawDataBot](https://t.me/RawDataBot) on Telegram
2. Start the bot
3. It will send you detailed information including your user ID

#### Method 4: From Bot Logs
1. Start your bot with `python3 -m src.main`
2. Send `/start` to your bot
3. Check the console output - your user ID will be logged when you interact with the bot

**Important**: 
- Your user ID is a numeric value (e.g., `123456789`)
- For multiple admins, separate IDs with commas: `ADMIN_IDS=123456789,987654321,111222333`
- Make sure to add your ID to `.env` before running the bot if you want admin privileges


