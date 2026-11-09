# Reaction Bot — Fixed Admin Edition

## Render
Build command:
`pip install -r requirements.txt`

Start command:
`python main.py`

Environment variables:
- `BOT_TOKEN` — main bot token
- `ADMIN_PASSWORD` — HTML admin login password
- `FLASK_SECRET_KEY` — long random secret (Render can generate this)

Admin:
`https://YOUR-SERVICE.onrender.com/admin`

## Reaction Bot
1. Add the reaction bot token in Admin → Reaction Bots.
2. Add the target channel ID.
3. Make that reaction bot an administrator in the target channel.
4. Add comma-separated emoji, e.g. `👍, ❤️, 🔥`.

The reaction listener now handles `channel_post` and `edited_channel_post` updates and logs successful reactions.

For a message that is sent by the *same bot token* that is doing the reacting, Telegram may not deliver that bot's own outgoing message back as an update. In that case call `/api/react_message` immediately after sending/forwarding, using the returned message ID.
