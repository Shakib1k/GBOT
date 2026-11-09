# Reaction Bot - Railway Fixed Build

## Environment Variables
- BOT_TOKEN = main Telegram bot token
- ADMIN_PASSWORD = HTML Admin password
- FLASK_SECRET_KEY = optional; if omitted, a stable secret is derived from BOT_TOKEN + ADMIN_PASSWORD

## Railway
Build command:
`pip install -r requirements.txt`

Start command:
`python BOT.py`

## Admin
Open `/admin` on the Railway public domain.

## Reaction Bot setup
1. Add the reaction bot token in Admin > Reaction Bots.
2. Enter the target channel ID (for example `-1001234567890`).
3. Enter an emoji. If multiple are entered comma-separated, the first emoji is used because Telegram allows a bot to set one reaction per message.
4. The reaction bot must be an administrator in the target channel.
5. The fixed listener uses full Telegram Update objects so `channel_post` and `edited_channel_post` are received reliably.

## Persistence
Reaction bot configuration and app data are stored in `bot_database.json` so a Railway restart does not immediately erase the configuration. For production persistence across service replacement, attach a Railway Volume or move the DB to an external database.
