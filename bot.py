import logging
import os
import time
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from telegram.constants import ParseMode
from config import TELEGRAM_BOT_TOKEN
from agent import run_agent
from db import init_db
from accounts import get_or_create_user, new_conversation
from tools.output import parse_references, generate_references_image

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

MAX_TELEGRAM_MSG_LENGTH = 4096

# Minimum interval between message edits (Telegram rate limits)
MIN_EDIT_INTERVAL = 1.5


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Hi! I'm your financial research assistant.\n\n"
        "Ask me about stocks, funds, bonds, or any financial topic. "
        "I can look up data from US and Chinese markets, generate charts, and create PDF reports.\n\n"
        "Commands:\n"
        "/start - Show this message\n"
        "/clear - Clear conversation history\n\n"
        "Just send me a message to get started!"
    )


async def clear_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = await get_or_create_user("telegram", str(update.effective_user.id))
    await new_conversation(user_id)
    await update.message.reply_text("Conversation history cleared.")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_uid = update.effective_user.id
    user_text = update.message.text

    if not user_text:
        return

    # Send initial status message that we'll keep editing
    status_msg = await update.message.reply_text("Thinking...")
    last_edit_time = time.time()

    async def on_status(text: str):
        """Edit the status message with progress updates, rate-limited."""
        nonlocal last_edit_time
        now = time.time()
        if now - last_edit_time < MIN_EDIT_INTERVAL:
            return  # skip to avoid Telegram rate limits
        try:
            await status_msg.edit_text(text)
            last_edit_time = now
        except Exception:
            pass  # message unchanged or rate limited

    user_id = await get_or_create_user("telegram", str(telegram_uid))

    try:
        result = await run_agent(user_text, user_id=user_id, on_status=on_status)
    except Exception as e:
        logger.error(f"Agent error for user {telegram_uid}: {e}")
        await status_msg.edit_text(f"Sorry, something went wrong: {e}")
        return

    # Extract references from response and generate reference image
    text = result.get("text", "")
    text, refs = parse_references(text)
    ref_image_path = generate_references_image(refs) if refs else None

    # Edit the status message with the final response
    if text:
        # First chunk: edit the existing message
        first_chunk = text[:MAX_TELEGRAM_MSG_LENGTH]
        try:
            await status_msg.edit_text(first_chunk)
        except Exception:
            # If edit fails (e.g. same content), send new message
            await update.message.reply_text(first_chunk)

        # Remaining chunks: send as new messages
        for i in range(MAX_TELEGRAM_MSG_LENGTH, len(text), MAX_TELEGRAM_MSG_LENGTH):
            chunk = text[i:i + MAX_TELEGRAM_MSG_LENGTH]
            await update.message.reply_text(chunk)
    else:
        await status_msg.edit_text("Done, but no text response was generated.")

    # Send any generated files (charts, PDFs)
    for filepath in result.get("files", []):
        if not os.path.exists(filepath):
            continue
        if filepath.endswith(".png"):
            with open(filepath, "rb") as f:
                await update.message.reply_photo(photo=f)
        elif filepath.endswith(".pdf"):
            with open(filepath, "rb") as f:
                await update.message.reply_document(document=f, filename=os.path.basename(filepath))

    # Send references image last
    if ref_image_path and os.path.exists(ref_image_path):
        with open(ref_image_path, "rb") as f:
            await update.message.reply_photo(photo=f)


async def post_init(application):
    await init_db()


def main():
    if not TELEGRAM_BOT_TOKEN:
        print("Error: TELEGRAM_BOT_TOKEN not set in .env")
        return

    app = Application.builder().token(TELEGRAM_BOT_TOKEN).post_init(post_init).build()

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("clear", clear_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Bot started. Listening for messages...")
    app.run_polling()


if __name__ == "__main__":
    main()
