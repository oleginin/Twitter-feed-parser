"""
bot.py — Main file for the Twitter → Telegram monitor bot

Usage:
    python bot.py

Dependencies: pip install -r requirements.txt
"""
import argparse
import asyncio
import logging
import signal
import sys
from datetime import timezone

from telegram import Bot
from telegram.constants import ParseMode
from telegram.error import TelegramError

import config
from rss_parser import Tweet, fetch_tweets
from state import add_seen_ids, load_seen_ids

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("bot.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger("TwitterBot")


# ── Message formatting ────────────────────────────────────────────────────────
def format_message(tweet: Tweet) -> str:
    """Formats the Telegram notification message for a tweet."""
    dt = tweet.published.astimezone(timezone.utc)
    date_str = dt.strftime("%d.%m.%Y %H:%M UTC")

    # Truncate long tweets (keep room for link and date)
    text = tweet.text
    if len(text) > 800:
        text = text[:797] + "…"

    # Escape special chars for MarkdownV2
    def esc(s: str) -> str:
        for ch in r"\_*[]()~`>#+-=|{}.!":
            s = s.replace(ch, f"\\{ch}")
        return s

    lines = [
        "🐦 *New tweet\\!*",
        "",
        esc(text),
        "",
        f"🔗 [Open tweet]({tweet.url})",
        f"📅 {esc(date_str)}",
    ]
    return "\n".join(lines)


# ── Send notification ─────────────────────────────────────────────────────────
async def send_tweet_notification(bot: Bot, tweet: Tweet) -> bool:
    """Sends a tweet notification to Telegram. Returns True on success."""
    try:
        await bot.send_message(
            chat_id=config.TELEGRAM_CHAT_ID,
            text=format_message(tweet),
            parse_mode=ParseMode.MARKDOWN_V2,
            disable_web_page_preview=False,  # show link preview card
        )
        logger.info("✅ Sent tweet %s", tweet.id)
        return True
    except TelegramError as exc:
        logger.error("❌ Telegram error sending tweet %s: %s", tweet.id, exc)
        return False


# ── Monitoring loop ───────────────────────────────────────────────────────────
async def check_new_tweets(bot: Bot, seen_ids: set[str]) -> set[str]:
    """
    Fetches RSS feed, finds new tweets, and sends them.
    Number of tweets fetched is controlled by config.INITIAL_FETCH_COUNT.
    Returns updated seen_ids set.
    """
    tweets = fetch_tweets(
        username=config.TWITTER_USERNAME,
        instances=config.NITTER_INSTANCES,
        limit=config.INITIAL_FETCH_COUNT,
    )

    if not tweets:
        logger.warning("Could not fetch tweets (empty list)")
        return seen_ids

    new_tweets = [t for t in tweets if t.id not in seen_ids]

    if not new_tweets:
        logger.debug("No new tweets found")
        return seen_ids

    # Send in chronological order (oldest first)
    new_tweets_sorted = sorted(new_tweets, key=lambda t: t.published)
    logger.info("📨 Found %d new tweet(s), sending…", len(new_tweets_sorted))

    sent_ids: set[str] = set()
    for tweet in new_tweets_sorted:
        success = await send_tweet_notification(bot, tweet)
        if success:
            sent_ids.add(tweet.id)
        # Small delay to avoid Telegram rate limits
        await asyncio.sleep(1)

    return add_seen_ids(seen_ids, sent_ids)


# ── Main loop ─────────────────────────────────────────────────────────────────
async def main() -> None:
    logger.info("=" * 60)
    logger.info("🤖 Twitter → Telegram Bot starting")
    logger.info("   Account  : @%s", config.TWITTER_USERNAME)
    logger.info("   Interval : %d min", config.CHECK_INTERVAL_MINUTES)
    logger.info("=" * 60)

    bot = Bot(token=config.TELEGRAM_BOT_TOKEN)

    # Verify Telegram connection
    try:
        me = await bot.get_me()
        logger.info("🔗 Connected to Telegram as @%s", me.username)
    except TelegramError as exc:
        logger.critical("❌ Failed to connect to Telegram: %s", exc)
        sys.exit(1)

    seen_ids = load_seen_ids()
    interval_sec = config.CHECK_INTERVAL_MINUTES * 60

    # ── Send latest tweet on every startup ────────────────────────────────────
    logger.info("📨 Sending latest tweet on startup…")
    startup_tweets = fetch_tweets(
        username=config.TWITTER_USERNAME,
        instances=config.NITTER_INSTANCES,
        limit=config.INITIAL_FETCH_COUNT,
    )
    if startup_tweets:
        latest = startup_tweets[0]  # most recent
        logger.info("📤 Latest tweet: %s", latest.url)
        await send_tweet_notification(bot, latest)
        # Mark all fetched tweets as seen so the loop won't re-send them
        seen_ids = add_seen_ids(seen_ids, {t.id for t in startup_tweets})
    else:
        logger.warning("⚠️  Could not fetch tweets on startup")

    # ── Graceful shutdown on Ctrl+C / SIGTERM ─────────────────────────────────
    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()

    def _shutdown(sig_name: str) -> None:
        logger.info("⏹  Received %s, shutting down…", sig_name)
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _shutdown, sig.name)
        except NotImplementedError:
            # Windows does not support add_signal_handler for SIGTERM
            pass

    # ── Main monitoring loop ───────────────────────────────────────────────────
    while not stop_event.is_set():
        try:
            seen_ids = await check_new_tweets(bot, seen_ids)
        except Exception as exc:
            logger.exception("⚠️  Unexpected error in monitoring loop: %s", exc)

        # Wait until next check or shutdown signal
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval_sec)
        except asyncio.TimeoutError:
            pass  # Normal — time for next check

    logger.info("👋 Bot stopped")


