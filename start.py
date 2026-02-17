"""Single entry point to run the entire app — web server + Telegram bot."""

import asyncio
import logging
import os
import subprocess

import uvicorn
from config import TELEGRAM_BOT_TOKEN, WEB_PORT
from db import init_db

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


def _build_frontend_if_needed():
    """Build the React frontend if dist/ is missing or stale."""
    frontend_dir = os.path.join(os.path.dirname(__file__), "frontend")
    dist_dir = os.path.join(frontend_dir, "dist")
    src_dir = os.path.join(frontend_dir, "src")
    node_modules = os.path.join(frontend_dir, "node_modules")

    if not os.path.isdir(frontend_dir):
        logger.warning("frontend/ directory not found, skipping build")
        return

    # Install deps if needed
    if not os.path.isdir(node_modules):
        logger.info("Installing frontend dependencies...")
        subprocess.run(["npm", "install"], cwd=frontend_dir, check=True)

    # Build if dist/ doesn't exist or src/ is newer
    need_build = not os.path.isdir(dist_dir)
    if not need_build:
        dist_mtime = os.path.getmtime(dist_dir)
        for root, _, files in os.walk(src_dir):
            for f in files:
                if os.path.getmtime(os.path.join(root, f)) > dist_mtime:
                    need_build = True
                    break
            if need_build:
                break

    if need_build:
        logger.info("Building frontend...")
        subprocess.run(["npm", "run", "build"], cwd=frontend_dir, check=True)
        logger.info("Frontend build complete")
    else:
        logger.info("Frontend dist/ is up to date")


async def _run_telegram_bot():
    """Start the Telegram bot (non-blocking)."""
    if not TELEGRAM_BOT_TOKEN:
        logger.info("TELEGRAM_BOT_TOKEN not set — Telegram bot disabled")
        return

    from telegram.ext import Application, CommandHandler, MessageHandler, filters
    from bot import start_command, clear_command, handle_message

    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("clear", clear_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    await app.initialize()
    await app.start()
    await app.updater.start_polling()
    logger.info("Telegram bot started")

    # Keep running until cancelled
    try:
        await asyncio.Event().wait()
    finally:
        await app.updater.stop()
        await app.stop()
        await app.shutdown()


async def _run_web_server():
    """Start the uvicorn web server (non-blocking)."""
    from web import app

    config = uvicorn.Config(
        app,
        host="0.0.0.0",
        port=WEB_PORT,
        log_level="info",
    )
    server = uvicorn.Server(config)
    await server.serve()


async def main():
    await init_db()
    logger.info("Database initialized")

    tasks = [
        asyncio.create_task(_run_web_server()),
    ]

    if TELEGRAM_BOT_TOKEN:
        tasks.append(asyncio.create_task(_run_telegram_bot()))

    logger.info(f"Web UI: http://localhost:{WEB_PORT}")
    if TELEGRAM_BOT_TOKEN:
        logger.info("Telegram bot: enabled")
    else:
        logger.info("Telegram bot: disabled (no TELEGRAM_BOT_TOKEN)")

    # Wait for any task to finish (or crash)
    done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)

    # If one crashes, cancel the rest
    for t in pending:
        t.cancel()
    for t in done:
        if t.exception():
            logger.error(f"Task crashed: {t.exception()}")


if __name__ == "__main__":
    _build_frontend_if_needed()
    asyncio.run(main())
