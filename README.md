# Twitter → Telegram Monitor Bot

A bot that monitors your Twitter/X account and automatically sends new tweets to a Telegram chat or channel.

## How It Works

1. **On every startup** — immediately sends your latest tweet to Telegram
2. **Every N minutes** — checks for new tweets and sends them as they appear
3. **Clean URLs** — all links are in the format `https://twitter.com/user/status/123` (no `?s=20` or other tracking parameters)
4. **Nitter fallback** — uses 5 public Nitter instances; automatically switches if one is unavailable

---

## Quick Start

### 1. Copy files to your VPS

```bash
git clone <repo> twitter_bot
cd twitter_bot
```

### 2. Install Python 3.10+

```bash
sudo apt update && sudo apt install python3 python3-pip python3-venv -y
```

### 3. Create a virtual environment

```bash
python3 -m venv venv
source venv/bin/activate
```

### 4. Install dependencies

```bash
pip install -r requirements.txt
```

### 5. Configure `.env`

```bash
cp .env.example .env
nano .env
```

Fill in your values:

| Variable | Description |
|----------|-------------|
| `TWITTER_USERNAME` | Your Twitter username **without** the `@` |
| `TELEGRAM_BOT_TOKEN` | Token from [@BotFather](https://t.me/BotFather) |
| `TELEGRAM_CHAT_ID` | Chat or channel ID to send tweets to |
| `CHECK_INTERVAL_MINUTES` | How often to check for new tweets (default: `5`) |

#### How to get your Telegram Chat ID

- **Personal chat**: send any message to your bot, then use [@userinfobot](https://t.me/userinfobot)
- **Channel**: add [@getidsbot](https://t.me/getidsbot) to the channel — it will show the ID — then remove it

### 6. Run

```bash
python bot.py
```

> **On every start**, the bot sends the most recent tweet immediately, then continues monitoring.

---

## Run Modes

```bash
# Normal monitoring mode (sends latest tweet on start, then checks every N minutes)
python bot.py

# Send the latest tweet to Telegram right now (for testing)
python bot.py --send-now

# Show the latest tweet in console without sending
python bot.py --test
```

---

## Message Format

```
🐦 New tweet!

Tweet text goes here...

🔗 Open tweet
📅 20.06.2026 00:30 UTC
```

---

## Auto-start with systemd (Linux VPS)

### Create the service file

```bash
sudo nano /etc/systemd/system/twitter-bot.service
```

Paste the following (replace paths and username):

```ini
[Unit]
Description=Twitter → Telegram Monitor Bot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=<your_linux_user>
WorkingDirectory=/path/to/twitter_bot
ExecStart=/path/to/twitter_bot/venv/bin/python bot.py
Restart=on-failure
RestartSec=30
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

### Enable and start

```bash
sudo systemctl daemon-reload
sudo systemctl enable twitter-bot
sudo systemctl start twitter-bot

# Check status
sudo systemctl status twitter-bot

# Follow logs
sudo journalctl -u twitter-bot -f
```

---

## Project Structure

```
twitter_bot/
├── bot.py              # Main file — async loop, Telegram sender
├── config.py           # Loads config from .env
├── rss_parser.py       # Nitter RSS parser with fallback
├── state.py            # Saves seen tweet IDs to JSON
├── seen_tweets.json    # Auto-created cache file
├── bot.log             # Log file
├── requirements.txt    # Python dependencies
├── .env                # Your secrets — DO NOT commit to git!
├── .env.example        # Config template
└── .gitignore
```

---

## Notes

- `seen_tweets.json` is created automatically on first run
- Logs are written to both console and `bot.log`
- **Never commit `.env` to git** — it contains your bot token
- Nitter instances may occasionally be slow; the bot tries up to 5 different servers automatically