# ── Instant send mode ─────────────────────────────────────────────────────────
async def send_now(test_only: bool = False) -> None:
    """
    --send-now : fetches the latest tweet and sends it to Telegram (ignores seen_ids).
    --test     : same but only prints to console without sending.
    """
    print(f"🔍 Fetching tweets for @{config.TWITTER_USERNAME}…")
    tweets = fetch_tweets(limit=config.INITIAL_FETCH_COUNT)

    if not tweets:
        print("❌ Could not fetch any tweets. Check your username and Nitter availability.")
        return

    tweet = tweets[0]  # most recent
    print(f"\n✅ Found tweet [{tweet.id}]:")
    print(f"   URL  : {tweet.url}")
    print(f"   Text : {tweet.text[:200]}")
    print(f"   Date : {tweet.published}")

    if test_only:
        print("\n[--test mode] Sending skipped.")
        return

    bot = Bot(token=config.TELEGRAM_BOT_TOKEN)
    try:
        me = await bot.get_me()
        print(f"\n🔗 Connected to Telegram as @{me.username}")
    except TelegramError as exc:
        print(f"❌ Telegram connection error: {exc}")
        return

    success = await send_tweet_notification(bot, tweet)
    if success:
        print("\n✅ Tweet sent to Telegram!")
    else:
        print("\n❌ Failed to send. Check bot.log.")


# ── Helper: find correct TELEGRAM_CHAT_ID ─────────────────────────────────────
async def get_chat_id() -> None:
    """
    Calls getUpdates and prints all chat IDs the bot has interacted with.
    Before running: send /start to your bot in Telegram.
    """
    bot = Bot(token=config.TELEGRAM_BOT_TOKEN)
    print("🔍 Looking up chat_id via getUpdates…")
    print("   (Make sure you sent /start to the bot in Telegram)\n")
    try:
        updates = await bot.get_updates(limit=20, timeout=5)
    except TelegramError as exc:
        print(f"❌ Error: {exc}")
        return

    if not updates:
        print("⚠️  No updates found. Send /start to the bot and try again.")
        return

    seen: set[int] = set()
    for update in updates:
        msg = update.message or update.edited_message or update.channel_post
        if msg and msg.chat.id not in seen:
            seen.add(msg.chat.id)
            chat = msg.chat
            name = chat.username or chat.title or chat.first_name or "—"
            print(f"  chat_id : {chat.id}")
            print(f"  type    : {chat.type}")
            print(f"  name    : {name}")
            print(f"  → Set TELEGRAM_CHAT_ID={chat.id} in your .env\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Twitter → Telegram Monitor Bot")
    parser.add_argument(
        "--send-now",
        action="store_true",
        help="Immediately send the latest tweet to Telegram (for testing)",
    )
    parser.add_argument(
        "--test",
        action="store_true",
        help="Show the latest tweet in console without sending",
    )
    parser.add_argument(
        "--get-chat-id",
        action="store_true",
        help="Show available chat IDs (send /start to the bot first)",
    )
    args = parser.parse_args()

    try:
        if args.get_chat_id:
            asyncio.run(get_chat_id())
        elif args.send_now:
            asyncio.run(send_now(test_only=False))
        elif args.test:
            asyncio.run(send_now(test_only=True))
        else:
            asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Stopped by user")
