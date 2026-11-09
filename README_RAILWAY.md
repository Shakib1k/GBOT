# Reaction Bot - Railway Fixed Build

## Environment Variables
- BOT_TOKEN = main Telegram bot token
- ADMIN_PASSWORD = HTML admin login password
- FLASK_SECRET_KEY = long random secret for Flask sessions

## Start command
python BOT.py

## Why this build fixes the Railway crash
The previous build imported `ReactionTypeEmoji` from `telegram`, but the pinned
`python-telegram-bot==20.7` package does not export that symbol. This build
removes that import and uses Telegram Bot API `setMessageReaction` through
`requests` for reactions, so the application can start on Railway.

The admin panel is available at `/admin`.
