# Reaction Bot — Railway Fixed Final

## Railway
Build command:
`pip install -r requirements.txt`

Start command:
`python BOT.py`

## Required Variables
- `BOT_TOKEN` = main bot token
- `ADMIN_PASSWORD` = HTML admin login password

Optional:
- `FLASK_SECRET_KEY` = long random secret
- `DATABASE_FILE` = database path (default `bot_database.json`)

## HTML Admin
Open:
`https://YOUR-RAILWAY-DOMAIN/admin`

## Reaction Bot Setup
In HTML Admin → Reaction Bots:
1. Enter the **separate reaction bot token**.
2. Enter the exact channel ID, e.g. `-1001234567890`.
3. Enter an emoji, e.g. `❤️` or `🔥`.
4. Click Add & Verify.

The server verifies:
- token is valid
- channel is reachable by that bot
- the reaction bot's status is `administrator` or `creator`

The worker then uses Telegram Bot API `getUpdates` with only `channel_post` and `edited_channel_post` updates and calls `setMessageReaction` for the configured channel.

## Important
Do NOT use the main `BOT_TOKEN` as a reaction-bot token. Each reaction worker needs its own bot token so it can have its own polling stream.

The reaction bot must be an administrator in the target channel. If Telegram rejects the reaction, the Railway logs will show the exact Bot API error description.
